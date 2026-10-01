"""Tests for handler helpers (_robot_variables, _suite_paths)."""

from inferverify.handler import _robot_variables, _suite_paths


def test_robot_variables_builds_target_and_thresholds():
    spec = {
        "target": "http://llama:8000",
        "thresholds": {"ttftP99Ms": 5000, "throughputMinTokens": 80},
    }
    variables = _robot_variables(spec)
    assert "TARGET:http://llama:8000" in variables
    assert "TTFT_P99_MS:5000" in variables
    assert "THROUGHPUT_MIN_TOKENS:80" in variables


def test_robot_variables_without_thresholds():
    spec = {"target": "http://x"}
    assert _robot_variables(spec) == ["TARGET:http://x"]


def test_robot_variables_missing_target():
    spec = {"thresholds": {"aB": 1}}
    variables = _robot_variables(spec)
    assert "TARGET:" not in "".join(variables)
    assert "A_B:1" in variables


def test_suite_paths():
    assert _suite_paths(["smoke", "regression"]) == [
        "/app/tests/smoke.robot",
        "/app/tests/regression.robot",
    ]
