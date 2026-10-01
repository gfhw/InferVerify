"""AI 推理验证关键字库。

让用户写一个 InferenceCheck CR 就能跑 AI 语义的断言,不用懂 Robot、不用懂
vLLM/TGI/SGLang 的指标细节。关键字通过 Robot 变量 ``${TARGET}`` 拿到推理服务地址,
从 ``/metrics`` 读取原生 Prometheus 指标并做断言。

失败时 message 固定为 ``<指标> 超阈值: expected <X>, actual = Y`` 的格式,供
operator 的 result 解析成结构化的 expected/actual。

指标名目前按 vLLM 约定,后续按 engine 分支适配 TGI/SGLang。
"""

import requests
from robot.libraries.BuiltIn import BuiltIn


class InferGuardLibrary:
    ROBOT_LIBRARY_SCOPE = "GLOBAL"

    def _target(self):
        target = BuiltIn().get_variable_value("${TARGET}")
        if not target:
            raise AssertionError("缺少 ${TARGET} 变量(推理服务地址)")
        return target.rstrip("/")

    def _metrics(self):
        url = f"{self._target()}/metrics"
        resp = requests.get(url, timeout=10)
        if resp.status_code != 200:
            raise AssertionError(
                f"无法访问 {url}: HTTP {resp.status_code}"
            )
        return resp.text

    @staticmethod
    def _metric_value(text, name):
        """提取第一个匹配的 Prometheus 指标值(取样本中最后一条)。

        Prometheus 文本格式: ``name{labels} value``。同名指标可能带不同 label,
        这里取最后一个样本(通常是聚合样本),够用且不依赖 label 细节。
        """
        value = None
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("#") or not line:
                continue
            if line.startswith(name):
                try:
                    value = float(line.rsplit(" ", 1)[1])
                except (IndexError, ValueError):
                    continue
        return value

    def inference_service_ready(self):
        """推理服务 /health 可达且返回 200。"""
        url = f"{self._target()}/health"
        resp = requests.get(url, timeout=5)
        if resp.status_code != 200:
            raise AssertionError(f"推理服务未就绪: HTTP {resp.status_code}")

    def verify_ttft_below(self, ms):
        """断言 P99 首 token 延迟(TTFT)低于阈值(ms)。

        优先取 summary 的分位数,回退到 histogram 的近似均值。
        """
        ms = float(ms)
        metrics = self._metrics()
        ttft = self._metric_value(metrics, "vllm:time_to_first_token_seconds_quantile")
        if ttft is None:
            # histogram: 用 sum/count 估算均值(非 P99,标注清楚)
            total = self._metric_value(metrics, "vllm:time_to_first_token_seconds_sum")
            count = self._metric_value(metrics, "vllm:time_to_first_token_seconds_count")
            ttft = (total / count * 1000.0) if (total is not None and count) else None
        if ttft is None:
            raise AssertionError("无法从 /metrics 获取 TTFT 指标")
        if ttft > ms:
            raise AssertionError(
                f"TTFT 超阈值: expected < {ms}ms, actual = {ttft}ms"
            )

    def verify_kv_cache_below(self, percent):
        """断言 KV-cache 占用率低于阈值(%)。"""
        percent = float(percent)
        metrics = self._metrics()
        usage = self._metric_value(metrics, "vllm:gpu_cache_usage_perc")
        if usage is None:
            raise AssertionError("无法从 /metrics 获取 KV-cache 占用指标")
        if usage > percent:
            raise AssertionError(
                f"KV-cache 超阈值: expected < {percent}%, actual = {usage}%"
            )
