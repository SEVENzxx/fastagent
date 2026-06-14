# FastWorkflow Harness — HTTP 黑盒回归验证工具

## 概述

Harness 是一个面向 FastAgent 客服系统的 HTTP 黑盒回归验证工具，通过 Internal Harness API 发送客户消息并断言 AI 回复的准确性，覆盖商品、订单、RAG、多轮上下文等核心业务链路的自动化回归。

## 架构

```
scripts/run_harness.py          CLI 入口
tests/harness/                  测试框架核心
├── adapters/
│   └── http_adapter.py          HTTP 适配器（none / simulate）
├── assertions/
│   └── basic_assertions.py      断言检查器
├── cases/                       用例定义（YAML）
│   ├── smoke.yaml               冒烟用例（P0/P1）
│   ├── product.yaml             商品咨询用例
│   ├── order.yaml               订单咨询用例
│   ├── rag.yaml                 知识库/RAG 用例
│   └── context.yaml             多轮上下文用例
├── reporters/
│   ├── console_reporter.py      控制台报告
│   └── json_reporter.py         JSON 报告
├── config.py                    运行时配置
├── case_loader.py               YAML 加载器
├── runner.py                    执行编排器
└── schemas.py                   数据类型定义
reports/harness/                 报告输出目录
scripts/run_harness_*.ps1        运行快捷脚本
```

## 快速开始

```bash
# 框架验证模式（不连接后端服务，测试框架本身）
uv run python scripts/run_harness.py --case tests/harness/cases/smoke.yaml --backend none

# 全部用例指定标签运行
.\scripts\run_harness_p0.ps1     # 仅 P0 用例（依次跑全部 yaml）
.\scripts\run_harness_all.ps1    # 全部用例
```

## 后端模式

| 模式 | 命令 | 说明 |
|------|------|------|
| `none` | `--backend none` | 框架自验模式，mock 响应，无需外部服务 |
| `simulate` | `--backend simulate` | 通过 Internal Harness API 调用真实 AI 链路 |

`simulate` 模式需要：
- 目标服务运行在 `APP_ENV=development` 或 `APP_ENV=test`
- 目标服务已设置 `HARNESS_API_TOKEN`
- 提供 `--harness-token`、`--tenant-id`、`--platform-guid`、`--base-url`

## YAML 用例格式

```yaml
env:
  local:
    base_url: "http://localhost:8000"

tenant_id: 319767484162940928
conversation_prefix: "harness"

cases:
  - name: "用例名称"                    # 必填，用例标识
    description: "用例描述"              # 可选，说明测试目的
    risk_level: "p0"                    # 可选，风险等级 p0/p1/p2
    business_constraints:               # 可选，业务约束列表
      - "约束条件 1"
      - "约束条件 2"
    tags: ["smoke", "p0"]               # 必填，标签（用于 tag 过滤）
    messages:                           # 必填，消息列表
      - description: "消息说明"          # 可选，本条消息的说明
        content: "你好"                 # 必填，消息文本
        expected:                       # 可选，消息级断言
          status_code: 200
          reply_not_empty: true
    expected:                           # 可选，用例级断言（作用于最后一轮）
      status_code: 200
      reply_not_empty: true
      max_latency_ms: 10000
```

消息格式支持两种写法：
- **字符串简写**：`- "你好"` — 无期望断言的消息
- **对象完整写法**：`- content: "你好"; expected: {...}` — 带期望断言的消息

## 断言类型

| 断言名 | YAML 字段 | 类型 | 说明 |
|--------|-----------|------|------|
| 状态码 | `status_code` | `int` | 期望 HTTP 状态码 |
| 回复非空 | `reply_not_empty` | `bool` | 回复内容非空 |
| 包含关键词 | `reply_contains` | `[str]` | 回复必须包含所有指定关键词 |
| 不包含关键词 | `reply_not_contains` | `[str]` | 回复不得包含指定关键词 |
| 包含任一关键词 | `reply_contains_any` | `[str]` | 回复至少包含列表中的一个关键词 |
| 正则匹配 | `reply_regex` | `str` | 回复必须匹配正则表达式 |
| 正则不匹配 | `reply_not_regex` | `str` | 回复不得匹配正则表达式 |
| 最大延迟 | `max_latency_ms` | `int` | 响应时间上限（毫秒） |

