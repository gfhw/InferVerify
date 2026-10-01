# InferVerify

**声明式的 Kubernetes Robot 测试/验证 Operator。** 提交一个 `InferenceCheck` CR,它就在集群内起 Job 跑 Robot 用例,把结果回写成结构化的 `Verified / Degraded` 状态,支持定时重跑和人工批准门禁。

它有两个层次的定位:

```
┌─────────────────────────────────────────────────────┐
│  上层(标杆用例):AI 推理验证                          │
│  与 InferGuard 联动,验证"模型部署后是否真的达标"      │
│  TTFT / 吞吐 / KV-cache 定量断言 + 版本回归对比       │
├─────────────────────────────────────────────────────┤
│  底盘(通用):Kubernetes Robot 测试 runner             │
│  测任意 HTTP 服务 / 集群资源,不依赖任何特定领域        │
│  声明式 CR 触发 + Job 隔离执行 + 结果回写 + 门禁      │
└─────────────────────────────────────────────────────┘
```

与 [InferGuard](../InferGuard) 的关系是**平等的两个平台,通过 CR 协作**:InferGuard 负责"部署",InferVerify 负责"验证",靠 `InferenceCheck` CR 解耦——但没有 InferGuard,InferVerify 也能独立作为通用测试平台用。

---

## 定位:补上"活着 ≠ 健康"的缝隙

Helm 的 `--wait` 只保证 Pod Ready,探针只能判"进程活着"(布尔)。它们都回答不了:

> **这个服务/模型现在到底达不达标?运行一段时间后有没有劣化?**

InferVerify 用 Robot Framework 的**定量断言**回答这个问题:声明式地定义"要测什么、阈值是多少",跑用例、测实测值、和阈值对比、输出结构化的 `expected/actual`。对 AI 推理,它补的是"Pod Ready ≠ 模型能按 SLA 推理";对任意服务,它补的是"部署成功 ≠ 运行时达标"。

---

## 架构

```
InferenceCheck CR ──► kopf on.create
                        ├─ 创建结果 ConfigMap + Kubernetes Job(robot 镜像跑 job_runner)
                        ├─ target/阈值 通过环境变量注入(声明式,不改用例)
                        └─ status.phase = Pending

Job 容器 ──► 写 ConfigMap
              ├─ progress 字段(每个用例开始/结束,实时)
              └─ result 字段(验证结束,结构化)

kopf on.event(watch ConfigMap)──► 实时回写 status(无轮询)
              ├─ progress → status.progress(流式)
              ├─ result → status.phase: Verified / Degraded / Unknown
              └─ approval.required 且通过 → PendingApproval(等人工批准)

kopf on.timer(spec.interval 存在时)──► 运行保障
              └─ 每 interval 重建验证 Job,持续保证"还在不在 SLA"
```

**执行模型**:robot 用例跑在**独立的 Job Pod**里(与 operator 进程隔离)。Job 容器把进度和结果写到结果 ConfigMap;operator 通过 `on.event` **watch ConfigMap 变化**实时回写 CR。`spec.approval.required` 时,通过的人工验证停在 `PendingApproval`;`spec.interval` 存在时,定时重跑做持续健康检查。

---

## 用法一:通用 Robot 测试(不依赖 InferGuard)

测任意 HTTP 服务,用标准 Robot 库:

```yaml
apiVersion: verification.inferguard.io/v1alpha1
kind: InferenceCheck
metadata:
  name: my-api-check
spec:
  target: http://my-service.prod.svc:8080
  suites: [api_smoke]       # 你自己的 robot 用例,用标准 RequestsLibrary
  interval: "1h"            # 每小时重跑一次(运行保障)
  thresholds:
    maxLatencyMs: 200       # 阈值作为变量注入用例
```

`releaseRef`/`revision` 留空 = 纯通用测试,不关联任何 ModelRelease。

## 用法二:AI 推理验证(与 InferGuard 联动)

InferGuard 部署成功后,若 `spec.verification.enabled=true`,会自动创建带 `releaseRef`/`revision` 的 InferenceCheck:

