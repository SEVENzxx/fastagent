# Harness 回归测试

> 更新日期：2026-07-02

Harness 是 FastAgent 的 HTTP 黑盒回归验证工具，用于验证客户消息进入系统后，AI 客服链路是否返回符合预期的回复，并检查部分资源调用约束。它不是某个 AI 编程工具的专用能力；开发者、CI、脚本、代码助手都可以调用它。

## 定位

Harness 解决的问题是：当修改 Agent 编排、商品、订单、RAG、上下文或渠道链路后，快速确认核心对话行为没有退化。

它适合用于：

- 本地开发后的快速回归
- 提交前的 smoke / P0 验证
- CI 中的自动化测试
- 代码助手修改项目后的自检
- 线上问题修复后的回归确认

它不适合替代：

- 单元测试：函数级、类级逻辑仍应使用 pytest 覆盖
- 端到端 UI 测试：Harness 不验证前端页面
- 人工验收：复杂业务话术仍需要人工抽查
- 模型质量评测：Harness 更偏工程回归，不是完整 LLM 评测平台

## 运行模式

| 模式 | 参数 | 说明 |
|------|------|------|
| 框架自验 | `--backend none` | 不访问真实后端，使用 mock 响应验证 Harness 框架、YAML、断言和报告生成是否正常 |
| 真实链路 | `--backend simulate` | 通过 Internal Harness API 调用本地或测试环境后端，验证真实 AI 链路 |

`backend=none` 适合快速检查用例文件和断言格式；`backend=simulate` 才能验证真实业务行为。

## 快速运行

### 框架自验

```bash
cd backend
uv run python scripts/run_harness.py --case tests/harness/cases/smoke.yaml --backend none
```

### 真实链路

先启动后端服务，并确认当前环境注册了 Internal Harness API。

```bash
cd backend
uv run python scripts/run_harness.py \
  --case tests/harness/cases/smoke.yaml \
  --backend simulate \
  --harness-token <token> \
  --tenant-id <tenant_id> \
  --platform-guid <platform_guid> \
  --base-url http://localhost:8000
```

### PowerShell 快捷脚本

这些脚本运行 `simulate` 模式，要求后端服务已启动，并配置好 Harness token、租户和渠道参数。

```powershell
.\scripts\run_harness_smoke.ps1    # smoke.yaml 全部用例
.\scripts\run_harness_p0.ps1       # 全部 yaml 的 P0 用例
.\scripts\run_harness_p1.ps1       # 全部 yaml 的 P1 用例
.\scripts\run_harness_p2.ps1       # 全部 yaml 的 P2 用例
.\scripts\run_harness_all.ps1      # 全部 yaml 的全部用例
```

## 配置

命令行参数优先，其次读取环境变量。

| 环境变量 | 说明 | 默认值 |
|----------|------|--------|
| `HARNESS_BASE_URL` | 后端服务地址 | `http://localhost:8000` |
| `HARNESS_BACKEND` | 运行模式：`none` 或 `simulate` | `none` |
| `HARNESS_API_TOKEN` | Internal Harness API token | 空 |
| `HARNESS_TENANT_ID` | 测试租户 ID | `0` |
| `HARNESS_PLATFORM_GUID` | 测试渠道 ID | `1` |
| `HARNESS_TIMEOUT` | HTTP 请求超时时间，单位秒 | `30` |
| `HARNESS_TAG` | 只运行指定标签的用例 | 空 |
| `HARNESS_OUTPUT` | JSON 报告输出路径 | 自动生成 |

`simulate` 模式必须提供有效的 `HARNESS_API_TOKEN`、`HARNESS_TENANT_ID` 和 `HARNESS_PLATFORM_GUID`。

## 用例组织

用例文件位于 `backend/tests/harness/cases/`。

| 文件 | 覆盖范围 | 当前用例数 |
|------|----------|------------|
| `smoke.yaml` | 问候、商品咨询、订单咨询、转人工、兜底 | 5 |
| `product.yaml` | 商品列表、筛选、价格、详情、对比、预算、特征词、异常商品、语义推荐 | 11 |
| `order.yaml` | 订单查询、单号查询、退款、缺号追问、发货状态、取消、确认、下单图流程 | 9 |
| `rag.yaml` | 售后、退货、保修、发票、政策不编造 | 5 |
| `context.yaml` | 商品多轮追问、订单缺槽补充、多轮连贯性 | 3 |
| `memory.yaml` | 偏好保存、偏好查询、保存后查询 | 3 |

当前总计 36 条用例。新增或删除 case 后，以 YAML 文件为准，并同步更新本文档。

## 标签体系

