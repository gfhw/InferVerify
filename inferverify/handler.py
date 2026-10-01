"""Kopf handlers: orchestrate the verification Job and reflect its outcome.

Flow:

  1. ``on.create`` creates an empty result ConfigMap and the verification Job
     (robot image running ``inferverify.job_runner``), then marks Pending.
  2. The Job publishes progress and the final result into that ConfigMap.
  3. ``on.event`` watches those ConfigMaps and streams progress/result back into
     the InferenceCheck status — no polling, near-realtime.
  4. If ``spec.approval.required`` is set and verification passed, the phase
     becomes ``PendingApproval`` until the user flips ``spec.approval.approved``,
     handled by ``on.field``.
"""

import json
import os
import re
import time
from datetime import datetime, timezone

import kopf
import kubernetes.client as k8s
import kubernetes.config

SUITE_ROOT = "/app/tests"
JOB_IMAGE = os.environ.get("INFERVERIFY_IMAGE", "inferverify:latest")
RESULT_CM_LABEL = {"app": "inferverify-result"}
JOB_TIMEOUT_SECONDS = 300

_batch_api = None
_core_api = None
_custom_api = None


def _load_config():
    try:
        kubernetes.config.load_incluster_config()
    except kubernetes.config.ConfigException:
        kubernetes.config.load_kube_config()


def _get_batch_api():
    global _batch_api
    if _batch_api is None:
        _load_config()
        _batch_api = k8s.BatchV1Api()
    return _batch_api


def _get_core_api():
    global _core_api
    if _core_api is None:
        _load_config()
        _core_api = k8s.CoreV1Api()
    return _core_api


def _get_custom_api():
    global _custom_api
    if _custom_api is None:
        _load_config()
        _custom_api = k8s.CustomObjectsApi()
    return _custom_api


def _job_name(check_name):
    return f"{check_name}-verify"


def _result_cm_name(check_name):
    return f"{check_name}-result"


def _suite_paths(suites):
    suites = suites or ["smoke"]
    return [f"{SUITE_ROOT}/{name}.robot" for name in suites]


def _build_job(name, namespace, suites, target, thresholds, job_name=None):
    env = [
        k8s.V1EnvVar(name="SUITES", value=",".join(_suite_paths(suites))),
        k8s.V1EnvVar(name="TARGET", value=target or ""),
        k8s.V1EnvVar(name="THRESHOLDS_JSON", value=json.dumps(thresholds or {})),
        k8s.V1EnvVar(name="REPORT_DIR", value="/tmp/reports"),
        k8s.V1EnvVar(name="RESULT_CONFIGMAP", value=_result_cm_name(name)),
        k8s.V1EnvVar(name="RESULT_NAMESPACE", value=namespace),
    ]
    container = k8s.V1Container(
        name="robot",
        image=JOB_IMAGE,
        image_pull_policy="IfNotPresent",
        command=["python", "-m", "inferverify.job_runner"],
        env=env,
    )
    template = k8s.V1PodTemplateSpec(
        metadata=k8s.V1ObjectMeta(labels={"app": "inferverify-job", "check": name}),
        spec=k8s.V1PodSpec(restart_policy="Never", containers=[container]),
    )
    spec = k8s.V1JobSpec(
        template=template,
        backoff_limit=0,
        active_deadline_seconds=JOB_TIMEOUT_SECONDS,
    )
    return k8s.V1Job(
        api_version="batch/v1",
        kind="Job",
        metadata=k8s.V1ObjectMeta(
            name=job_name or _job_name(name),
            namespace=namespace,
        ),
        spec=spec,
    )


def _ensure_result_cm(name, namespace):
    """Create the empty result ConfigMap (idempotent)."""
    core_api = _get_core_api()
    try:
        core_api.read_namespaced_config_map(_result_cm_name(name), namespace)
    except k8s.ApiException as exc:
        if exc.status == 404:
            body = k8s.V1ConfigMap(
                metadata=k8s.V1ObjectMeta(
                    name=_result_cm_name(name),
                    namespace=namespace,
                    labels={"app": "inferverify-result", "check": name},
                ),
                data={},
            )
            core_api.create_namespaced_config_map(namespace, body)