## 快捷脚本

| 脚本 | 功能 |
|------|------|
| `run_harness_smoke.ps1` | 跑 smoke.yaml 全部用例 |
| `run_harness_p0.ps1` | 跑全部 yaml 的 P0 用例 |
| `run_harness_p1.ps1` | 跑全部 yaml 的 P1 用例 |
| `run_harness_p2.ps1` | 跑全部 yaml 的 P2 用例 |
| `run_harness_all.ps1` | 跑全部 yaml 的全部用例 |

项目参数优先从环境变量读取，支持以下变量（括号内为默认值）：

- `HARNESS_BASE_URL`（`http://localhost:8000`）
- `HARNESS_API_TOKEN`（`dev-harness-token`）
- `HARNESS_TENANT_ID`（`319767484162940928`）
- `HARNESS_PLATFORM_GUID`（`316547449139269632`）

## 运行单元测试

```bash
uv run pytest tests/test_harness.py -v
```

## 标签分类

| 标签 | 含义 | 典型用例 |
|------|------|----------|
| `smoke` | 冒烟测试 | 问候、通用查询 |
| `p0` | 关键路径 | 全品类查询、查订单、基础问候 |
| `p1` | 主要功能 | 按品类筛选、查价格、RAG 查询 |
| `p2` | 边缘/异常 | 商品对比、退款、上下文追踪 |
| `product` | 商品域 | 所有商品相关用例 |
| `order` | 订单域 | 所有订单相关用例 |
| `rag` | 知识库域 | 所有 RAG 相关用例 |
| `context` | 多轮域 | 所有多轮上下文用例 |
| `human` | 转人工 | 转人工流程 |
| `fallback` | 兜底 | 未知输入处理 |

## 使用时机

| 阶段 | 建议命令 | 说明 |
|------|---------|------|
| 开发前 | 先确认 `--backend none` 全部通过 | 确保基线干净 |
| 改代码后 | `uv run python scripts/run_harness.py --case tests/harness/cases/<模块>.yaml --backend none` | 改哪个模块就跑对应模块的 case，快速反馈 |
| 提交前 | `.\scripts\run_harness_smoke.ps1` 或 `.\scripts\run_harness_p0.ps1` | Smoke / P0 必须全部通过 |
| 大改后 | `.\scripts\run_harness_p1.ps1` | 主要功能回归 |
| 发布前 | `.\scripts\run_harness_all.ps1` 并检查 JSON 报告 | 全部 case + latency 基线 |

## 失败分类

| 分类 | 典型表现 | 处理方式 |
|------|---------|---------|
| 测试数据问题 | 租户缺少对应商品或知识库内容，导致搜索无结果 | 补充测试数据或调整 case 预期 |
| 断言过严 | `reply_contains` 关键词与 AI 回复不完全匹配；`max_latency_ms` 持续超上限 | 改用 `reply_contains_any`、调整关键词、放宽时间阈值 |
| Workflow 退化 | 同一输入返回的回复不符合业务预期（引入回归） | 回滚或修复 Workflow 逻辑 |
| 接口问题 | 返回 500/404/403 | 检查后端日志和服务状态 |
| 认证问题 | 401 Unauthorized，`X-Harness-Token` 不匹配 | 检查 `HARNESS_API_TOKEN` 环境变量是否一致 |
| 超时问题 | 整体执行 hang 或 `max_latency_ms` 持续超时 | 检查 LLM 响应速度、Qdrant 延迟 |