```yaml
spec:
  releaseRef: llama-3-8b      # 指向 ModelRelease(联动键,可选)
  revision: 42                # Helm revision(版本画像)
  engine: vllm
  target: http://llama-3-8b.prod.svc:8000
  suites: [smoke]             # 用 AI 关键字库
  interval: "6h"
  thresholds:
    ttftP99Ms: 5000
    kvCachePercent: 90
```

回写后的 status:

```yaml
status:
  phase: Degraded            # Verified | Degraded | PendingApproval | Unknown | Pending
  lastCheckAt: "2025-01-15T06:00:00Z"
  passedCases: 1
  failedCases:
    - name: TTFT 达标
      message: "TTFT 超阈值: expected < 5000.0ms, actual = 8100.0ms"
      expected: "< 5000.0ms"
      actual: "8100.0ms"
  message: "1 case(s) failed: TTFT 达标"
```

---

## 与 InferGuard 的联动

```
InferGuard(Go)  部署成功 + verification.enabled=true
  → 创建 InferenceCheck CR(写 releaseRef/revision/target/thresholds/interval)
  → watch InferenceCheck.status(controller-runtime Watches,事件驱动)
  → 实时回写 ModelRelease.status.verification

InferVerify(Python)  watch InferenceCheck
  → 起 Job 跑 robot 用例
  → 结果写 ConfigMap → watch 回写 status
  → interval 存在时定时重跑(运行保障)
```

**两者不直接通信,靠 `InferenceCheck` CR 作为共享中间态解耦**,各自 watch 各自关心的资源,天然解耦又天然实时。

---

## 相对 kubetest 的差异化

[kubetest](https://kubetest.readthedocs.io/) 是通用 K8s 测试框架(pytest),结果就是 pytest 的 pass/fail、跑在 CI/本地、不回写资源。InferVerify 是它的 **operator 化 + 持续化 + 门禁化**:

1. **声明式触发** —— 提交 CR 即触发,而非写 pytest 代码跑 CI;
2. **集群内隔离执行** —— 起 Job 跑,而非本地/CI 机器;
3. **结构化结果** —— `failedCases` 带 `expected`/`actual`,而非布尔;
4. **持续运行** —— `spec.interval` 定时重跑,而非一次性;
5. **人工门禁** —— `spec.approval` 卡发布,而非跑完即止;
6. **AI 关键字库** —— `Verify TTFT Below`、`Verify KV Cache Below` 等推理专用断言。

---

## 快速开始

```bash
# 1. 安装 CRD + operator
kubectl apply -f deploy/crd.yaml
kubectl apply -f deploy/rbac.yaml
kubectl apply -f deploy/deployment.yaml

# 2. 通用测试:测任意 HTTP 服务
kubectl apply -f - <<EOF
apiVersion: verification.inferguard.io/v1alpha1
kind: InferenceCheck
metadata:
  name: my-api-check
spec:
  target: http://my-service:8080
  suites: [api_smoke]
EOF

# 3. 看结果
kubectl get inferencecheck my-api-check -o yaml
```

---

## 项目结构

```
InferVerify/
├── inferverify/
│   ├── main.py        # kopf 入口
│   ├── handler.py     # 创建 Job + watch ConfigMap 回写 + interval 定时重跑 + approval 门禁
│   ├── job_runner.py  # Job 容器入口(跑 robot + 写进度/结果到 ConfigMap)
│   ├── library.py     # AI 推理关键字库(可选,通用模式不用)
│   ├── listener.py    # Robot listener(进度 + 结果收集)
│   └── result.py      # 结果聚合(Verified/Degraded + expected/actual 提取)
├── tests/
│   ├── smoke.robot     # AI 推理示例(用 AI 关键字库)
│   ├── api_smoke.robot # 通用示例(标准 RequestsLibrary)
│   └── test_*.py       # 单元测试
├── deploy/
│   ├── crd.yaml
│   ├── rbac.yaml
│   └── deployment.yaml
├── requirements.txt
└── Dockerfile
```

---

## 依赖

- Python 3.11+
- kopf(operator 框架)
- kubernetes(K8s client)
- Robot Framework 6.1+
- requests(用例里发 HTTP)
