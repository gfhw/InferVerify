"""Tests for the Job runner entrypoint (job_runner._robot_variables)."""

import json
import os

from inferverify.job_runner import _robot_variables


def _set_env(**kwargs):
    for k in kwargs:
        os.environ[k] = kwargs[k]


def _clear_env(*keys):
    for k in keys:
        os.environ.pop(k, None)


def test_robot_variables_builds_target_and_thresholds():
    _set_env(
        TARGET="http://llama:8000",
        THRESHOLDS_JSON=json.dumps({"ttftP99Ms": 5000, "throughputMinTokens": 80}),
    )
    try:
        variables = _robot_variables()
    finally:
        _clear_env("TARGET", "THRESHOLDS_JSON")

    assert "TARGET:http://llama:8000" in variables
    assert "TTFT_P99_MS:5000" in variables
    assert "THROUGHPUT_MIN_TOKENS:80" in variables


def test_robot_variables_without_thresholds():
    _set_env(TARGET="http://x")
    try:
        assert _robot_variables() == ["TARGET:http://x"]
    finally:
        _clear_env("TARGET")


def test_robot_variables_empty_env():
    _clear_env("TARGET", "THRESHOLDS_JSON")
    assert _robot_variables() == []