排查步骤：
1. 确认环境状态：后端是否运行、`APP_ENV` 是否正确
2. 匹配分类：从以上找到最符合的表现
3. 修复或放宽后重新运行对应 case

## Case 编写规范

### 命名

格式：`<领域>-<场景>[-<子场景>]`，全局唯一，报告中易于定位。  
示例：`商品-预算过滤`、`订单-缺号必须追问`、`RAG-政策不编造`。

### 字段要求

| 字段 | 要求 |
|------|------|
| `name` | `领域-场景` 格式，全局唯一 |
| `description` | 一句话说明测试目标 |
| `risk_level` | p0/p1/p2，p0 只用于核心链路 |
| `business_constraints` | 中文描述业务规则，第一版只用于报告展示 |
| `tags` | 至少包含领域标签 + 风险标签 |
| `messages` | 至少 1 条；多轮需用 `description` 说明每轮意图 |
| `expected` | 至少 `reply_not_empty: true` |

### 断言策略

- **P0** — 宽松断言（`reply_not_empty` + `max_latency_ms`），确保核心链路稳定
- **P1** — 增加 `reply_contains` / `reply_contains_any` / `reply_not_contains`，验证特定关键词
- **P2** — 可增加 `reply_regex` / `reply_not_regex`，验证复杂行为约束
- 避免使用过于具体的品牌、型号、SKU 作为断言关键词（SaaS 多租户数据差异大）

### 标签策略

- 每个 case 至少有一个领域标签（product/order/rag/context）和一个风险标签（p0/p1/p2）
- `smoke` 标签仅用于核心链路

## 标准 Case 模板

```yaml
# 单轮消息模板
- name: "领域-场景"
  description: "一句话说明测试场景和目的"
  risk_level: "p0"
  business_constraints:
    - "业务约束 1"
    - "业务约束 2"
  tags: ["领域标签", "p0"]
  messages:
    - content: "客户消息"
  expected:
    status_code: 200
    reply_not_empty: true
    reply_contains: ["关键词1", "关键词2"]  # P1/P2 可选
    reply_not_contains: ["不应出现的词"]    # P1/P2 可选
    max_latency_ms: 10000

# 多轮消息模板
- name: "领域-场景-多轮"
  description: "多轮交互场景说明"
  risk_level: "p1"
  business_constraints:
    - "业务约束"
  tags: ["context", "p1"]
  messages:
    - description: "第一轮：用户做什么"
      content: "第一轮消息"
    - description: "第二轮：用户做什么"
      content: "第二轮消息"
  expected:
    status_code: 200
    reply_not_empty: true
    max_latency_ms: 20000
```

## 测试数据要求

### 基础要求

- 租户需有完整的商品分类、商品资料、知识库文档和 QA pair
- 商品应覆盖多个品类（至少 3 个），便于筛选测试
- 知识库应覆盖售后、退货、保修、发票等场景

### 历史 Bug 回归需要的特定数据

部分 case 需要特定测试数据才能完整验证：

| Case | 所需数据 | 当前状态 |
|------|---------|---------|
| 商品-预算过滤 | 同一品类下有不同价格梯度的商品 | 需确认 |
| 商品-attrs_json三态处理 | 商品中 attrs_json 存在 null / "null" / "{}" 三种情况 | 需数据准备 |
| RAG-政策不编造 | 知识库中有明确售后政策和退款条款 | 需确认 |

### 数据准备建议

1. 上传 15-20 个商品，覆盖 4-5 个品类
2. 上传 10+ 知识库文档覆盖客服高频场景
3. 上传 20+ QA pair
4. 确保有价格差异（¥50-¥2000）以便测试预算过滤
5. 确保有包含特征词（防水、便宜、便携等）的商品描述

## 报告解读方式

### 控制台报告

每轮执行后输出：

```
[Harness] [通过] 问候-基础
[Harness] [失败] 商品咨询-通用 → reply_contains: "商品" 未命中
```

