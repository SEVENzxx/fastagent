"""ScenarioSpec — 场景权限规约。

定义每个场景的允许行为边界，由 PolicyGuard 在 _finalize() 中校验。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

RiskLevel = Literal["read_only", "write_confirm", "human_required"]


class ScenarioSpec(BaseModel):
    """场景规约：定义该场景允许的行为边界。

    在 _finalize() 中，PolicyGuard 根据 HandlerResult.resource_trace
    与 ScenarioSpec 逐条校验，越权时降级回复。
    """

    scenario_id: str = Field(description="场景 ID")
    allowed_skills: list[str] = Field(
        default_factory=list,
        description="允许调用的 Skill 方法名列表",
    )
    allowed_context_reads: list[str] = Field(
        default_factory=list,
        description="允许读取的 SessionContext 字段",
    )
    allowed_context_writes: list[str] = Field(
        default_factory=list,
        description="允许写入的 SessionContext 字段",
    )
    allow_llm_entity_extraction: bool = Field(
        default=False,
        description="是否允许 LLM 实体抽取",
    )
    allow_llm_reply_generation: bool = Field(
        default=False,
        description="是否允许 LLM 回复生成（摘要等）",
    )
    allow_vector_search: bool = Field(
        default=False,
        description="是否允许向量检索",
    )
    allow_pending: bool = Field(
        default=False,
        description="是否允许 SET PendingState",
    )
    risk_level: RiskLevel = Field(
        default="read_only",
        description="风险等级：read_only / write_confirm / human_required",
    )


# ── 写操作 Skill 集合（用于 risk_level 校验） ──

WRITE_SKILL_NAMES: frozenset[str] = frozenset({
    "create_order_draft",
    "confirm_order",
    "cancel_order_draft",
    "update_order_draft",
    "update_draft_order_quantity",
    "remember_info",
})


# ── 场景规约注册表 ──

SCENARIO_SPECS: dict[str, ScenarioSpec] = {
    # ══════════════════════════════════════════
    # Template
    # ══════════════════════════════════════════
    "template.greeting": ScenarioSpec(
        scenario_id="template.greeting",
        allowed_skills=[],
        risk_level="read_only",
    ),
    "template.confirmation": ScenarioSpec(
        scenario_id="template.confirmation",
        allowed_skills=[],
        risk_level="read_only",
    ),
    "template.farewell": ScenarioSpec(
        scenario_id="template.farewell",
        allowed_skills=[],
        risk_level="read_only",
    ),
    "template.silent": ScenarioSpec(
        scenario_id="template.silent",
        allowed_skills=[],
        risk_level="read_only",
    ),
    "template.fallback": ScenarioSpec(
        scenario_id="template.fallback",
        allowed_skills=[],
        risk_level="read_only",
    ),
    "template.clarify": ScenarioSpec(
        scenario_id="template.clarify",
        allowed_skills=[],
        risk_level="read_only",
    ),

    # ══════════════════════════════════════════
    # Human
    # ══════════════════════════════════════════
    "human.transfer": ScenarioSpec(
        scenario_id="human.transfer",
        allowed_skills=[],
        risk_level="human_required",
    ),

    # ══════════════════════════════════════════
    # Product
    # ══════════════════════════════════════════
    "product.catalog": ScenarioSpec(
        scenario_id="product.catalog",
        allowed_skills=["list_categories", "search_products"],
        risk_level="read_only",
    ),
    "product.filter_search": ScenarioSpec(
        scenario_id="product.filter_search",
        allowed_skills=["search_products"],
        allow_llm_entity_extraction=True,
        risk_level="read_only",
    ),
    "product.semantic_recommend": ScenarioSpec(
        scenario_id="product.semantic_recommend",
        allowed_skills=["search_products"],
        allow_llm_entity_extraction=True,
        allow_vector_search=True,
        risk_level="read_only",
    ),
    "product.sku_query": ScenarioSpec(
        scenario_id="product.sku_query",
        allowed_skills=["search_by_sku"],
        risk_level="read_only",
    ),
    "product.detail": ScenarioSpec(
        scenario_id="product.detail",
        allowed_skills=["get_detail", "search_products", "search_product_knowledge"],
        allow_llm_entity_extraction=True,
        allow_llm_reply_generation=True,
        allow_vector_search=True,
        risk_level="read_only",
    ),
    "product.compare": ScenarioSpec(
        scenario_id="product.compare",
        allowed_skills=["batch_get_detail", "get_detail", "search_products"],
        risk_level="read_only",
    ),
    "product.attribute_query": ScenarioSpec(
        scenario_id="product.attribute_query",
        allowed_skills=["search_products", "get_detail", "get_attribute"],
        risk_level="read_only",
    ),
    "product.usage": ScenarioSpec(
        scenario_id="product.usage",
        allowed_skills=["get_detail", "search_product_knowledge"],
        allow_llm_entity_extraction=True,
        allow_llm_reply_generation=True,
        allow_vector_search=True,
        risk_level="read_only",
    ),
    "product.pagination_sort": ScenarioSpec(
        scenario_id="product.pagination_sort",
        allowed_skills=["batch_get_detail"],
        risk_level="read_only",
    ),

    # ══════════════════════════════════════════
    # Order — 只读
    # ══════════════════════════════════════════
    "order.list": ScenarioSpec(
        scenario_id="order.list",
        allowed_skills=["manage_order"],
        risk_level="read_only",
    ),
    "order.filter": ScenarioSpec(
        scenario_id="order.filter",
        allowed_skills=["manage_order"],
        risk_level="read_only",
    ),
    "order.detail": ScenarioSpec(
        scenario_id="order.detail",
        allowed_skills=["manage_order"],
        risk_level="read_only",
    ),
    "order.shipping_status": ScenarioSpec(
        scenario_id="order.shipping_status",
        allowed_skills=["manage_order"],
        risk_level="read_only",
    ),

    # ══════════════════════════════════════════
    # Order — 写操作
    # ══════════════════════════════════════════
    "order.create": ScenarioSpec(
        scenario_id="order.create",
        allowed_skills=["manage_order", "create_order_draft"],
        allow_pending=True,
        risk_level="write_confirm",
    ),
    "order.cancel": ScenarioSpec(
        scenario_id="order.cancel",
        allowed_skills=["manage_order", "cancel_order_draft"],
        allow_pending=True,
        risk_level="write_confirm",
    ),
    "order.confirm": ScenarioSpec(
        scenario_id="order.confirm",
        allowed_skills=["confirm_order"],
        allow_pending=True,
        risk_level="write_confirm",
    ),
    "order.refund": ScenarioSpec(
        scenario_id="order.refund",
        allowed_skills=["manage_order", "create_refund"],
        allow_pending=True,
        risk_level="write_confirm",
    ),

    # ══════════════════════════════════════════
    # Knowledge
    # ══════════════════════════════════════════
    "knowledge.qa": ScenarioSpec(
        scenario_id="knowledge.qa",
        allowed_skills=["search_qa", "search_knowledge"],
        allow_llm_reply_generation=True,
        allow_vector_search=True,
        risk_level="read_only",
    ),
    "knowledge.policy": ScenarioSpec(
        scenario_id="knowledge.policy",
        allowed_skills=["search_qa", "search_knowledge"],
        allow_llm_reply_generation=True,
        allow_vector_search=True,
        risk_level="read_only",
    ),
    "knowledge.product_qa": ScenarioSpec(
        scenario_id="knowledge.product_qa",
        allowed_skills=["search_qa", "search_knowledge"],
        allow_llm_reply_generation=True,
        allow_vector_search=True,
        risk_level="read_only",
    ),

    # ══════════════════════════════════════════
    # Memory
    # ══════════════════════════════════════════
    "memory.save": ScenarioSpec(
        scenario_id="memory.save",
        allowed_skills=["remember_info"],
        risk_level="write_confirm",
    ),
    "memory.recall": ScenarioSpec(
        scenario_id="memory.recall",
        allowed_skills=["recall_info"],
        risk_level="read_only",
    ),
}


def get_spec(scenario_id: str) -> ScenarioSpec | None:
    """按场景 ID 获取 ScenarioSpec，不存在返回 None。"""
    return SCENARIO_SPECS.get(scenario_id)


def is_write_skill(skill_name: str) -> bool:
    """判断是否为写操作 Skill。"""
    return skill_name in WRITE_SKILL_NAMES
