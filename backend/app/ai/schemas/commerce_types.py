"""电商 AI 链路统一 DTO。

这些类型约束路由、引用解析、咨询、动作、Skill 和回复之间的协议。
订单金额、状态和明细不长期复制到上下文，必须通过数据库或 Skill 获取。
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class CommerceRoute(str, Enum):
    """电商消息路由方向。"""
    PRODUCT_CONSULT = "PRODUCT_CONSULT"   # 商品咨询（搜索、详情、对比）
    ORDER_ACTION = "ORDER_ACTION"         # 订单动作（创建、修改、确认、取消）
    GENERAL_RAG = "GENERAL_RAG"           # 非电商意图，交给通用 RAG 管线
    FALLBACK = "FALLBACK"                 # 退出 / 重置当前电商流程


class ActionType(str, Enum):
    """电商规则路由的动作类型。"""
    EXIT_FLOW = "exit_flow"                   # 退出当前流程
    QUERY_ORDER = "query_order"               # 查询订单
    CANCEL_ORDER = "cancel_order"             # 取消订单草稿
    CONFIRM_ORDER = "confirm_order"           # 确认下单
    UPDATE_QUANTITY = "update_quantity"       # 修改草稿订单数量
    UPDATE_CONTACT = "update_contact"         # 修改联系方式（地址/电话）
    CREATE_DRAFT_ORDER = "create_draft_order" # 创建订单草稿
    COMPARE_PRODUCTS = "compare_products"          # 商品对比
    CONSULT_PRODUCT = "consult_product"            # 商品咨询
    PRODUCT_CATEGORY_QUERY = "product_category_query"        # 按分类查询商品
    PRODUCT_CATEGORY_OVERVIEW = "product_category_overview"  # 公司分类总览
    PRODUCT_REFERENCE_AMBIGUOUS = "product_reference_ambiguous"  # 商品引用有歧义
    PRODUCT_CONSULT = "product_consult"                     # 商品咨询（通用）
    ASK_PRODUCT_SELECTION = "ask_product_selection"         # 让用户选择商品


class SkillName(str, Enum):
    """技能名称常量。"""
    # 产品相关
    GET_PRODUCT_DETAIL = "get_product_detail"                # 获取商品详情
    SEARCH_PRODUCTS = "search_products"                      # 搜索商品
    LIST_PRODUCT_CATEGORIES = "list_product_categories"      # 列出商品分类
    # 订单相关
    MANAGE_ORDER = "manage_order"                            # 管理/查询订单
    CANCEL_ORDER_DRAFT = "cancel_order_draft"                # 取消订单草稿
    CONFIRM_ORDER = "confirm_order"                        # 确认提交订单
    UPDATE_DRAFT_ORDER_QUANTITY = "update_draft_order_quantity"  # 更新草稿数量
    UPDATE_ORDER_DRAFT = "update_order_draft"              # 更新草稿信息
    CREATE_ORDER_DRAFT = "create_order_draft"              # 创建订单草稿


class ResponseType(str, Enum):
    """回复类型常量。"""
    FLOW_EXIT = "flow_exit"                       # 退出流程
    ORDER_QUERY_RESULT = "order_query_result"     # 订单查询结果
    ORDER_CANCELLED = "order_cancelled"           # 订单已取消
    ORDER_CONFIRMED = "order_confirmed"           # 订单已确认
    DRAFT_ORDER_CREATED = "draft_order_created"   # 草稿已创建
    DRAFT_ORDER_UPDATED = "draft_order_updated"   # 草稿已更新
    MISSING_SLOTS = "missing_slots"               # 缺少必填信息
    PRODUCT_COMPARE = "product_compare"           # 商品对比
    PRODUCT_KNOWLEDGE_ANSWER = "product_knowledge_answer"  # 基于知识库的商品回答
    PRODUCT_CATEGORY_LIST = "product_category_list"        # 公司商品分类列表
    PRODUCT_DETAIL = "product_detail"                      # 单个商品详情
    PRODUCT_CANDIDATES = "product_candidates"              # 商品候选列表
    CANDIDATE_CLARIFICATION = "candidate_clarification"    # 候选商品歧义澄清
    TRANSFER_HUMAN = "transfer_human"                      # 建议转人工
    FALLBACK = "fallback"                                  # 兜底回复


class RiskLevel(str, Enum):
    """操作风险等级，决定是否需要审批或人工确认。"""
    READ_ONLY = "READ_ONLY"           # 只读操作（查询商品、浏览列表）
    LOW_RISK_WRITE = "LOW_RISK_WRITE"       # 低风险写（创建草稿、修改数量）
    HIGH_RISK_WRITE = "HIGH_RISK_WRITE"     # 高风险写（确认下单、取消订单）


class CostLevel(str, Enum):
    """回复生成成本等级，用于计费和监控。"""
    FREE_RULE = "FREE_RULE"   # 零成本（规则模板直接输出）
    FREE_DB = "FREE_DB"       # 仅数据库查询（无 LLM 调用）
    LOW_QA = "LOW_QA"         # 低成本（QA 标准答案直出，不经过 LLM）
    HIGH_LLM = "HIGH_LLM"     # 高成本（需要调用 LLM 生成回答）


class UserMessage(BaseModel):
    """用户消息 DTO（电商链路入口的标准化输入）。"""
    model_config = ConfigDict(extra="allow")

    tenant_id: int                             # 租户 ID
    conversation_id: int                       # 会话 ID
    text: str                                  # 用户消息原文
    customer_id: int | None = None             # 客户联系人 ID
    user_id: int | None = None                 # 当前坐席 ID
    channel: str | None = None                 # 渠道标识（wecom / web / api）
    timestamp: datetime | None = None          # 消息时间戳


class IntentResult(BaseModel):
    """意图识别结果（LLM 分类器输出，规则路由的备用路径）。"""
    model_config = ConfigDict(extra="allow")

    intent: str                                      # 识别到的意图名称
    confidence: float = 1.0                          # 置信度 [0, 1]
    route: CommerceRoute                             # 对应的路由方向
    reason: str | None = None                        # 分类依据
    candidates: list[dict[str, Any]] = Field(default_factory=list)  # 候选意图列表


class SlotResult(BaseModel):
    """从用户消息中抽取的槽位信息，供后续电商流程使用。"""
    model_config = ConfigDict(extra="allow")

    product_keyword: str | None = None     # 清洗后的商品关键词（去掉了"买""怎么样"等动作词）
    category: str | None = None            # 分类名称（如"耳机""平板"）
    product_id: str | None = None          # 商品 ID
    quantity: int | None = None            # 数量（绝对值，如 2 表示买 2 件）
    quantity_delta: int | None = None      # 数量变化值（+1 表示加一件，-1 表示减一件）
    address: str | None = None             # 收货地址
    phone: str | None = None               # 联系电话
    selection_index: int | None = None     # 用户选择的候选序号（0-based，"第一个" → 0）
    confirm_flag: bool = False             # 是否确认指令
    cancel_flag: bool = False              # 是否取消指令
    order_id: str | None = None            # 订单号
    min_price: float | None = None         # 预算最低价
    max_price: float | None = None         # 预算最高价


ProductReferenceSource = Literal[
    "selected_product",           # 用户当前选中的商品（如之前点了"这款"）
    "last_product",               # 上一次交互中提到的商品（通过 last_product_id 匹配）
    "pending_candidates_index",   # 上一轮推荐列表中按序号选中（如"第二个"）
    "pending_candidates_name",    # 上一轮推荐列表中按名称模糊匹配
    "global_search",              # 全库搜索匹配（无上下文时兜底查到商品名）
]


class ProductReferenceResult(BaseModel):
    """商品引用解析结果：用户在指代哪个商品？"""
    model_config = ConfigDict(extra="allow")

    matched: bool = False                              # 是否成功解析到商品
    product_id: str | None = None                      # 解析到的商品 ID
    product_name: str | None = None                    # 解析到的商品名
    source: ProductReferenceSource | None = None       # 匹配来源（序号 / 名称 / 全局搜索）
    confidence: float = 0.0                            # 匹配置信度
    ambiguous: bool = False                            # 是否歧义（多个候选中无法确定）
    candidates: list[dict[str, Any]] = Field(default_factory=list)  # 歧义时的候选列表
    reason: str | None = None                          # 匹配原因或失败原因

    @property
    def product(self) -> dict[str, Any] | None:
        if not self.matched or self.ambiguous:
            return None
        payload: dict[str, Any] = {}
        if self.product_id is not None:
            payload["id"] = self.product_id
        if self.product_name is not None:
            payload["name"] = self.product_name
        if self.candidates:
            payload.update(self.candidates[0])
        return payload or None


class CommerceContext(BaseModel):
    """电商对话上下文，在一次会话的生命周期中跨轮次传递。

    注意：商品详情（价格、库存）不长期缓存在上下文中，
    必须通过 DB / Skill 获取最新数据。这里只存引用键。
    """
    model_config = ConfigDict(extra="allow")

    tenant_id: int | None = None                                 # 租户 ID
    customer_id: int | None = None                               # 客户联系人 ID
    user_id: int | None = None                                   # 当前坐席 ID
    conversation_id: int | None = None                           # 会话 ID
    current_stage: str = "IDLE"                                  # 当前阶段（IDLE / PRODUCT_SELECTED / ORDER_DRAFTING 等）
    pending_candidates: list[dict[str, Any]] = Field(default_factory=list)         # 当前等待用户选择的候选商品
    last_displayed_candidates: list[dict[str, Any]] = Field(default_factory=list)  # 上一次展示的候选商品
    disambiguation_candidates: list[dict[str, Any]] = Field(default_factory=list)  # 歧义消解的候选商品
    search_candidates: list[dict[str, Any]] = Field(default_factory=list)          # 搜索返回的全部候选
    selected_product_id: str | None = None                       # 用户明确选中的商品 ID
    last_product_id: str | None = None                           # 上一次交互涉及的商品 ID
    last_product_category: str | None = None                     # 上一次查询的分类名
    last_product_keyword: str | None = None                      # 上一次查询的商品关键词（用于指代兜底："它怎么样"）
    draft_order_id: str | None = None                            # 当前草稿订单 ID
    pending_quantity: int | None = None                          # 等待确认的数量
    pending_address: str | None = None                           # 等待补充的地址
    pending_phone: str | None = None                             # 等待补充的电话
    last_intent: str | None = None                               # 上一次识别的意图
    last_route: str | None = None                                # 上一次路由方向
    last_response_type: str | None = None                        # 上一次回复类型
    last_skill: str | None = None                                # 上一次调用的技能名
    last_user_message: str | None = None                         # 用户上一次发送的消息原文
    updated_at: datetime | str | None = None                     # 上下文更新时间


class DecisionResult(BaseModel):
    """路由决策结果：规则路由完成后输出的方向 + 动作。"""
    model_config = ConfigDict(extra="allow")

    route: CommerceRoute                                         # 路由方向（产品咨询 / 订单动作 / 通用 RAG / 退出）
    action_type: str | None = None                               # 动作类型（consult_product / create_draft_order 等）
    skill_name: str | None = None                                # 应该调用的技能名（如 search_products / confirm_order）
    skill_params: dict[str, Any] = Field(default_factory=dict)   # 传递给技能的参数
    response_type: str | None = None                             # 回复模板类型（product_detail / order_confirmed / fallback）
    risk_level: RiskLevel = RiskLevel.READ_ONLY                  # 操作风险等级
    reason: str | None = None                                    # 决策原因（调试用）
    context_updates: dict[str, Any] = Field(default_factory=dict) # 需要同步到上下文的状态更新


class SkillResult(BaseModel):
    """技能调用结果（封装 ToolResult 的内部结构）。"""
    model_config = ConfigDict(extra="allow")

    success: bool                                                # 技能是否执行成功
    skill_name: str                                              # 技能名称
    data: Any = None                                             # 技能返回的业务数据
    error_code: str | None = None                                # 错误码
    error_message: str | None = None                             # 错误描述
    changed_fields: list[str] = Field(default_factory=list)      # 被修改的字段列表（审计用）
    audit_info: dict[str, Any] = Field(default_factory=dict)     # 审计信息


class ReplyResult(BaseModel):
    """最终回复：咨询/动作链路输出后发送给用户的消息。"""
    model_config = ConfigDict(extra="allow")

    handled: bool = True                                         # 是否已处理（False 时交给下游兜底）
    text: str                                                    # 发送给用户的回复文本
    response_type: str                                           # 回复类型（product_detail / order_confirmed / fallback 等）
    route: CommerceRoute | str | None = None                     # 来源路由
    risk_level: RiskLevel | str | None = None                    # 操作风险等级
    skill_result: SkillResult | None = None                      # 关联的技能调用结果
    cost_level: CostLevel | str = CostLevel.FREE_RULE            # 回复生成成本（规则 / DB / QA / LLM）
    response_mode: CostLevel | str | None = None                 # 实际使用的生成模式
    should_push: bool = True                                     # 是否需要推送给用户
    context_updates: dict[str, Any] = Field(default_factory=dict) # 需要同步到会话状态的数据
    metadata: dict[str, Any] = Field(default_factory=dict)       # 附加元数据（前端展示用）
