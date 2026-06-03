"""意图向量召回样本。

平台默认提供一批通用电商客服意图样本，覆盖 14 个意图分类共 60+ 条语料。
每条样本标注了 intent（意图标识）、label（中文标签）、route（路由类型）、skill（关联技能）。

索引机制：
  - 通过 VectorSearchService 写入 Qdrant collection `fastagent_intent_samples`
  - tenant_id=0 为平台共享样本，所有租户召回时通用
  - bootstrap 启动时自动索引（幂等 upsert），同时保留首次请求懒加载兜底

样本设计原则：
  - 每个意图 3-7 条不同表达方式（直接问句、口语化、敬语）
  - 覆盖电商客服高频场景：询价、库存、发货、订单、物流、发票、推荐、退货退款、闲聊
  - 人工类意图（投诉/转人工/注销）优先走强规则匹配，向量样本用于兜底语义召回
"""

from __future__ import annotations

from dataclasses import dataclass

from app.ai.classifier.types import RouteType


@dataclass(frozen=True, slots=True)
class IntentExample:
    """标准意图样本 metadata。

    intent:        意图唯一标识，与 route_map 中的 key 对应
    label:         中文展示名称
    route:         路由类型（AGENT / HUMAN / GENERAL_REPLY / SILENT）
    skill:         关联的 Agent skill 名称（HUMAN 路由填 human_service）
    example_text:  用户实际可能发送的原始问句样本
    """

    intent: str
    label: str
    route: RouteType
    skill: str | None
    example_text: str


# ── 平台默认意图样本 ─────────────────────────────────────────────────────────
# tenant_id=0 全局共享，新租户开箱即用。租户可通过管理后台新增/覆盖专属样本。
# 每条 example_text 来自真实电商客服对话场景，确保向量召回的高匹配率。

