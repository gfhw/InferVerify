"""Entrypoint executed inside the verification Job container.

Reads the check's parameters from environment variables, runs the Robot suites,
and prints a single JSON result line (prefixed ``INFERVERIFY_RESULT:``) to
stdout so the operator can parse the outcome from the Job's pod logs.

Exit code: 0 when every case passed, 1 otherwise — which also drives the Job's
completion status.
"""

import json
import os
import sys

from robot import run

from inferverify.listener import ProgressListener
from inferverify.result import build_result


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

    listener = ProgressListener()

    rc = run(
        *suites,
        outputdir=report_dir,
        listener=listener,
        variable=_robot_variables(),
        console=None,
        log="log.html",
        report="report.html",
        output="output.xml",
    )

    result = build_result(listener)
    result["returnCode"] = rc
    print("INFERVERIFY_RESULT:" + json.dumps(result), flush=True)

    sys.exit(0 if rc == 0 else 1)


if __name__ == "__main__":
    main()
