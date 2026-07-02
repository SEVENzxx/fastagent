# FastAgent

<p align="center">
  <strong>面向电商私域场景的多租户 AI 客服与销售助手平台</strong>
</p>

<p align="center">
  <img alt="Python" src="https://img.shields.io/badge/Python-3.12+-3776AB?logo=python&logoColor=white">
  <img alt="FastAPI" src="https://img.shields.io/badge/FastAPI-0.115+-009688?logo=fastapi&logoColor=white">
  <img alt="Vue" src="https://img.shields.io/badge/Vue-3-42b883?logo=vue.js&logoColor=white">
  <img alt="TypeScript" src="https://img.shields.io/badge/TypeScript-6-3178c6?logo=typescript&logoColor=white">
  <img alt="PostgreSQL" src="https://img.shields.io/badge/PostgreSQL-pgvector-4169e1?logo=postgresql&logoColor=white">
  <img alt="Qdrant" src="https://img.shields.io/badge/Qdrant-Vector_Search-dc244c">
</p>

FastAgent 不是一个只会闲聊的 ChatBot，而是围绕电商客服、销售跟进和店铺运营构建的业务型 AI 系统。它把商品、订单、知识库、客户资料、人工接管、租户后台和 AI 可观测性放在同一套产品链路里，让 AI 回复可以被业务数据约束、被权限边界限制、被测试用例回归验证。

当前项目适合用来研究和二次开发：

- 电商客服 Agent 的工程化落地方式
- RAG 知识库、标准问答和商品知识在客服场景里的组合使用
- 多租户 SaaS 后台与 AI 能力配置
- 场景识别、结构化 Skill、LangGraph 多轮流程的边界设计
- AI 链路 trace、资源调用统计和 Harness 回归测试

## 项目亮点

| 能力 | 说明 |
|------|------|
| 多租户 SaaS | 租户、员工、角色、权限、套餐、LLM 配置、业务数据按租户维度管理 |
| 电商业务场景 | 覆盖商品咨询、商品筛选、商品对比、订单查询、订单创建、订单取消、退款/售后等客服高频问题 |
| 可控 AI 链路 | 场景识别、参数解析、业务操作、回复生成分层处理，避免把所有逻辑塞进一个 Prompt |
| RAG 知识库 | 支持知识文档、QA 标准问答、商品知识、营销资料、图片素材等检索场景 |
| 多轮状态管理 | SessionContext 维护普通对话上下文，LangGraph Pending 承接下单、取消、售后等复杂流程 |
| 人工接管 | 支持转人工、取消、恢复等状态守卫，避免 AI 和人工流程互相覆盖 |
| 可观测性 | trace_id 贯穿 API、AI、图流程、WebSocket，支持 LangFuse 链路追踪和资源调用统计 |
| 回归测试 | 内置 Harness 测试框架，用例覆盖商品、订单、知识、记忆、上下文等场景 |

## 当前功能

### 后台与 SaaS

- 登录认证、JWT 会话、员工管理
- 角色、权限、菜单访问控制
- 租户管理、套餐管理、平台 Admin 看板
- LLM 配置、用量统计、调用日志
- 登录历史、审计日志、系统通知、敏感词配置

### 客服工作台

- 会话列表、消息窗口、WebSocket 在线状态
- 联系人管理、客户详情、客户资料导入
- 人工接管与 AI 回复链路衔接
- 企业微信 Webhook 接入与 Web 测试工具

### 商品与订单

- 商品、分类、属性模板管理
- 商品导入、商品知识维护、商品卡片展示
- 订单列表、订单详情、订单状态管理
- AI 商品推荐、条件筛选、详情咨询、商品对比
- AI 订单查询、下单、取消、退款/售后流程

### 知识与内容

- 知识文档上传、解析、分块和向量化
- QA 标准问答管理
- RAG 命中测试
- 营销资料管理
- 图片素材库

### AI 工程能力

- 规则、向量、LLM 组合的场景识别链路
- Handler / Component / Skill / ReplyBuilder 分层
- ScenarioSpec 场景权限约束
- LangGraph 子图处理复杂多轮流程
- SessionContext 与 Pending 状态隔离
- trace_id、ResourceTrace、LangFuse 可观测性
- Harness 回归测试与场景断言

