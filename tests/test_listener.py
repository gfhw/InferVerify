"""Tests for the Robot listener (ProgressListener)."""

from inferverify.listener import ProgressListener


class _FakeResult:
    def __init__(self, passed, message=""):
        self.passed = passed
        self.message = message


class _FakeData:
    def __init__(self, name):
        self.name = name


def test_collects_pass_and_fail():
    events = []
    listener = ProgressListener(on_progress=lambda *args: events.append(args))

    listener.start_test(_FakeData("case-a"), None)
    listener.end_test(_FakeData("case-a"), _FakeResult(True, ""))

    listener.start_test(_FakeData("case-b"), None)
    listener.end_test(_FakeData("case-b"), _FakeResult(False, "boom"))

    assert len(listener.results) == 2
    assert listener.results[0] == {
        "name": "case-a", "status": "PASS", "message": "",
    }
    assert listener.results[1] == {
        "name": "case-b", "status": "FAIL", "message": "boom",
    }
    assert len(listener.passed) == 1
    assert len(listener.failed) == 1
    # one progress event per start/end = 4 events for 2 tests
    assert len(events) == 4


def test_ignores_end_without_start():
    listener = ProgressListener()
    listener.end_test(_FakeData("orphan"), _FakeResult(True, ""))
    assert listener.results == []
