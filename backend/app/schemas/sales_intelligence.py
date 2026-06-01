"""销售智能 Schema —— 客户 360 视图、待办、跟单计划的数据模型。

本模块定义销售智能模块的请求/响应格式：
- TodoCreate/Update/Response：会话待办（AI 与人工共享的任务列表）
- FollowupPlanCreate/Response：智能跟单计划（定时任务扫描并执行）
- SalesContextResponse：客户销售阶段快照（新客户→询价→谈判→成交→售后）
- ContactProductContextResponse：客户×商品维度的销售管线（每商品独立追踪报价和阶段）
- Contact360Response：客户画像聚合视图（基本信息 + 销售上下文 + 订单 + 待办）
"""

from datetime import datetime

from pydantic import Field, field_serializer, field_validator

from app.schemas.base import CamelModel


class TodoCreate(CamelModel):
    """创建会话待办的请求体。

    待办可由 AI（created_by_type='ai'）或坐席（'agent'）创建，
    关联到具体会话。创建时会自动从会话中获取 contact_id。
    """
    conversation_id: int  # 所属会话 ID（Snowflake BigInt，JSON 序列化为字符串）
    content: str           # 待办内容，不能为空
    keywords: list[str] = Field(default_factory=list)  # 关键词标签，方便筛选和搜索
    due_at: datetime | None = None  # 截止时间（可空表示无截止）
    created_by_type: str = "agent"  # 创建者类型：ai（AI 自动创建）或 agent（坐席手动创建）

    @field_validator("content")
    @classmethod
    def content_required(cls, value: str) -> str:
        """待办内容不能为空字符串或纯空白"""
        value = value.strip()
        if not value:
            raise ValueError("待办内容不能为空")
        return value


class TodoUpdate(CamelModel):
    """更新待办的请求体，所有字段可选（PATCH 语义）。"""
    content: str | None = None    # 更新待办内容
    status: str | None = None     # 更新状态：pending（待处理）/ done（已完成）/ cancelled（已取消）
    due_at: datetime | None = None  # 更新截止时间

    @field_validator("status")
    @classmethod
    def validate_status(cls, value: str | None) -> str | None:
        """只允许三种预定义状态，避免脏数据进入数据库"""
        if value is not None and value not in {"pending", "done", "cancelled"}:
            raise ValueError("待办状态必须为 pending、done 或 cancelled")
        return value


class TodoResponse(CamelModel):
    """待办响应体，包含完整字段。"""
    id: int
    tenant_id: int
    conversation_id: int
    contact_id: int
    content: str
    keywords: list[str] = Field(default_factory=list)
    status: str           # pending / done / cancelled
    due_at: datetime | None = None
    completed_at: datetime | None = None  # 完成时间（status='done' 时自动设置）
    created_by_type: str  # ai / agent
    created_at: datetime
    updated_at: datetime

    @field_serializer("id", "tenant_id", "conversation_id", "contact_id")
    def serialize_bigint(self, value: int) -> str:
        """Snowflake BigInt 转字符串，防止 JavaScript 精度丢失"""
        return str(value)


class FollowupPlanCreate(CamelModel):
    """创建跟单计划的请求体。

    跟单计划由 AI 或坐席创建，后台定时任务（Celery Beat）扫描到期计划并执行。
    """
    contact_id: int                    # 目标客户
    conversation_id: int | None = None # 来源会话（可空）
    content: str                       # 跟进内容/话术
    scheduled_at: datetime             # 计划执行时间
    created_by_type: str = "agent"     # 创建者类型：ai / agent


class FollowupPlanResponse(CamelModel):
    """跟单计划响应体。"""
    id: int
    tenant_id: int
    contact_id: int
    conversation_id: int | None = None
    content: str
    scheduled_at: datetime            # 计划执行时间
    status: str                       # pending / executed / failed / cancelled
    created_by_type: str
    failure_reason: str | None = None # 执行失败原因（status='failed' 时填充）
    sent_at: datetime | None = None   # 实际执行时间
    created_at: datetime
    updated_at: datetime

    @field_serializer("id", "tenant_id", "contact_id", "conversation_id")
    def serialize_bigint(self, value: int | None) -> str | None:
        return str(value) if value is not None else None


class SalesContextResponse(CamelModel):
    """客户销售阶段快照响应体。

    展示客户在当前销售漏斗中的位置和报价策略级别。
    stage 流转规则：只允许向前推进（new → inquiry → negotiation → ordered → after_sales → closed）
    """
    stage: str               # 销售阶段：new / inquiry / negotiation / ordered / after_sales / closed
    pricing_level: str       # 报价策略级别：normal（原价）/ discount（折扣）/ below_floor_pending（低于底价待审批）
    followup_state: str      # 跟进状态：none / pending / scheduled / executed
    next_followup_at: datetime | None = None  # 下次跟进时间
    last_interaction_at: datetime | None = None  # 最近互动时间
    summary: str | None = None  # AI 生成的客户摘要


class SalesMemoryResponse(CamelModel):
    """客户销售记忆响应体。

    AI Agent 通过 remember_info Skill 记录的客户偏好、事实和备注。
    按 key 唯一 upsert，保证同一事实只保留最新值。
    """
    id: int
    memory_type: str  # preference（偏好）/ note（备注）/ fact（事实）
    key: str           # 记忆键（如 "favorite_flavor"、"budget_range"）
    value: str         # 记忆值
    source: str        # 来源：customer_message / agent_note / ai_deduction
    updated_at: datetime

    @field_serializer("id")
    def serialize_bigint(self, value: int) -> str:
        return str(value)


class ContactProductContextResponse(CamelModel):
    """客户×商品销售管线响应体。

    每个商品与客户的交互独立追踪，包括报价历史、销售阶段和成交订单。
    unique(tenant_id, contact_id, product_id) 确保每对关系只有一条当前状态记录。
    """
    id: int
    product_id: int
    product_name: str | None = None  # 商品名称（join 查询填充，便于前端展示）
    stage: str                # 管线阶段：inquiry / quoted / negotiating / ordered / abandoned
    quoted_price: float | None = None  # 最近报价
    price_level: int          # 报价等级：1=原价 / 2=折扣 / 3=低于底价需审批
    order_id: int | None = None  # 关联的最近订单

    @field_serializer("id", "product_id", "order_id")
    def serialize_bigint(self, value: int | None) -> str | None:
        return str(value) if value is not None else None


class Contact360Response(CamelModel):
    """客户 360 画像聚合响应体。

    聚合客户基本信息、销售阶段、AI 记忆、商品交互、历史订单、待办和跟单计划。
    工作台右侧面板和客户详情页使用此接口一次性获取完整客户视图。
    """
    contact_id: int
    name: str                          # 客户名称
    phone: str | None = None           # 电话
    address: str | None = None         # 地址
    tags: list[str] = Field(default_factory=list)         # 客户标签
    assigned_employee_name: str | None = None             # 分配的坐席姓名
    sales_context: SalesContextResponse                    # 销售阶段快照
    memories: list[SalesMemoryResponse] = Field(default_factory=list)       # AI 记忆列表
    product_contexts: list[ContactProductContextResponse] = Field(default_factory=list)  # 商品交互管线
    orders: list[dict] = Field(default_factory=list)      # 最近 5 笔订单摘要
    todos: list[TodoResponse] = Field(default_factory=list)          # 关联待办
    followups: list[FollowupPlanResponse] = Field(default_factory=list)  # 跟单计划

    @field_serializer("contact_id")
    def serialize_bigint(self, value: int) -> str:
        return str(value)
