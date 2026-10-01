"""Aggregate listener results into the InferenceCheck status outcome.

The listener already classified every test case as PASS/FAIL. Here we turn that
into the status fields the CR expects:

  phase        — Verified (all passed) | Degraded (any failed)
  passedCases  — count of passing cases
  failedCases  — list of {name, message} for every failed case

The assertion detail (expected vs actual) lives in the failure message, which
the Robot keywords format as human-readable text, so we keep it verbatim.
"""


def build_result(listener):
    failed = listener.failed
    phase = "Verified" if not failed else "Degraded"

    return {
        "phase": phase,
        "passedCases": len(listener.passed),
        "failedCases": [
            {"name": r["name"], "message": r["message"]}
            for r in failed
        ],
    }