- `[通过]` — 该 case 全部断言通过
- `[失败]` — 至少一个断言未通过，`→` 后为失败的断言名和原因

### JSON 报告（详细）

JSON 报告输出到 `reports/harness/harness_report_<timestamp>.json`。

| JSON 路径 | 说明 |
|-----------|------|
| `summary.total` | 总 case 数 |
| `summary.passed` | 通过数 |
| `summary.failed` | 失败数 |
| `summary.duration` | 总耗时（秒） |
| `cases[].name` | case 名称 |
| `cases[].passed` | 是否全部通过 |
| `cases[].turns[].status_code` | 实际 HTTP 状态码 |
| `cases[].turns[].latency_ms` | 实际响应时间（毫秒） |
| `cases[].turns[].reply` | 实际回复内容 |
| `cases[].assertion_results[].name` | 断言名称 |
| `cases[].assertion_results[].passed` | 是否通过 |
| `cases[].assertion_results[].expected` | 期望值 |
| `cases[].assertion_results[].actual` | 实际值 |

### 解读步骤

1. 先看 `summary.failed` 是否为 0
2. 有失败则按失败分类归类
3. 对每个失败 case 查看 `assertion_results` 定位具体断言
4. `reply_contains` / `reply_regex` 失败时，查看 `turns[].reply` 确认 AI 实际回复
5. `max_latency_ms` 持续失败时，检查后端 LLM / 检索性能

## Claude Code 使用规则

### 修改代码后自动跑 Harness

| 修改范围 | 建议命令 |
|----------|---------|
| AI Workflow 逻辑（`app/ai/`） | `.\scripts\run_harness_p0.ps1` 或 `uv run python scripts/run_harness.py --case tests/harness/cases/smoke.yaml --backend none` |
| 订单/商品服务（`app/services/`） | `.\scripts\run_harness_p0.ps1` |
| RAG/知识库服务 | `uv run python scripts/run_harness.py --case tests/harness/cases/rag.yaml --backend none` |
| Webhook/渠道层 | `.\scripts\run_harness_smoke.ps1` |
| Harness 框架本身 | `uv run pytest tests/test_harness.py -v` |

### 新增 Case 后

1. 先跑 `--backend none` 验证 YAML 语法和框架逻辑
2. 再跑 `--backend simulate` 验证真实 AI 回复
3. 确认新 case 不影响已有 P0 case 通过率
4. 更新 `docs/evaluation/harness.md` 中的用例数量

### 添加新断言类型

需同步更新：
- `assertions/basic_assertions.py` — 断言检查逻辑
- `schemas.py` — 数据类型定义
- `README.md` — 断言类型表格
- `tests/test_harness.py` — 对应单元测试
- `docs/evaluation/harness.md` — 文档同步

## 当前限制与后续计划

### 当前限制

| 限制 | 说明 | 后续方向 |
|------|------|---------|
| `simulate` 依赖外部后端 | 需要目标服务运行并配置 Harness token | 容器化全栈测试 |
| 无 LLM-as-judge | 复杂语义断言无法自动判断 | 当前依赖关键词断言 + 人工复核 |
| 无基线 diff | 不支持对比两次报告的差异 | Git CI 集成 |
| 无 CI 自动触发 | 当前全手动执行 | GitHub Actions 门禁 |
| 无 YAML schema 校验 | 缺少严格格式校验 | 集成 JSON Schema / Pydantic |

### 后续计划

1. **CI 集成**：在 GitHub Actions 中自动运行 P0 case 作为 PR 门禁
2. **基线管理**：支持 `--baseline` 模式对比两次执行结果
3. **测试数据工厂**：提供独立的数据准备脚本，解决黑盒数据依赖
4. **YAML schema 校验**：对 case 文件进行严格格式校验
5. **性能基线**：`max_latency_ms` 自动基线学习和报警
