"""Kopf handlers: create the verification Job and watch it to completion.

Flow:

  1. ``on.create`` builds a Kubernetes Job (robot image running
     ``inferverify.job_runner``) and marks the check Pending.
  2. ``on.timer`` polls the Job every 10s; once the Job finishes, it reads the
     result JSON from the Job pod's stdout and writes Verified / Degraded /
     Unknown back to the check's status.

The robot work runs inside the Job pod, isolated from the operator process.
"""

import json
import os

import kopf
import kubernetes.client as k8s
import kubernetes.config

SUITE_ROOT = "/app/tests"
JOB_IMAGE = os.environ.get("INFERVERIFY_IMAGE", "inferverify:latest")
RESULT_PREFIX = "INFERVERIFY_RESULT:"
PROGRESS_PREFIX = "INFERVERIFY_PROGRESS:"
POLL_INTERVAL = 10.0
JOB_TIMEOUT_SECONDS = 300

# Lazily initialized API clients: loading kube config has side effects (reads
# the in-cluster token or ~/.kube/config), so we defer it until a handler
# actually runs, keeping the module importable in unit tests.
_batch_api = None
_core_api = None


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


def _job_name(check_name):
    return f"{check_name}-verify"


def _suite_paths(suites):
    suites = suites or ["smoke"]
    return [f"{SUITE_ROOT}/{name}.robot" for name in suites]


def _build_job(name, namespace, suites, target, thresholds):
    env = [
        k8s.V1EnvVar(name="SUITES", value=",".join(_suite_paths(suites))),
        k8s.V1EnvVar(name="TARGET", value=target or ""),
        k8s.V1EnvVar(name="THRESHOLDS_JSON", value=json.dumps(thresholds or {})),
        k8s.V1EnvVar(name="REPORT_DIR", value="/tmp/reports"),
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
        metadata=k8s.V1ObjectMeta(name=_job_name(name), namespace=namespace),
        spec=spec,
    )


def _read_logs(core_api, name, namespace):
    """Return the Job pod's stdout lines (empty if none readable yet)."""
    pods = core_api.list_namespaced_pod(
        namespace=namespace, label_selector=f"check={name}"
    )
    for pod in pods.items:
        try:
            logs = core_api.read_namespaced_pod_log(
                name=pod.metadata.name, namespace=namespace
            )
        except k8s.ApiException:
            continue
        return logs.splitlines()
    return []


def _read_result(core_api, name, namespace):
    """Read the result JSON line from the Job pod's stdout."""
    for line in _read_logs(core_api, name, namespace):
        if line.startswith(RESULT_PREFIX):
            return json.loads(line[len(RESULT_PREFIX):])
    return None


def _read_latest_progress(core_api, name, namespace):
    """Read the latest progress JSON line from the Job pod's stdout."""
    latest = None
    for line in _read_logs(core_api, name, namespace):
        if line.startswith(PROGRESS_PREFIX):
            latest = json.loads(line[len(PROGRESS_PREFIX):])
    return latest


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

    job = _build_job(
        name, namespace,
        spec.get("suites"),
        spec.get("target"),
        spec.get("thresholds"),
    )
    _get_batch_api().create_namespaced_job(namespace=namespace, body=job)


@kopf.timer(
    "verification.inferguard.io/v1alpha1", "inferencechecks",
    interval=POLL_INTERVAL,
)
def watch_job(status, patch, name, namespace, logger, **_):
    phase = (status or {}).get("phase", "")
    if phase in ("Verified", "Degraded", "Unknown"):
        return  # already settled, stop polling

    batch_api = _get_batch_api()
    try:
        job = batch_api.read_namespaced_job(name=_job_name(name), namespace=namespace)
    except k8s.ApiException as exc:
        if exc.status == 404:
            return  # job not created yet
        raise

    # Not finished: still running (or waiting for a node). Surface live progress.
    if job.status.succeeded is None and job.status.failed is None:
        progress = _read_latest_progress(_get_core_api(), name, namespace)
        if progress:
            patch.status["progress"] = progress
        return

    result = _read_result(_get_core_api(), name, namespace)
    if result is None:
        patch.status["phase"] = "Unknown"
        patch.status["message"] = "job finished but result could not be parsed"
        return

    # Drop the internal return code before writing back.
    result.pop("returnCode", None)
    patch.status.update(result)
    logger.info(
        "InferenceCheck %s/%s settled: %s", namespace, name, result.get("phase")
    )
