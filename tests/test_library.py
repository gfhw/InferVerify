"""Tests for the AI inference keyword library (metric parsing)."""

from inferverify.library import InferGuardLibrary


def test_metric_value_parses_prometheus_text():
    text = "\n".join([
        "# HELP vllm:gpu_cache_usage_perc GPU KV-cache usage",
        'vllm:gpu_cache_usage_perc{gpu="0"} 12.5',
        'vllm:gpu_cache_usage_perc{gpu="1"} 88.0',
    ])
    assert InferGuardLibrary._metric_value(text, "vllm:gpu_cache_usage_perc") == 88.0


def test_metric_value_ignores_comments_and_unknown():
    text = "\n".join([
        "# some comment",
        "vllm:other_metric 1.0",
    ])
    assert InferGuardLibrary._metric_value(text, "vllm:gpu_cache_usage_perc") is None


def test_metric_value_returns_none_on_empty():
    assert InferGuardLibrary._metric_value("", "anything") is None
