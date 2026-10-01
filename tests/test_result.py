"""Tests for result aggregation (result.build_result)."""

from inferverify.result import build_result


class _FakeListener:
    def __init__(self, passed, failed):
        self._passed = passed
        self._failed = failed

    @property
    def passed(self):
        return self._passed

    @property
    def failed(self):
        return self._failed


def test_all_passed_is_verified():
    listener = _FakeListener(
        passed=[{"name": "a", "status": "PASS", "message": ""}],
        failed=[],
    )
    result = build_result(listener)
    assert result["phase"] == "Verified"
    assert result["passedCases"] == 1
    assert result["failedCases"] == []


def test_any_failed_is_degraded():
    listener = _FakeListener(
        passed=[{"name": "a", "status": "PASS", "message": ""}],
        failed=[{"name": "b", "status": "FAIL", "message": "boom"}],
    )
    result = build_result(listener)
    assert result["phase"] == "Degraded"
    assert result["passedCases"] == 1
    assert len(result["failedCases"]) == 1


def test_failed_case_extracts_expected_actual():
    listener = _FakeListener(
        passed=[],
        failed=[{
            "name": "TTFT 达标",
            "status": "FAIL",
            "message": "TTFT 超阈值: expected < 5000.0ms, actual = 8100.0ms",
        }],
    )
    result = build_result(listener)
    case = result["failedCases"][0]
    assert case["name"] == "TTFT 达标"
    assert case["expected"] == "< 5000.0ms"
    assert case["actual"] == "8100.0ms"


def test_failed_case_without_markers():
    listener = _FakeListener(
        passed=[],
        failed=[{"name": "c", "status": "FAIL", "message": "plain failure"}],
    )
    result = build_result(listener)
    assert result["failedCases"][0]["expected"] == ""
    assert result["failedCases"][0]["actual"] == ""
