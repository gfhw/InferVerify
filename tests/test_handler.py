"""Tests for handler helpers (_suite_paths)."""

from inferverify.handler import _suite_paths


def test_suite_paths():
    assert _suite_paths(["smoke", "regression"]) == [
        "/app/tests/smoke.robot",
        "/app/tests/regression.robot",
    ]


def test_suite_paths_defaults_to_smoke():
    assert _suite_paths(None) == ["/app/tests/smoke.robot"]
    assert _suite_paths([]) == ["/app/tests/smoke.robot"]