## 架构概览

```text
客户消息 / 企业微信 / Web 测试工具
        |
        v
FastAPI API / WebSocket / Webhook
        |
        v
AssistantService
        |
        +--> PendingGuard
        +--> RecognitionPipeline
        +--> HandlerRegistry
        |       |
        |       +--> Components
        |       +--> Skills
        |       +--> ReplyBuilders
        |
        +--> SessionContext / LangGraph Pending
        |
        v
业务数据、知识库、向量库、LLM、可观测系统
```

更完整的架构说明见 [docs/architecture.md](docs/architecture.md)。

## 技术栈

| 模块 | 技术 |
|------|------|
| 后端 | Python 3.12, FastAPI, SQLAlchemy Async, Alembic |
| 前端 | Vue 3, TypeScript, Vite, Element Plus, Pinia |
| 数据库 | PostgreSQL, pgvector |
| 缓存与状态 | Redis |
| 向量检索 | Qdrant |
| AI 编排 | LangGraph, LiteLLM / OpenAI-compatible HTTP, Ollama |
| 可观测性 | trace_id, ResourceTrace, LangFuse |
| 测试 | pytest, Harness scenario runner |
| 部署 | Docker Compose |

## 快速开始

### 环境要求

- Docker 与 Docker Compose
- Python 3.12+
- Node.js 20+
- pnpm
- uv

### 1. 准备环境变量

```bash
cp .env.example .env
```

`.env.example` 默认使用本地模型服务：

- LLM: `http://localhost:11434`
- Embedding: `http://localhost:8001`
- Reranker: `http://localhost:8002/rerank`
- Qdrant: `http://localhost:6333`

如果只是先跑通后台和基础 API，可以根据本地环境临时关闭或替换 AI 相关配置。

### 2. 启动后端依赖与 API

```bash
docker compose up -d
```

默认服务：

- Backend API: `http://localhost:8000`
- API Docs: `http://localhost:8000/docs`
- PostgreSQL: `localhost:5432`
- Redis: `localhost:6379`
- Qdrant: `http://localhost:6333`

### 3. 启动前端

```bash
cd frontend
pnpm install
pnpm run dev
```

前端默认访问：`http://localhost:5173`

### 4. 本地后端开发

```bash
cd backend
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
```

## 测试

后端单元测试与场景测试：

```bash
cd backend
uv run pytest
```

Harness 场景回归脚本：

```bash
cd backend
uv run python scripts/run_harness.py --help
```

更多说明见 [docs/evaluation/harness.md](docs/evaluation/harness.md)。

## 文档

| 文档 | 内容 |
|------|------|
| [docs/requirements/product-requirements.md](docs/requirements/product-requirements.md) | 当前版产品需求、已实现范围和后续规划 |
| [docs/requirements/scenarios.md](docs/requirements/scenarios.md) | AI 场景、识别规则、Handler 边界和风险权限 |
| [docs/architecture.md](docs/architecture.md) | 系统架构、后端分层、前端结构、数据与可观测性 |
| [docs/development/standards.md](docs/development/standards.md) | 开发规则、行为约束和模块边界 |
| [docs/development/observability.md](docs/development/observability.md) | trace_id、LangFuse 和链路追踪说明 |
| [docs/evaluation/harness.md](docs/evaluation/harness.md) | Harness 回归测试说明 |

## 项目状态

FastAgent 目前处于可运行的工程化开发阶段，核心后台、AI 主链路、商品/订单/知识库场景、可观测性和 Harness 已具备基础能力。部分能力仍在持续完善，包括退款写操作闭环、敏感词在发送链路中的深度接入、企业微信幂等与告警、自动跟进安全策略、账单配额和更完整的生产部署方案。

详细需求边界见 [docs/requirements/product-requirements.md](docs/requirements/product-requirements.md)。

## 适合谁

- 正在做电商客服、私域销售、企业微信客服自动化的开发者
- 想研究业务型 AI Agent 如何落地到真实后台系统的人
- 想了解 RAG、LangGraph、多租户 SaaS、AI 可观测性如何组合的人
- 需要一个可二次开发的 AI 客服后台项目的人

## License

本项目采用 [LICENSE](LICENSE) 中声明的许可证。
