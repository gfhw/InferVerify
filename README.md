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
InferenceCheck CR ──► kopf on.create
                        ├─ 创建 Kubernetes Job(robot 镜像跑 inferverify.job_runner)
                        ├─ 阈值/target 通过环境变量注入(声明式,不改用例)
                        └─ status.phase = Pending

kopf timer(每 10s)──► watch Job
                        ├─ Job 完成 → 读 Pod stdout 里的结果 JSON
                        └─ 回写 status: Verified / Degraded / Unknown
```

**执行模型**:robot 用例跑在**独立的 Job Pod**里(与 operator 进程隔离)。Job 容器执行 `inferverify.job_runner`,把结果以单行 JSON(`INFERVERIFY_RESULT:...`)打到 stdout;operator 通过 timer 轮询 Job 状态,完成后读日志回写 CR。

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

[kubetest](https://kubetest.readthedocs.io/) 是通用 K8s 测试框架(pytest),它的结果就是 pytest 的 pass/fail、跑在 CI/本地、不回写任何资源。InferVerify 定制的点(均已实现):

1. **声明式阈值** —— 阈值在 CR 里(`spec.thresholds`),作为变量注入用例,改 CR 不改用例;
2. **结构化结果** —— `failedCases` 带 `expected`/`actual`(从关键字失败信息解析),而非布尔;
3. **版本化验证** —— `releaseRef` + `revision` 关联部署版本,升级回归对比;
4. **实时进度** —— Job 容器通过 listener 把关键字级事件打到 stdout,operator 轮询回写 `status.progress`;
5. **AI 关键字库** —— `Verify TTFT Below`、`Verify KV Cache Below`、`Inference Service Ready` 等推理专用关键字,写一个 CR 就能用。

> 待做(进阶):流程级暂停/人工介入——验证分阶段,阶段间暂停等批准。

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
├── inferverify/
│   ├── main.py        # kopf 入口
│   ├── handler.py     # 创建 Job + timer 轮询回写状态
│   ├── job_runner.py  # Job 容器入口(跑 robot + 输出结果 JSON)
│   ├── listener.py    # Robot listener(进度 + 结果收集)
│   └── result.py      # 结果聚合(Verified/Degraded)
├── tests/
│   ├── smoke.robot    # 示例用例(健康检查 + 模型加载)
│   └── test_*.py      # 单元测试
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
