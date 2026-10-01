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
    assert result["failedCases"] == [{"name": "b", "message": "boom"}]
