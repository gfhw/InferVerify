# InferVerify

AI 推理部署的 **Robot Framework 验证 Operator**。它 watch `InferenceCheck` CR,用 Robot Framework 跑断言用例,把结果回写成结构化的 `Verified / Degraded` 状态。

与 [InferGuard](../InferGuard) 联动:InferGuard 负责"部署",InferVerify 负责"验证部署是否真的达标"——补上"Pod Ready ≠ 模型能推理"这个缝隙。

---

## 定位

Kubernetes 上部署 AI 推理模型,Helm 的 `--wait` 只保证 Pod Ready,探针只能判"进程活着"(布尔)。它们都回答不了:

> **这个模型现在到底能不能按 SLA 推理?这次升级有没有劣化?**

InferVerify 用 Robot Framework 的**定量断言**回答这个问题:跑用例、测出实测值、和 CR 里声明的阈值对比、输出结构化结论。

---

## 架构

```
InferenceCheck CR ──► kopf handler
                        ├─ robot.run() 跑用例(listener 收集结果)
                        ├─ 阈值通过 --variable 注入(声明式,不改用例)
                        └─ 回写 status: Verified / Degraded / Unknown
```

**执行模型**:第一版在 operator 进程内**同步**跑 Robot(验证是轻量 HTTP 探测,不需要 GPU)。`runner.run_suites` 是隔离点,后续可无缝换成 Job-based executor(起 Job 跑、收集 output.xml)。

---

## CR 示例

```yaml
apiVersion: verification.inferguard.io/v1alpha1
kind: InferenceCheck
metadata:
  name: llama-3-8b-check
  namespace: production
spec:
  releaseRef: llama-3-8b      # 指向哪个 ModelRelease(联动键)
  revision: 42                # 验证哪个 Helm revision
  engine: vllm
  target: http://llama-3-8b.production.svc:8000   # 推理服务地址
  suites: [smoke]             # 跑 tests/smoke.robot
  thresholds:                 # 声明式阈值,作为变量注入用例
    ttftP99Ms: 5000
    throughputMinTokens: 80
```

回写后的 status:

```yaml
status:
  phase: Degraded            # Verified | Degraded | Unknown | Pending
  passedCases: 1
  failedCases:
    - name: TTFT 达标
      message: "TTFT 超阈值: expected < 5000ms, actual = 8100ms"
  reportURL: /tmp/reports/.../report.html
  message: "1 case(s) failed: TTFT 达标"
```

---

## 与 InferGuard 的联动

```
InferGuard(Go)  部署成功 + verification.enabled=true
  → 创建 InferenceCheck CR(写 releaseRef / revision / target / thresholds)
  → watch InferenceCheck.status
  → 回写 ModelRelease.status.verification.phase

InferVerify(Python)  watch InferenceCheck
  → kopf handler 触发
  → robot.run() 跑用例(listener 收集进度/结果)
  → 回写 status(Verified/Degraded)
```

---

## 相对 kubetest 的定制能力

[kubetest](https://kubetest.readthedocs.io/) 是通用 K8s 测试框架(pytest),它的结果是 pass/fail。InferVerify 定制的点:

1. **声明式阈值** —— 阈值在 CR 里,改 CR 不改用例;
2. **结构化结果** —— `failedCases` 带 expected/actual,而非布尔;
3. **版本化验证** —— `releaseRef` + `revision` 关联部署版本,升级回归;
4. **实时进度** —— Robot listener(关键字级事件)驱动;
5. **AI 关键字库** —— 后续迭代:`Verify TTFT Below` 等推理专用关键字。

---

## 快速开始

```bash
# 1. 安装 CRD
kubectl apply -f deploy/crd.yaml

# 2. 部署 operator
kubectl apply -f deploy/rbac.yaml
kubectl apply -f deploy/deployment.yaml

# 3. 创建验证(假设推理服务已在 http://llama-3-8b:8000 就绪)
kubectl apply -f - <<EOF
apiVersion: verification.inferguard.io/v1alpha1
kind: InferenceCheck
metadata:
  name: llama-3-8b-check
spec:
  releaseRef: llama-3-8b
  revision: 42
  target: http://llama-3-8b:8000
  suites: [smoke]
EOF

# 4. 看结果
kubectl get inferencecheck llama-3-8b-check -o yaml
```

---

## 项目结构

```
InferVerify/
├── operator/
│   ├── main.py        # kopf 入口
│   ├── handler.py     # CR handler(状态机 + 触发验证)
│   ├── runner.py      # robot.run 封装(执行器隔离点)
│   ├── listener.py    # Robot listener(进度 + 结果收集)
│   └── result.py      # 结果聚合(Verified/Degraded)
├── tests/
│   └── smoke.robot    # 示例用例(健康检查 + 模型加载)
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
- Robot Framework 6.1+
- requests(用例里发 HTTP)
