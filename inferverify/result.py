"""Aggregate listener results into the InferenceCheck status outcome.

The listener classified every test case as PASS/FAIL. Here we turn that into
the status fields the CR expects, and pull ``expected`` / ``actual`` out of the
failure message so the outcome is structured (metric vs threshold), not just a
boolean. The keyword library formats failures as
``<metric> 超阈值: expected <X>, actual = Y``.
"""

import re

_EXPECTED_RE = re.compile(r"expected\s+(.+?), actual")
_ACTUAL_RE = re.compile(r"actual\s*=\s*(.+)$")


def _extract(message):
    expected = ""
    actual = ""
    m = _EXPECTED_RE.search(message)
    if m:
        expected = m.group(1).strip()
    m = _ACTUAL_RE.search(message)
    if m:
        actual = m.group(1).strip()
    return expected, actual


def build_result(listener):
    failed = listener.failed
    phase = "Verified" if not failed else "Degraded"

    failed_cases = []
    for r in failed:
        expected, actual = _extract(r["message"])
        failed_cases.append({
            "name": r["name"],
            "message": r["message"],
            "expected": expected,
            "actual": actual,
        })

    return {
        "phase": phase,
        "passedCases": len(listener.passed),
        "failedCases": failed_cases,
    }
