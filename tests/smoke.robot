*** Settings ***
Library    RequestsLibrary

*** Variables ***
# Defaults; overridden by the operator via --variable TARGET:...
${TARGET}    http://localhost:8000

*** Test Cases ***
推理引擎健康检查
    [Documentation]    推理引擎 /health 端点可达且返回 200
    GET    ${TARGET}/health
    Status Should Be    200

模型已加载
    [Documentation]    /v1/models 返回 200,说明模型权重已加载完成
    GET    ${TARGET}/v1/models
    Status Should Be    200