def _patch_status(name, namespace, status_update):
    """Merge-patch the InferenceCheck status subresource."""
    _get_custom_api().patch_namespaced_custom_object_status(
        group="verification.inferguard.io",
        version="v1alpha1",
        namespace=namespace,
        plural="inferencechecks",
        name=name,
        body={"status": status_update},
    )


def _should_await_approval(spec):
    approval = spec.get("approval") or {}
    return bool(approval.get("required")) and not bool(approval.get("approved"))


@kopf.on.create("verification.inferguard.io/v1alpha1", "inferencechecks")
def create_check(spec, patch, name, namespace, logger, **_):
    release_ref = spec.get("releaseRef", "")
    revision = spec.get("revision", 0)
    logger.info(
        "InferenceCheck %s/%s: creating verification job (release=%s rev=%s)",
        namespace, name, release_ref, revision,
    )

    patch.status["phase"] = "Pending"
    patch.status["message"] = "verification job created"

    _ensure_result_cm(name, namespace)
    job = _build_job(
        name, namespace,
        spec.get("suites"),
        spec.get("target"),
        spec.get("thresholds"),
    )
    _get_batch_api().create_namespaced_job(namespace=namespace, body=job)


@kopf.on.event("", "v1", "configmaps", labels=RESULT_CM_LABEL)
def configmap_changed(event, logger, **_):
    obj = event.get("object") or {}
    meta = obj.get("metadata") or {}
    cm_name = meta.get("name", "")
    namespace = meta.get("namespace", "")
    if not cm_name.endswith("-result"):
        return
    check_name = cm_name[: -len("-result")]
    data = obj.get("data") or {}

    progress_raw = data.get("progress")
    if progress_raw:
        try:
            _patch_status(check_name, namespace, {
                "progress": json.loads(progress_raw),
            })
        except json.JSONDecodeError:
            logger.warning("invalid progress JSON in %s/%s", namespace, cm_name)

    result_raw = data.get("result")
    if not result_raw:
        return
    try:
        result = json.loads(result_raw)
    except json.JSONDecodeError:
        logger.error("invalid result JSON in %s/%s", namespace, cm_name)
        return

    result.pop("returnCode", None)

    # Approval gate: a passing verification may still need human sign-off.
    if result.get("phase") == "Verified":
        spec = _read_check_spec(check_name, namespace)
        if _should_await_approval(spec):
            result["phase"] = "PendingApproval"
            result["message"] = "verification passed, awaiting approval"

    _patch_status(check_name, namespace, result)
    logger.info(
        "InferenceCheck %s/%s reflected: %s", namespace, check_name, result.get("phase")
    )


def _read_check_spec(name, namespace):
    try:
        obj = _get_custom_api().get_namespaced_custom_object(
            group="verification.inferguard.io",
            version="v1alpha1",
            namespace=namespace,
            plural="inferencechecks",
            name=name,
        )
        return obj.get("spec") or {}
    except k8s.ApiException:
        return {}


@kopf.on.field(
    "verification.inferguard.io/v1alpha1", "inferencechecks",
    field="spec.approval.approved",
)
def approval_changed(old, new, name, namespace, logger, **_):
    if not new:
        return  # only act when the user approves (true)
    cm_name = _result_cm_name(name)
    core_api = _get_core_api()
    try:
        cm = core_api.read_namespaced_config_map(cm_name, namespace)
    except k8s.ApiException:
        return
    result_raw = (cm.data or {}).get("result")
    if not result_raw:
        return
    try:
        result = json.loads(result_raw)
    except json.JSONDecodeError:
        return

    result.pop("returnCode", None)

    # Only a passing verification can be approved. If the verification actually
    # degraded, flipping approved=true must not overwrite the real outcome.
    if result.get("phase") != "Verified":
        logger.warning(
            "InferenceCheck %s/%s approval ignored: result is %s",
            namespace, name, result.get("phase"),
        )
        return

    result["message"] = "approved"
    _patch_status(name, namespace, result)
    logger.info("InferenceCheck %s/%s approved", namespace, name)


