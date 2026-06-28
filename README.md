# FastAgent

**SaaS 智能客服平台** — 面向电商场景的多租户对话 AI 系统。每个租户拥有独立的数据隔离、分类体系、属性模板和 LLM 配置。采用分层架构，将意图识别、参数抽取、业务逻辑、回复生成清晰分离，兼顾可控性与灵活性。

## SaaS 架构

FastAgent 以多租户 SaaS 模式运行：

- **租户隔离** — 每个租户独立数据库 schema（或隔离层），商品分类树、属性模板、知识库、LLM 模型参数均按租户隔离
- **管理后台** — 租户通过管理后台自行配置机器人名称、欢迎语、商品属性模板、知识库文档、意图样本
- **API 接入** — 提供标准化 REST API，支持多渠道接入（企业微信、Web、自定义渠道）
- **可观测性** — 每个租户的 LLM 调用、向量检索、技能调用均可独立追踪和审计

```
┌─────────────────────────────────────────────────┐
│                    租户 A                         │
│  分类树 → 属性模板 → 知识库 → LLM 配置 → 意图样本 │
└─────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────┐
│                    租户 B                         │
│  分类树 → 属性模板 → 知识库 → LLM 配置 → 意图样本 │
└─────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────┐
│                    租户 C                         │
│  分类树 → 属性模板 → 知识库 → LLM 配置 → 意图样本 │
└─────────────────────────────────────────────────┘
                        │
                        ▼
              FastAgent AI 引擎
        场景识别 → 参数解析 → 业务处理 → 回复生成
```

## 架构概览

```
渠道消息
  → AssistantService（主编排）
    → PendingGuard（转人工 / 取消 / 恢复）
    → RecognitionPipeline（场景识别）
    → HandlerRegistry → Handler.execute()
      → Components（参数解析与校验）
      → Skills（结构化业务操作）
      → ReplyBuilder（回复组装）
    → SessionContext 更新 + graph Pending 指令
  → AssistantRuntimeResult
```

### 核心分层

| 层 | 职责 |
|-------|----------|
| **Assistant** | 顶层编排、Pending 恢复、收口处理 |
| **Recognition** | 场景分类：规则 → 向量相似度 → LLM 兜底 |
| **Handler** | 场景流程负责人 — 编排 Component → Skill → ReplyBuilder |
| **Component** | 纯参数解析与校验，无业务副作用 |
| **Skill** | 结构化业务操作，不接收原始文本，不重新识别意图 |
| **Prompt** | 所有 Prompt 集中管理 |
| **LangGraph** | 仅用于复杂多轮子流程（下单、取消、售后） |

## 技术栈

| 类别 | 技术 |
|----------|-----------|
| 后端 | Python 3.12+, FastAPI, SQLAlchemy (async) |
| 前端 | Vue 3, TypeScript, Element Plus, Pinia |
| 数据库 | PostgreSQL (pgvector), Redis |
| 向量库 | Qdrant |
| AI/LLM | Ollama, LiteLLM, Langfuse（可观测性） |
| 流程编排 | LangGraph（复杂子流程） |
| 向量模型 | BGE/bce-embedding, BGE-reranker |
| 部署 | Docker Compose（支持 SaaS 多租户部署） |

## 功能特性

### 商品场景
- **商品浏览** — 按分类展示，不依赖 LLM
- **条件筛选** — 多属性组合筛选（分类、价格、属性），基于租户模板校验
- **商品详情** — 名称/SKU 匹配 → SQL 查询 → 知识库检索 → LLM 组织回复；多候选/序号选择只写 SessionContext
- **商品对比** — 分别解析每个商品引用，按 product_id 精准召回知识
- **属性查询** — 注入租户属性模板，确保抽取结果合法

### 订单场景
- **订单列表与筛选** — 规则解析，不走 LLM
- **订单详情与物流** — 优先级：显式订单号 → 时间/状态条件 → 上下文
- **创建订单** — LangGraph 子流程：选商品 → SKU → 地址 → 确认 → 草稿 → 确认
- **取消订单** — LangGraph 子流程，含校验和确认门

### 知识场景
- **政策问答** — QA pair 高置信直出，长内容仅用 LLM 做摘要
- **商品知识** — 绑定已确定的 product_id，精准召回
- **追问续查** — 基于 last_knowledge_refs 精准重新检索

### SaaS 平台能力
- **多租户管理** — 租户独立配置机器人名称、欢迎语、LLM 参数、知识库
- **租户商品体系** — 每个租户自定义分类树、属性模板、属性可选值，AI 抽取基于租户数据校验
- **租户知识库** — 独立知识库文档、QA pair、商品知识，按租户隔离检索
- **意图样本管理** — 租户可通过管理后台上传意图样本，提升场景识别准确率
- **管理 API** — 完整的租户配置 REST API，支持自动化入驻

### 系统能力
- **Pending 恢复** — 仅服务 LangGraph 子流程，三态守卫（HUMAN → CANCEL → RESUME）；商品多轮依赖 SessionContext
- **状态 TTL** — SessionContext 1 小时，LangGraph Pending 2 小时，避免商品候选与图恢复状态双写
- **资源追踪** — 自动记录 LLM 调用、向量检索、Skill 调用次数，支撑测试断言
- **场景权限** — ScenarioSpec 约束每个场景可调用的 Skill、上下文读写、LLM/向量使用

## 项目结构

```
backend/app/
├── ai/
│   ├── assistant/        # 主编排入口、PendingGuard
│   ├── recognition/      # 场景识别流水线
│   ├── handlers/         # 场景处理器（商品、订单、知识、转人工、模板）
│   ├── components/       # 参数解析器（分类、商品引用、筛选条件）
│   ├── skills/           # 结构化业务能力（商品、订单、知识、记忆）
│   ├── reply_builders/   # 回复组装（商品、订单、知识、模板）
│   ├── prompts/          # Prompt 集中管理
│   ├── graphs/           # LangGraph 子图（下单、取消、售后）
│   ├── context/          # SessionContext、LangGraph Pending 状态
│   ├── services/         # RAG 服务、属性抽取服务
│   ├── scenario/         # 场景定义与权限配置
│   ├── rag/              # 向量检索
│   └── llm/              # LLM 网关与客户端抽象
├── api/                  # REST API 接口
├── models/               # SQLAlchemy ORM 模型
├── schemas/              # Pydantic 数据模式
└── services/             # 领域服务（租户、管理后台等）

frontend/src/
├── views/                # AI 配置、租户设置等页面
├── api/                  # API 客户端模块
└── components/           # 公共组件
```

## 快速开始

### 环境要求

- Docker & Docker Compose
- Python 3.12+（本地开发）
- Node.js 20+（前端开发）

### 启动

```bash
# 克隆项目
git clone <repo-url> && cd fastagent

# 复制环境配置
cp .env.example .env

# 启动所有服务
docker compose up -d

# 后端: http://localhost:8000
# 前端: http://localhost:5173（vite 开发服务器）
```

### 本地开发

```bash
# 后端
cd backend
uv venv
source .venv/bin/activate
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload

# 前端
cd frontend
npm install
npm run dev
```

## 测试

基于 Harness 的集成测试，使用真实数据库和向量库：

```bash
cd backend
uv run pytest tests/
```

测试通过断言 `ResourceTrace` 来验证每个场景的 LLM 调用次数、向量检索次数、Skill 调用是否符合场景权限配置。
