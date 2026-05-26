"""意图向量召回样本。

真实生产中这些 example_text 会提前向量化并写入向量库。当前实现用轻量文本相似度模拟召回，
但 metadata 结构保持和未来向量库一致。
"""

from __future__ import annotations

from dataclasses import dataclass

from app.services.ai.intent.types import RouteType


@dataclass(frozen=True, slots=True)
class IntentExample:
    """标准意图样本 metadata。"""

    intent: str
    label: str
    route: RouteType
    skill: str | None
    example_text: str


DEFAULT_INTENT_EXAMPLES: tuple[IntentExample, ...] = (
    IntentExample("product_price", "商品价格", "AGENT", "product_price", "这个多少钱"),
    IntentExample("product_price", "商品价格", "AGENT", "product_price", "价格多少"),
    IntentExample("product_price", "商品价格", "AGENT", "product_price", "有没有优惠"),
    IntentExample("product_stock", "商品库存", "AGENT", "product_stock", "这个有货吗"),
    IntentExample("product_stock", "商品库存", "AGENT", "product_stock", "还有库存吗"),
    IntentExample("product_stock", "商品库存", "AGENT", "product_stock", "有没有现货"),
    IntentExample("delivery_time", "发货时效", "AGENT", "delivery_time", "今天能发吗"),
    IntentExample("delivery_time", "发货时效", "AGENT", "delivery_time", "什么时候发货"),
    IntentExample("order_status", "订单状态", "AGENT", "order_status", "我的订单怎么还没发货"),
    IntentExample("order_status", "订单状态", "AGENT", "order_status", "订单处理到哪了"),
    IntentExample("logistics_status", "物流状态", "AGENT", "logistics_status", "物流到哪里了"),
    IntentExample("logistics_status", "物流状态", "AGENT", "logistics_status", "快递到哪了"),
    IntentExample("invoice", "发票", "AGENT", "invoice", "可以开发票吗"),
    IntentExample("product_search", "商品搜索", "AGENT", "search_products", "帮我推荐商品"),
)
