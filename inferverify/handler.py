"""Kopf handlers: react to the InferenceCheck CR lifecycle.

The operator watches ``InferenceCheck`` objects. On create it:

  1. marks the check Pending;
  2. runs the requested Robot suites synchronously (in a thread pool, so the
     kopf event loop is not blocked);
  3. aggregates the listener results into Verified / Degraded;
  4. writes the outcome back to ``status``.

Execution model note: the first version runs Robot **in-process** rather than
spawning a Job, because inference verification is a lightweight HTTP probe
(no GPU needed). The runner is isolated behind ``runner.run_suites`` so a
Job-based executor can be swapped in later without touching the handler.
"""

import kopf

from .result import build_result
from .runner import run_suites

# Where the Robot suites live inside the container image.
SUITE_ROOT = "/app/tests"


def _suite_paths(suites):
    """Map suite names (e.g. "smoke") to .robot file paths."""
    paths = []
    for name in suites:
        path = f"{SUITE_ROOT}/{name}.robot"
        paths.append(path)
    return paths


def _robot_variables(spec):
    """Build Robot --variable entries from the CR spec.

    The inference target and every threshold become variables, e.g.
    thresholds.ttftP99Ms -> TTFT_P99_MS=5000.
    """
    variables = []

    target = spec.get("target", "")
    if target:
        variables.append(f"TARGET:{target}")

    thresholds = spec.get("thresholds") or {}
    for key, value in thresholds.items():
        # camelCase -> UPPER_SNAKE_CASE
        name = "".join(
            "_" + c.lower() if c.isupper() else c for c in key
        ).lstrip("_").upper()
        variables.append(f"{name}:{value}")

    return variables


@kopf.on.create("verification.inferguard.io/v1alpha1", "inferencechecks")
def create_check(spec, patch, name, namespace, logger, **_):
    release_ref = spec.get("releaseRef", "")
    revision = spec.get("revision", 0)
    suites = spec.get("suites") or ["smoke"]

    logger.info(
        "InferenceCheck %s/%s: verifying release=%s revision=%s",
        namespace, name, release_ref, revision,
    )

    patch.status["phase"] = "Pending"
    patch.status["message"] = "running robot verification"

    variables = _robot_variables(spec)
    suite_paths = _suite_paths(suites)

    logger.info("Running suites: %s with variables: %s", suites, variables)

    try:
        rc, listener = run_suites(
            suite_paths,
            variables,
            report_dir=f"/tmp/reports/{namespace}-{name}",
            on_progress=lambda *args: logger.info("progress: %s", args),
        )
    except Exception as exc:  # noqa: BLE001 - surface as Unknown, don't crash
        logger.error("Verification raised: %s", exc)
        patch.status["phase"] = "Unknown"
        patch.status["message"] = str(exc)
        return

    result = build_result(listener)
    patch.status.update(result)
    patch.status["reportURL"] = f"/tmp/reports/{namespace}-{name}/report.html"

    if result["phase"] == "Verified":
        logger.info("Verification PASSED for release=%s revision=%s", release_ref, revision)
        patch.status["message"] = f"verified revision {revision}"
    else:
        failed = result["failedCases"]
        logger.warning(
            "Verification DEGRADED for release=%s revision=%s: %s",
            release_ref, revision, failed,
        )
        patch.status["message"] = (
            f"{len(failed)} case(s) failed: "
            + "; ".join(c["name"] for c in failed)
        )