@kopf.timer(
    "verification.inferguard.io/v1alpha1", "inferencechecks",
    interval=30.0,
)
def timeout_guard(status, name, namespace, logger, **_):
    """Fallback for Jobs that die without writing a result.

    A Job that times out (activeDeadlineSeconds) or crashes before the
    job_runner publishes the result would otherwise leave the check stuck in
    Pending forever, because the ConfigMap watch only reacts to a ``result``
    field. Here we detect a failed Job with no result and settle it as Unknown.
    """
    phase = (status or {}).get("phase", "")
    if phase in ("Verified", "Degraded", "PendingApproval", "Unknown"):
        return  # already settled

    batch_api = _get_batch_api()
    try:
        job = batch_api.read_namespaced_job(name=_job_name(name), namespace=namespace)
    except k8s.ApiException as exc:
        if exc.status == 404:
            return
        raise

    # Job failed (non-zero exit or deadline exceeded) but wrote no result.
    failed = job.status.failed or 0
    if failed == 0:
        return

    core_api = _get_core_api()
    try:
        cm = core_api.read_namespaced_config_map(_result_cm_name(name), namespace)
    except k8s.ApiException:
        return
    if (cm.data or {}).get("result"):
        return  # result actually made it in; let the watch handle it

    _patch_status(name, namespace, {
        "phase": "Unknown",
        "message": "verification job failed without producing a result",
    })
    logger.warning(
        "InferenceCheck %s/%s job failed with no result; marked Unknown", namespace, name
    )


_INTERVAL_RE = re.compile(r"(\d+)([hms])")


def _parse_interval(raw):
    """Parse "6h", "30m", "1h30m" into seconds. Returns 0 when unparseable."""
    if not raw:
        return 0
    total = 0
    for match in _INTERVAL_RE.finditer(str(raw)):
        value = int(match.group(1))
        unit = match.group(2)
        if unit == "h":
            total += value * 3600
        elif unit == "m":
            total += value * 60
        elif unit == "s":
            total += value
    return total


def _now_rfc3339():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_rfc3339(raw):
    if not raw:
        return None
    try:
        dt = datetime.strptime(raw, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except (ValueError, TypeError):
        return None


@kopf.timer(
    "verification.inferguard.io/v1alpha1", "inferencechecks",
    interval=60.0,
)
def schedule_recheck(spec, status, name, namespace, logger, **_):
    """Runtime assurance: periodically re-run verification while the release runs.

    Only active when ``spec.interval`` is set (e.g. "6h"). The timer fires every
    60s but skips until ``interval`` has elapsed since the last check, then
    creates a fresh verification Job (timestamped name). The result overwrites
    the same ConfigMap, and the existing watch reflects it into status.
    """
    interval_seconds = _parse_interval(spec.get("interval"))
    if interval_seconds <= 0:
        return  # runtime assurance disabled

    now = time.time()
    last_ts = _parse_rfc3339((status or {}).get("lastCheckAt"))
    if last_ts and (now - last_ts) < interval_seconds:
        return  # not due yet

    job = _build_job(
        name, namespace,
        spec.get("suites"),
        spec.get("target"),
        spec.get("thresholds"),
        job_name=f"{_job_name(name)}-{int(now)}",
    )
    _get_batch_api().create_namespaced_job(namespace=namespace, body=job)
    _patch_status(name, namespace, {"lastCheckAt": _now_rfc3339()})
    logger.info("InferenceCheck %s/%s recheck job created", namespace, name)
