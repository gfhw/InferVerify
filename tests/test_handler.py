"""Tests for handler helpers (_suite_paths, _should_await_approval, _parse_interval)."""

from inferverify.handler import _parse_interval, _should_await_approval, _suite_paths


def test_suite_paths():
    assert _suite_paths(["smoke", "regression"]) == [
        "/app/tests/smoke.robot",
        "/app/tests/regression.robot",
    ]


def test_suite_paths_defaults_to_smoke():
    assert _suite_paths(None) == ["/app/tests/smoke.robot"]
    assert _suite_paths([]) == ["/app/tests/smoke.robot"]


def test_should_await_approval_required_and_not_approved():
    spec = {"approval": {"required": True, "approved": False}}
    assert _should_await_approval(spec) is True


def test_should_await_approval_required_and_approved():
    spec = {"approval": {"required": True, "approved": True}}
    assert _should_await_approval(spec) is False


def test_should_await_approval_not_required():
    assert _should_await_approval({"approval": {"required": False}}) is False
    assert _should_await_approval({}) is False


def test_parse_interval_hours():
    assert _parse_interval("6h") == 21600


def test_parse_interval_minutes():
    assert _parse_interval("30m") == 1800


def test_parse_interval_compound():
    assert _parse_interval("1h30m") == 5400


def test_parse_interval_empty_or_invalid():
    assert _parse_interval("") == 0
    assert _parse_interval(None) == 0
    assert _parse_interval("abc") == 0

