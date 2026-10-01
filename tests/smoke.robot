*** Settings ***
Library    InferGuardLibrary

*** Variables ***
# Defaults; the operator overrides these via --variable from spec.thresholds.
${TARGET}             http://localhost:8000
${TTFT_P99_MS}        5000
${KV_CACHE_PERCENT}   90

*** Test Cases ***
推理服务就绪
    [Documentation]    推理引擎 /health 可达且返回 200
    Inference Service Ready

TTFT 达标
    [Documentation]    首 token 延迟 P99 低于阈值
    Verify TTFT Below    ${TTFT_P99_MS}

KV-cache 未打满
    [Documentation]    GPU KV-cache 占用率低于阈值
    Verify KV Cache Below    ${KV_CACHE_PERCENT}
