"""HandlerRegistry — 场景 ID → Handler 的注册与路由。

相同 scenario_id 只能注册一个 Handler。
"""

from __future__ import annotations

from app.ai.handlers.base import BaseHandler


def register_default_handlers(registry: HandlerRegistry) -> None:
    """注册默认 Handler 到 registry。"""
    from app.ai.handlers.human import HumanHandler
    from app.ai.handlers.knowledge import KnowledgeHandler
    from app.ai.handlers.memory import MemoryHandler
    from app.ai.handlers.order import OrderHandler
    from app.ai.handlers.product import ProductHandler
    from app.ai.handlers.template import TemplateHandler

    # Template
    registry.register("template.greeting", TemplateHandler())
    registry.register("template.confirmation", TemplateHandler())
    registry.register("template.farewell", TemplateHandler())
    registry.register("template.silent", TemplateHandler())
    registry.register("template.fallback", TemplateHandler())
    registry.register("template.clarify", TemplateHandler())

    # Human
    registry.register("human.transfer", HumanHandler())

    # Product
    registry.register("product.catalog", ProductHandler())
    registry.register("product.filter_search", ProductHandler())
    registry.register("product.semantic_recommend", ProductHandler())
    registry.register("product.sku_query", ProductHandler())
    registry.register("product.detail", ProductHandler())
    registry.register("product.compare", ProductHandler())
    registry.register("product.attribute_query", ProductHandler())
    registry.register("product.usage", ProductHandler())
    registry.register("product.pagination_sort", ProductHandler())

    # Order
    registry.register("order.list", OrderHandler())
    registry.register("order.filter", OrderHandler())
    registry.register("order.detail", OrderHandler())
    registry.register("order.shipping_status", OrderHandler())
    registry.register("order.create", OrderHandler())
    registry.register("order.cancel", OrderHandler())
    registry.register("order.confirm", OrderHandler())
    registry.register("order.refund", OrderHandler())

    # Knowledge
    registry.register("knowledge.policy", KnowledgeHandler())
    registry.register("knowledge.qa", KnowledgeHandler())
    registry.register("knowledge.product_qa", KnowledgeHandler())

    # Memory
    registry.register("memory.save", MemoryHandler())
    registry.register("memory.recall", MemoryHandler())


class HandlerRegistry:
    """场景 ID 到 Handler 的映射注册表。"""

    def __init__(self) -> None:
        self._handlers: dict[str, BaseHandler] = {}

    def register(self, scenario_id: str, handler: BaseHandler) -> None:
        """注册 Handler。相同 scenario_id 重复注册抛出 ValueError。"""
        if scenario_id in self._handlers:
            raise ValueError(f"场景 {scenario_id} 已有注册的 Handler: {type(self._handlers[scenario_id]).__name__}")
        self._handlers[scenario_id] = handler

    def get(self, scenario_id: str) -> BaseHandler | None:
        """根据场景 ID 获取 Handler。"""
        return self._handlers.get(scenario_id)

    def has(self, scenario_id: str) -> bool:
        """检查场景 ID 是否已注册。"""
        return scenario_id in self._handlers
