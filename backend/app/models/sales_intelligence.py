"""销售智能模型 —— 客户 360 视图、报价审批、跟进计划和会话待办。

设计意图：
---------
这一组表承接销售阶段的"智能决策"数据。它们刻意与订单表（orders）和消息表
（messages）分开存储，原因如下：

1. **订单和消息是不可丢失的业务事实** —— 一旦产生，只追加不修改。
2. **销售上下文是持续更新的"当前状态"** —— 客户在不同销售阶段间流转，
   报价价格反复协商，跟进计划随时调整。
3. **分开存储后，调整销售阶段推进规则时不会破坏历史订单和聊天记录**。
4. **销售智能表的写入频率远高于订单表**（每次 AI 分析客户意图都可能更新上下文）。

数据流关系：
-----------
- Contact（客户）→ SalesContext（客户级销售上下文，1:1）
- Contact + Product → ContactProductContext（客户-商品销售管线，N:N 的中间状态）
- Product → SalesTemplate（商品关联销售话术模板）
- Contact + Conversation → FollowupPlan（跟进计划）
- Contact + Conversation → ConversationTodo（会话待办）
"""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.utils.id_generator import generate_id


class SalesContext(Base):
    """客户级销售上下文 —— 每个租户下每个客户仅保留一条当前快照。

    业务角色：
    ---------
    这是销售智能的核心表，充当客户的"360 度销售视图"。AI Agent 在与客户对话时，
    读取此表获取客户当前所处的销售阶段、定价级别、跟进状态等，从而做出精准的
    商品推荐和话术选择。每次客户行为（咨询、下单、议价、流失等）都可能触发
    此记录的状态更新。

    状态机说明：
    -----------
    - stage（销售阶段）：new(新客) → contacting(接触中) → negotiating(议价中)
      → closed_won(已成交) → retention(维护中) / closed_lost(已流失)
    - pricing_level（定价级别）：normal(标准价) / vip( VIP 价) / wholesale(批发价)
    - followup_state（跟进状态）：none(无) / scheduled(已计划) / executing(执行中)
      / cooling(冷却中) / unsubscribed(已退订)

    字段说明：
    ---------
    - summary: 销售摘要，由 AI Agent 自动汇总关键对话信息（客户需求、预算、痛点等）。
    - next_followup_at: 下次跟进时间，Agent 调度器据此触发自动跟进。
    - last_interaction_at: 最近一次互动时间（消息、电话、邮件等）。
    """

    __tablename__ = "sales_contexts"

    # ---- 主键 ----
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, default=generate_id, comment="主键")

    # ---- 关联 ----
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenants.id"), nullable=False, comment="所属租户")

    contact_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("contacts.id"), nullable=False, comment="关联客户（1:1）")

    # ---- 销售状态 ----
    stage: Mapped[str] = mapped_column(String(30), nullable=False, default="new", server_default="new", comment="销售阶段: new / contacting / negotiating / closed_won / retention / closed_lost")

    pricing_level: Mapped[str] = mapped_column(String(30), nullable=False, default="normal", server_default="normal", comment="定价级别: normal / vip / wholesale")

    followup_state: Mapped[str] = mapped_column(String(30), nullable=False, default="none", server_default="none", comment="跟进状态: none / scheduled / executing / cooling / unsubscribed")

    next_followup_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, comment="下次跟进时间")

    last_interaction_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, comment="最近互动时间")

    # ---- AI 摘要 ----
    summary: Mapped[str | None] = mapped_column(Text, nullable=True, comment="AI 生成的客户需求摘要")

    # ---- 时间戳 ----
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), comment="创建时间")

    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), comment="更新时间")

    # ---- 索引 ----
    __table_args__ = (
        # 唯一约束：一个租户下一个客户只能有一条销售上下文
        Index("idx_sales_ctx_contact", "tenant_id", "contact_id", unique=True),
        # 按跟进时间检索待跟进的客户列表（调度器高频扫描）
        Index("idx_sales_ctx_followup", "tenant_id", "next_followup_at"),
        {"comment": "客户级销售上下文"},
    )


