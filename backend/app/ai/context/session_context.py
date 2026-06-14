"""统一会话上下文 DTO — 跨轮次传递的结构化状态。

单模型贯穿所有层：Pydantic model_dump / model_validate 直接序列化到 Redis。
不存长聊天记录。商品详情、价格、库存不长期缓存，必须通过 DB / skill 获取最新数据。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class SessionContext(BaseModel):
    """跨轮次传递的统一会话上下文。

    上下文规则：
      - 商品详情/价格/库存不长期缓存，必须通过 DB / skill 获取最新数据。
      - 订单金额/状态不只信 Redis，执行前必须查 DB。
      - 商品上下文可按轮次或 TTL 清理。
      - 订单上下文不能简单按 3 轮清空，必须看订单状态和 pending action。
      - 用户切换商品只清商品域上下文，不清订单域。
      - 用户明确退出当前流程时清 pending candidates / confirmation / slot。
    """

    # ── 租户与会话标识 ──
    tenant_id: int = 0                                           # 租户 ID
    conversation_id: int = 0                                     # 当前会话 ID
    contact_id: int | None = None                                # 当前客户联系人 ID

    # ── 上一轮路由信息（用于上下文连贯和消歧） ──
    last_skill: str | None = None                                # 上一轮调用的 Skill
    last_intent: str | None = None                               # 上一轮识别的用户意图
    turn_count: int = 0                                          # 当前会话已交互轮数
    last_user_message: str | None = None                         # 用户上一轮发送的原始消息文本

    # ── 商品域上下文（当前浏览/比较的商品信息） ──
    active_product_ids: list[str] = Field(default_factory=list)          # 当前对话活跃商品 ID 列表
    active_product_names: list[str] = Field(default_factory=list)        # 当前对话活跃商品名称列表
    last_product_id: str | None = None                                    # 最近一次引用的商品 ID（指代解析用）
    last_product_name: str | None = None                                  # 最近一次引用的商品名称
    last_focus_product_id: str | None = None                              # 当前焦点商品 ID（等价于 last_product_id，遵循架构文档命名）
    compare_base_product_id: str | None = None                            # 对比基准商品 ID（对比延续时使用）
    product_page: int = 1                                                       # 商品列表当前页码
    product_candidates: list[dict[str, Any]] = Field(default_factory=list)       # 搜索/推荐的商品候选列表
    disambiguation_candidates: list[dict[str, Any]] = Field(default_factory=list) # 需用户澄清的消歧候选
    product_context_round: int = 0                                              # 商品上下文已持续轮数（超阈值可清理）
    product_search_history: list[dict[str, Any]] = Field(default_factory=list)  # 近5轮商品搜索结果滑动窗口 [{"round": N, "products": [{"id":..., "name":...}]}]

    # ── 订单域上下文（当前进行中的订单状态） ──
    active_order_id: str | None = None                           # 当前操作的目标订单 ID
    draft_order_id: str | None = None                            # 草稿态订单 ID（未提交确认）
    active_order_state: str | None = None                        # 目标订单当前状态
    pending_order_action: str | None = None                      # 待执行的订单操作（confirm / cancel）
    recent_orders: list[dict[str, Any]] = Field(default_factory=list)  # 最近订单候选列表 [{"id": ..., "status": ..., "amount": ...}]

    # ── 槽位与确认（多轮补槽 + 高危操作审批） ──
    slots: dict[str, Any] = Field(default_factory=dict)              # 已填充的槽位键值对
    pending_slot: str | None = None                                   # 当前等待用户补充的槽位名称
    pending_confirmation: dict[str, Any] | None = None                # 待用户确认的操作快照
    pending_human_approval: dict[str, Any] | None = None              # 待坐席审批的高危操作

    # ── 知识域上下文（用于追问续查和精准召回） ──
    last_knowledge_topic: str | None = None                      # 知识主题，如 "优惠活动", "保修政策"
    last_knowledge_scope: str | None = None                      # 来源范围: "qa" 或 "knowledge"
    last_knowledge_refs: list[dict] = Field(default_factory=list)  # 最近知识引用，最多 5 条：{source_type, source_id, doc_id, chunk_id, title, content_preview}

    # ── 元数据 ──
    updated_at: str | None = None                                # 上下文最近更新时间（ISO 8601）

    def apply(self, updates: dict[str, Any]) -> SessionContext:
        """应用上下文更新，返回新实例。"""
        if not updates:
            return self
        return self.model_copy(update=updates)