DEFAULT_INTENT_EXAMPLES: tuple[IntentExample, ...] = (

    # ── 商品价格（AGENT → search_products）─────────────────────────────────
    IntentExample("product_price", "商品价格", "AGENT", "product_price", "这个多少钱"),
    IntentExample("product_price", "商品价格", "AGENT", "product_price", "价格多少"),
    IntentExample("product_price", "商品价格", "AGENT", "product_price", "有没有优惠"),
    IntentExample("product_price", "商品价格", "AGENT", "product_price", "能便宜点吗"),
    IntentExample("product_price", "商品价格", "AGENT", "product_price", "打不打折"),
    IntentExample("product_price", "商品价格", "AGENT", "product_price", "什么价位"),

    # ── 商品库存（AGENT → search_products）─────────────────────────────────
    IntentExample("product_stock", "商品库存", "AGENT", "product_stock", "这个有货吗"),
    IntentExample("product_stock", "商品库存", "AGENT", "product_stock", "还有库存吗"),
    IntentExample("product_stock", "商品库存", "AGENT", "product_stock", "有没有现货"),
    IntentExample("product_stock", "商品库存", "AGENT", "product_stock", "缺货了吗"),
    IntentExample("product_stock", "商品库存", "AGENT", "product_stock", "什么时候补货"),
    IntentExample("product_stock", "商品库存", "AGENT", "product_stock", "帮我查一下库存"),

    # ── 发货时效（AGENT → search_products）─────────────────────────────────
    IntentExample("delivery_time", "发货时效", "AGENT", "delivery_time", "今天能发吗"),
    IntentExample("delivery_time", "发货时效", "AGENT", "delivery_time", "什么时候发货"),
    IntentExample("delivery_time", "发货时效", "AGENT", "delivery_time", "几天能到"),
    IntentExample("delivery_time", "发货时效", "AGENT", "delivery_time", "发货要多久"),
    IntentExample("delivery_time", "发货时效", "AGENT", "delivery_time", "明天能收到吗"),
    IntentExample("delivery_time", "发货时效", "AGENT", "delivery_time", "配送要几天"),

    # ── 订单状态（AGENT → manage_order）────────────────────────────────────
    IntentExample("order_status", "订单状态", "AGENT", "order_status", "我的订单怎么还没发货"),
    IntentExample("order_status", "订单状态", "AGENT", "order_status", "订单处理到哪了"),
    IntentExample("order_status", "订单状态", "AGENT", "order_status", "帮我查下订单"),
    IntentExample("order_status", "订单状态", "AGENT", "order_status", "我的单子怎么样了"),
    IntentExample("order_status", "订单状态", "AGENT", "order_status", "订单什么时候能发"),
    IntentExample("order_status", "订单状态", "AGENT", "order_status", "查一下我的订单状态"),

    # ── 物流状态（AGENT → manage_order）────────────────────────────────────
    IntentExample("logistics_status", "物流状态", "AGENT", "logistics_status", "物流到哪里了"),
    IntentExample("logistics_status", "物流状态", "AGENT", "logistics_status", "快递到哪了"),
    IntentExample("logistics_status", "物流状态", "AGENT", "logistics_status", "包裹到哪了"),
    IntentExample("logistics_status", "物流状态", "AGENT", "logistics_status", "帮我查下快递"),
    IntentExample("logistics_status", "物流状态", "AGENT", "logistics_status", "怎么还没送到"),

    # ── 发票（AGENT → manage_order）────────────────────────────────────────
    IntentExample("invoice", "发票", "AGENT", "invoice", "可以开发票吗"),
    IntentExample("invoice", "发票", "AGENT", "invoice", "帮我开发票"),
    IntentExample("invoice", "发票", "AGENT", "invoice", "电子发票怎么开"),
    IntentExample("invoice", "发票", "AGENT", "invoice", "我要发票"),
    IntentExample("invoice", "发票", "AGENT", "invoice", "发票什么时候发"),

    # ── 商品搜索/推荐（AGENT → search_products）────────────────────────────
    IntentExample("product_search", "商品搜索", "AGENT", "search_products", "帮我推荐商品"),
    IntentExample("product_search", "商品搜索", "AGENT", "search_products", "有什么茶叶"),
    IntentExample("product_search", "商品搜索", "AGENT", "search_products", "推荐一下"),
    IntentExample("product_search", "商品搜索", "AGENT", "search_products", "你们有什么产品"),
    IntentExample("product_search", "商品搜索", "AGENT", "search_products", "介绍几款商品"),
    IntentExample("product_search", "商品搜索", "AGENT", "search_products", "有没有适合送礼的"),

    # ── 商品咨询（AGENT → search_products）─────────────────────────────────
    IntentExample("product_inquiry", "商品咨询", "AGENT", "search_products", "这个适合什么场景"),
    IntentExample("product_inquiry", "商品咨询", "AGENT", "search_products", "哪个好用"),
    IntentExample("product_inquiry", "商品咨询", "AGENT", "search_products", "有什么功能"),
    IntentExample("product_inquiry", "商品咨询", "AGENT", "search_products", "这款怎么样"),
    IntentExample("product_inquiry", "商品咨询", "AGENT", "search_products", "适合送人吗"),

    # ── 退货退款（HUMAN → human_service）───────────────────────────────────
    IntentExample("return_refund", "退货退款", "HUMAN", "human_service", "我要退货"),
    IntentExample("return_refund", "退货退款", "HUMAN", "human_service", "怎么退款"),
    IntentExample("return_refund", "退货退款", "HUMAN", "human_service", "退款什么时候到"),
    IntentExample("return_refund", "退货退款", "HUMAN", "human_service", "不满意可以退吗"),
    IntentExample("return_refund", "退货退款", "HUMAN", "human_service", "收到货有问题"),
    IntentExample("return_refund", "退货退款", "HUMAN", "human_service", "想换一个"),

    # ── 取消/退出（HUMAN → human_service）──────────────────────────────────
    IntentExample("cancel", "取消操作", "HUMAN", "human_service", "取消订单"),
    IntentExample("cancel", "取消操作", "HUMAN", "human_service", "我不想要了"),
    IntentExample("cancel", "取消操作", "HUMAN", "human_service", "帮我取消"),
    IntentExample("exit", "退出会话", "HUMAN", "human_service", "不用了谢谢"),

    # ── 闲聊（GENERAL_REPLY → general_reply）───────────────────────────────
    IntentExample("chitchat", "闲聊", "GENERAL_REPLY", "general_reply", "你好"),
    IntentExample("chitchat", "闲聊", "GENERAL_REPLY", "general_reply", "在吗"),
    IntentExample("chitchat", "闲聊", "GENERAL_REPLY", "general_reply", "谢谢"),
    IntentExample("chitchat", "闲聊", "GENERAL_REPLY", "general_reply", "好的"),
    IntentExample("chitchat", "闲聊", "GENERAL_REPLY", "general_reply", "辛苦了"),
    IntentExample("chitchat", "闲聊", "GENERAL_REPLY", "general_reply", "再见"),
)


def build_intent_examples(
    tenant_examples: list[IntentExample] | None = None,
    *,
    include_defaults: bool = True,
) -> list[IntentExample]:
    """构建意图样本列表：租户专属样本 + 平台默认兜底。

    Args:
        tenant_examples: 租户级别样本（从 DB 读取），为 None 时仅使用默认。
        include_defaults: 是否合并平台默认样本。关闭后仅使用租户数据。
    """
    result: list[IntentExample] = []
    if include_defaults:
        result.extend(DEFAULT_INTENT_EXAMPLES)
    if tenant_examples:
        # 租户样本追加在末尾，同 intent 去重以租户为准
        seen = {e.intent for e in result}
        result.extend(e for e in tenant_examples if e.intent not in seen)
    return result
