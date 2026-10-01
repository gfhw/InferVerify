*** Settings ***
Library    RequestsLibrary

*** Variables ***
# 通用示例:标准 RequestsLibrary,不依赖 AI 关键字库。
# operator 会通过 --variable TARGET:... 覆盖。
${TARGET}    http://localhost:8080

*** Test Cases ***
服务健康检查
    [Documentation]    目标服务 /health 可达且返回 200
    GET    ${TARGET}/health
    Status Should Be    200