class ContactProductContext(Base):
    """客户与商品之间的销售管线上下文 —— 记录最近报价和谈判阶段。

    业务角色：
    ---------
    当客户对某个商品表现出兴趣时（如询问价格、规格），系统在此表创建或更新
    一条记录。它跟踪客户对特定商品的兴趣程度和报价历史，帮助 AI Agent 判断
    是否适合推荐该商品、应该报什么价格、以及谈判到了什么阶段。

    与前表的关系：
    -------------
    - SalesContext 描述客户的整体销售状态（宏观视图）。
    - ContactProductContext 描述客户对某个具体商品的兴趣状态（微观视图）。
    - 一个客户可能对多个商品感兴趣 → 一个 contact_id 可对应多条 CPC 记录。

    字段说明：
    ---------
    - stage: 该商品的销售阶段 —— inquiry(询价) / quoted(已报价) / negotiating(议价)
      / accepted(已接受) / rejected(已拒绝)。
    - quoted_price: 最近一次报价金额，用于历史追溯和比价分析。
    - price_level: 报价级别（1-N），企业微信客户默认比零售价低一个级别。
    - order_id: 如果已成交，关联到具体订单。
    """

    __tablename__ = "contact_product_contexts"

    # ---- 主键 ----
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, default=generate_id, comment="主键")

    # ---- 关联 ----
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenants.id"), nullable=False, comment="所属租户")

    contact_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("contacts.id"), nullable=False, comment="关联客户")

    product_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("products.id"), nullable=False, comment="关联商品")

    # ---- 销售管线状态 ----
    stage: Mapped[str] = mapped_column(String(30), nullable=False, default="inquiry", server_default="inquiry", comment="销售阶段: inquiry / quoted / negotiating / accepted / rejected")

    quoted_price: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True, comment="最近报价金额")

    price_level: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1", comment="报价级别（1-N）")

    order_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("orders.id"), nullable=True, comment="成交后关联订单ID")

    # ---- 时间戳 ----
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), comment="最后更新时间")

    # ---- 索引 ----
    __table_args__ = (
        # 唯一约束：同一客户对同一商品只保留一条销售管线记录
        Index("idx_cpc_contact_product", "tenant_id", "contact_id", "product_id", unique=True),
        # 按订单 ID 反查关联的商品销售管线
        Index("idx_cpc_order", "order_id"),
        {"comment": "客户与商品销售管线上下文"},
    )


class SalesTemplate(Base):
    """销售话术模板 —— 商品可以通过 products.sales_template_id 关联此表。

    业务角色：
    ---------
    存储预设的销售话术文本，按场景（scene）分类。AI Agent 在与客户对话时，
    根据当前销售阶段和客户意图，从此表检索合适的话术模板，经 LLM 润色后
    自然融入对话回复中。

    使用场景示例：
    -------------
    - scene="greeting": 新客欢迎语模板。
    - scene="product_intro": 商品介绍话术。
    - scene="price_negotiation": 议价应对话术。
    - scene="followup": 跟进回访话术。
    - scene="closing": 促单话术。

    字段说明：
    ---------
    - name: 模板名称，便于管理员在后台识别和管理。
    - content: 话术正文，支持变量占位符如 {product_name} / {customer_name}。
    - scene: 适用场景标识，Agent 按场景检索匹配的模板。
    - metadata_: JSONB 扩展信息，如适用范围、AB 测试分组等（列名 "metadata"）。
    """

    __tablename__ = "sales_templates"

    # ---- 主键 ----
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, default=generate_id, comment="主键")

    # ---- 归属 ----
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenants.id"), nullable=False, comment="所属租户")

    # ---- 模板内容 ----
    name: Mapped[str] = mapped_column(String(200), nullable=False, comment="模板名称")

    content: Mapped[str] = mapped_column(Text, nullable=False, comment="话术正文，支持 {product_name} 占位符")

    scene: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="适用场景: greeting / product_intro / price_negotiation / followup / closing")

    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True, comment="扩展信息 JSON（列名 metadata）")

    # ---- 时间戳 ----
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), comment="创建时间")

    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), comment="更新时间")

    # ---- 索引 ----
    __table_args__ = (
        # 按租户检索所有模板（后台模板管理页面默认查询）
        Index("idx_sales_templates_tenant", "tenant_id"),
        {"comment": "销售话术模板"},
    )