| 标签 | 含义 | 当前用例数 |
|------|------|------------|
| `p0` | 关键路径，提交前优先验证 | 7 |
| `p1` | 主要功能，高优先级回归 | 20 |
| `p2` | 边缘或扩展场景 | 9 |
| `smoke` | 冒烟用例 | 5 |
| `product` | 商品域 | 14 |
| `order` | 订单域 | 11 |
| `rag` | 知识库/RAG | 5 |
| `memory` | 记忆能力 | 3 |
| `context` | 多轮上下文 | 4 |
| `regression` | 历史问题回归 | 8 |
| `human` | 转人工 | 1 |
| `fallback` | 兜底 | 1 |
| `intent` | 意图边界 | 1 |
| `graph` | LangGraph 多轮流程 | 1 |

## YAML 用例结构

一个用例通常包含名称、标签、输入消息和断言：

```yaml
cases:
  - name: "商品-全品类查询"
    description: "用户查询全部商品"
    tags: ["product", "p0", "smoke"]
    turns:
      - input: "你们有什么商品"
        expected:
          status_code: 200
          reply_not_empty: true
          reply_contains_any: ["商品", "产品"]
          max_latency_ms: 5000
```

多轮用例可以在 `turns` 中定义多条输入，Harness 会按顺序发送。

## 支持的断言

| 断言 | 说明 |
|------|------|
| `status_code` | HTTP 状态码匹配 |
| `reply_not_empty` | 回复不能为空 |
| `reply_contains` | 回复必须包含指定文本列表中的全部内容 |
| `reply_not_contains` | 回复不能包含指定文本 |
| `reply_contains_any` | 回复至少包含列表中的一个文本 |
| `reply_regex` | 回复匹配指定正则 |
| `reply_not_regex` | 回复不能匹配指定正则 |
| `max_latency_ms` | 单轮响应耗时不能超过上限 |
| `max_llm_calls` | `ResourceTrace.llm_calls` 不超过上限 |
| `max_vector_calls` | `ResourceTrace.vector_calls` 不超过上限 |
| `allowed_skill_calls` | 只能调用指定 Skill |
| `disallowed_skill_calls` | 不能调用指定 Skill |

`ResourceTrace` 相关断言依赖真实链路返回资源调用轨迹；`backend=none` 模式下只能验证框架行为。

## 报告输出

默认 JSON 报告写入：

```text
backend/reports/harness/harness_report_<timestamp>.json
```

报告包含：

- 运行汇总：总数、通过数、失败数、耗时
- 每个 case 的标签、轮次结果、最终回复
- 每条断言的 expected、actual、passed、message
- 运行环境和目标服务地址

## 代码变更后的验证建议

| 修改范围 | 建议验证 |
|----------|----------|
| `backend/app/ai/` 主链路、Handler、Recognition、Graph | 先跑 `--backend none` smoke，再跑 `run_harness_p0.ps1` |
| 商品相关服务或 Skill | `product.yaml`，必要时跑 P0/P1 |
| 订单相关服务或 Graph | `order.yaml`，必要时跑 P0/P1 |
| RAG、知识库、向量检索 | `rag.yaml` |
| Memory 或 SessionContext | `memory.yaml`、`context.yaml` |
| Webhook、渠道、消息入口 | `run_harness_smoke.ps1` 或 `run_harness_all.ps1` |
| Harness 框架本身 | 对应 pytest 单元测试 + `--backend none` |

如果本地没有启动后端，至少运行 `--backend none` 验证 Harness 框架和 YAML 用例没有损坏。

## 失败排查

| 类型 | 常见表现 | 处理建议 |
|------|----------|----------|
| 配置错误 | 缺少 token、tenant_id、platform_guid，或 base_url 不通 | 检查环境变量和命令行参数 |
| 后端错误 | 500、404、403 | 查看后端日志和 Internal Harness API 是否注册 |
| 测试数据缺失 | 商品、订单、知识库为空或租户不匹配 | 补充测试数据或调整用例租户 |
| 断言过严 | 文案微调导致 `reply_contains` 失败 | 改用 `reply_contains_any` 或正则 |
| 业务退化 | 回复意图、流程、上下文明显不符合预期 | 回到对应 Handler、Skill、Graph 排查 |
| 性能问题 | `max_latency_ms` 持续失败 | 检查 LLM、Qdrant、数据库和网络耗时 |
| Harness bug | `backend=none` 也失败，或断言实现异常 | 修复 Harness 框架并补单元测试 |

## 和 AI 工具的关系

Harness **不是专门拿给 AI 使用的**。它是项目自己的回归测试工具。

AI 编程助手可以运行 Harness，和开发者、CI 运行它没有本质区别。文档中不需要写死任何具体工具名；推荐使用“代码助手”“自动化工具”“CI”这类中性说法。

判断是否需要跑 Harness 的标准不是“谁改的代码”，而是“改动是否可能影响对话链路”。只要改动涉及 Agent 编排、场景识别、商品、订单、RAG、上下文、渠道入口或 Harness 框架本身，就应该运行对应用例。

