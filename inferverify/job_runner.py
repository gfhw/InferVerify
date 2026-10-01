"""Entrypoint executed inside the verification Job container.

Reads the check's parameters from environment variables, runs the Robot suites,
and publishes the outcome to a ConfigMap (progress updates during the run, the
final result at the end). It also echoes the result to stdout as a fallback for
debugging.

Exit code: 0 when every case passed, 1 otherwise — which also drives the Job's
completion status.
"""

import json
import os
import sys

from kubernetes import client as k8s
from kubernetes import config
from kubernetes.client.rest import ApiException
from robot import run

from inferverify.listener import ProgressListener
from inferverify.result import build_result

PROGRESS_PREFIX = "INFERVERIFY_PROGRESS:"
RESULT_PREFIX = "INFERVERIFY_RESULT:"

_core_api = None


def _get_core_api():
    """Return a CoreV1Api, or None when not running in-cluster (dev/test)."""
    global _core_api
    if _core_api is None:
        try:
            config.load_incluster_config()
        except config.ConfigException:
            return None
        _core_api = k8s.CoreV1Api()
    return _core_api


def _publish_configmap(name, namespace, data):
    """Merge ``data`` into the result ConfigMap. Best-effort: publish errors
    must never fail the verification itself."""
    if not name:
        return
    api = _get_core_api()
    if api is None:
        return
    try:
        try:
            cm = api.read_namespaced_config_map(name, namespace)
            cm.data = cm.data or {}
            cm.data.update(data)
            api.replace_namespaced_config_map(name, namespace, cm)
        except ApiException as exc:
            if exc.status == 404:
                body = k8s.V1ConfigMap(
                    metadata=k8s.V1ObjectMeta(name=name, namespace=namespace),
                    data=data,
                )
                api.create_namespaced_config_map(namespace, body)
    except ApiException:
        pass  # best-effort


def _make_progress_publisher(cm_name, cm_namespace):
    def publish(*args):
        event = {"event": args[0]}
        if len(args) > 1:
            event["test"] = args[1]
        if len(args) > 2:
            event["status"] = args[2]
        # stdout fallback for debugging
        print(PROGRESS_PREFIX + json.dumps(event), flush=True)
        # structured, watchable progress
        _publish_configmap(cm_name, cm_namespace, {"progress": json.dumps(event)})

    return publish


def _env_list(name):
    raw = os.environ.get(name, "")
    return [x for x in raw.split(",") if x]


def _robot_variables():
    """Rebuild Robot --variable entries from the environment."""
    variables = []
    target = os.environ.get("TARGET", "")
    if target:
        variables.append(f"TARGET:{target}")

    thresholds_json = os.environ.get("THRESHOLDS_JSON", "")
    if thresholds_json:
        thresholds = json.loads(thresholds_json)
        for key, value in thresholds.items():
            name = "".join(
                "_" + c.lower() if c.isupper() else c for c in key
            ).lstrip("_").upper()
            variables.append(f"{name}:{value}")

    return variables


def main():
    suites = _env_list("SUITES") or ["/app/tests/smoke.robot"]
    report_dir = os.environ.get("REPORT_DIR", "/tmp/reports")
    cm_name = os.environ.get("RESULT_CONFIGMAP", "")
    cm_namespace = os.environ.get("RESULT_NAMESPACE", "default")

    listener = ProgressListener(
        on_progress=_make_progress_publisher(cm_name, cm_namespace)
    )

    rc = run(
        *suites,
        outputdir=report_dir,
        listener=listener,
        variable=_robot_variables(),
        pythonpath=[os.path.dirname(os.path.dirname(os.path.abspath(__file__)))],
        console=None,
        log="log.html",
        report="report.html",
        output="output.xml",
    )

    result = build_result(listener)
    result["returnCode"] = rc
    print(RESULT_PREFIX + json.dumps(result), flush=True)
    if cm_name:
        _publish_configmap(cm_name, cm_namespace, {"result": json.dumps(result)})

    sys.exit(0 if rc == 0 else 1)


if __name__ == "__main__":
    main()