class FollowupPlan(Base):
    """客户跟进计划 —— AI Agent 或人工坐席创建的定时跟进任务。

    业务角色：
    ---------
    定义对特定客户的跟进任务，包含发送内容和预定时间。当前阶段（Phase 7+）
    只负责计划的 CRUD 和状态管理。后续接入 Celery Beat 定时任务后，
    调度器会扫描 scheduled_at 到期且 status 为 pending 的记录，按以下顺序执行：

    1. 检查发送窗口（如 9:00-21:00）
    2. 检查冷却时间（距离上次跟进是否满足最小间隔）
    3. 检查退订状态（客户是否已退订自动消息）
    4. 敏感词校验（消息内容是否触发敏感词规则）
    5. 执行发送 → 更新 status 为 sent / failed

    状态说明：
    ---------
    - pending: 等待执行
    - sent: 已发送
    - failed: 发送失败（查看 failure_reason）
    - cancelled: 已取消
    - cooling: 冷却中（被调度器跳过）

    字段说明：
    ---------
    - scheduled_at: 计划发送时间，调度器按此字段扫描到期任务。
    - created_by_type: 创建来源 —— "agent" AI自动创建 / "human" 人工创建。
    - failure_reason: 失败原因，仅在 status=failed 时有值。
    - sent_at: 实际发送时间，仅在 status=sent 时有值。
    """

    __tablename__ = "followup_plans"

    # ---- 主键 ----
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, default=generate_id, comment="主键")

    # ---- 关联 ----
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenants.id"), nullable=False, comment="所属租户")

    contact_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("contacts.id"), nullable=False, comment="目标客户")

    conversation_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("conversations.id"), nullable=True, comment="关联会话ID")

    # ---- 计划内容 ----
    content: Mapped[str] = mapped_column(Text, nullable=False, comment="发送消息内容")

    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, comment="计划发送时间")

    # ---- 状态 ----
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", server_default="pending", comment="执行状态: pending / sent / failed / cancelled / cooling")

    created_by_type: Mapped[str] = mapped_column(String(20), nullable=False, default="agent", server_default="agent", comment="创建来源: agent / human")

    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True, comment="失败原因")

    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, comment="实际发送时间")

    # ---- 时间戳 ----
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), comment="创建时间")

    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), comment="更新时间")

    # ---- 索引 ----
    __table_args__ = (
        # 调度器核心查询：按租户 + 状态 + 计划时间检索到期待发送任务
        Index("idx_followup_tenant_status_time", "tenant_id", "status", "scheduled_at"),
        # 客户维度查看所有跟进计划历史
        Index("idx_followup_contact", "tenant_id", "contact_id"),
        {"comment": "客户跟进计划"},
    )


class ConversationTodo(Base):
    """会话待办 —— AI Agent 和人工坐席共用同一张表。

    业务角色：
    ---------
    在会话过程中，AI Agent 或人工坐席可以创建待办事项，标记需要在后续跟进
    处理的事项。例如：客户要求查库存（待办）、需要人工介入处理投诉（待办）、
    承诺 3 天后回访（待办）。待办统一由此表管理，前端 Agent 工作台展示待办列表。

    AI 与人工共用：
    --------------
    同一张表同时服务于两类场景：
    - AI Agent 识别到需要人工介入时自动创建待办（created_by_type="agent"）
    - 人工坐席手动标记待跟进事项（created_by_type="human"）
    通过 created_by_type 字段区分来源，便于统计 AI 自动化率。

    字段说明：
    ---------
    - content: 待办描述，AI 或人工填写。
    - keywords: JSONB 关键词标签，用于分类和检索（如 ["投诉", "退款", "紧急"]）。
    - due_at: 截止时间，超过后前端高亮提醒。
    - completed_at: 完成时间，有值表示已完成（status 同步更新为 completed）。
    """

    __tablename__ = "conversation_todos"

    # ---- 主键 ----
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, default=generate_id, comment="主键")

    # ---- 关联 ----
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenants.id"), nullable=False, comment="所属租户")

    conversation_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("conversations.id"), nullable=False, comment="关联会话")

    contact_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("contacts.id"), nullable=False, comment="关联客户（冗余）")

    # ---- 待办内容 ----
    content: Mapped[str] = mapped_column(Text, nullable=False, comment="待办事项描述")

    keywords: Mapped[list | None] = mapped_column(JSONB, nullable=True, comment="关键词标签 JSON")

    # ---- 状态 ----
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", server_default="pending", comment="待办状态: pending / completed / cancelled")

    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, comment="截止时间")

    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, comment="完成时间")

    created_by_type: Mapped[str] = mapped_column(String(20), nullable=False, default="agent", server_default="agent", comment="创建来源: agent / human")

    # ---- 时间戳 ----
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), comment="创建时间")

    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), comment="更新时间")

    # ---- 索引 ----
    __table_args__ = (
        # 按会话检索该会话下的所有待办（Agent 工作台加载会话时关联查询）
        Index("idx_todos_tenant_conversation", "tenant_id", "conversation_id"),
        # 按客户 + 状态检索某客户的所有待处理事项（坐席工作台高频查询）
        Index("idx_todos_tenant_contact_status", "tenant_id", "contact_id", "status"),
        {"comment": "会话待办"},
    )
