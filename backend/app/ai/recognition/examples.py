"""意图向量召回样本。

平台默认提供一批通用电商客服意图样本，覆盖全量常用客服场景。
每条样本标注了 scenario_id（场景标识）、label（中文标签）、risk_level（风险等级）。
使用 scenario_id 替代旧 intent_name，与目标 Handler 架构对齐。

索引机制：
  - 通过 VectorSearchService 写入 Qdrant collection `fastagent_intent_samples`
  - tenant_id=0 为平台共享样本，所有租户召回时通用
  - bootstrap 启动时自动索引（幂等 upsert），同时保留首次请求懒加载兜底
  - SCHEMA_VERSION 变更时自动清理旧 point 并重新 upsert

样本设计原则：
  - 每个场景 5-30 条不同表达方式（直接问句、口语化、敬语）
  - 覆盖电商客服高频场景：商品分类、商品搜索、商品详情、下单、订单、物流、发票、售后、闲聊
  - SaaS 通用原则：不包含具体商品品类（耳机、茶叶、衣服等）、属性（防水、续航等）、品牌、型号
  - 具体品类/属性相关应由租户在「自定义意图样本管理」页面自行配置

SCHEMA_VERSION 历史：
  v5: intent → scenario_id 迁移。所有样本改用 scenario_id 替代 intent_name，
      拆分 product_search → catalog/semantic_recommend/filter_search，
      拆分 order_status → list/detail/shipping_status，
      拆分 chitchat → greeting/confirmation/farewell，
      移除 PendingGuard.CANCEL 信号样本，exit → template.farewell。
      skill 和 route 字段移除，risk_level 保留。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

# 样本 schema 版本：变更时 bootstrap 会清理旧版本 point 并重新索引
SCHEMA_VERSION = 6

RiskLevelType = Literal["READ_ONLY", "LOW_RISK_WRITE", "HIGH_RISK_WRITE"]


@dataclass(frozen=True, slots=True)
class IntentExample:
    """意图样本 metadata。

    scenario_id: 场景标识（如 product.catalog, order.list）
    label:        中文展示名称
    risk_level:   操作风险等级
    example_text: 用户实际可能发送的原始问句样本
    """

    scenario_id: str
    label: str
    risk_level: RiskLevelType
    example_text: str
DEFAULT_INTENT_EXAMPLES: tuple[IntentExample, ...] = (

    #  product.catalog — 商品分类浏览
    IntentExample("product.catalog", "商品分类浏览", "READ_ONLY", "你们有什么产品"),
    IntentExample("product.catalog", "商品分类浏览", "READ_ONLY", "你们有什么商品"),
    IntentExample("product.catalog", "商品分类浏览", "READ_ONLY", "公司有什么产品"),
    IntentExample("product.catalog", "商品分类浏览", "READ_ONLY", "有什么卖的"),
    IntentExample("product.catalog", "商品分类浏览", "READ_ONLY", "你们主要卖什么"),
    IntentExample("product.catalog", "商品分类浏览", "READ_ONLY", "给我看看商品"),
    IntentExample("product.catalog", "商品分类浏览", "READ_ONLY", "我想看看商品"),
    IntentExample("product.catalog", "商品分类浏览", "READ_ONLY", "看看你们卖什么"),
    IntentExample("product.catalog", "商品分类浏览", "READ_ONLY", "给我列一下产品"),
    IntentExample("product.catalog", "商品分类浏览", "READ_ONLY", "我想买东西"),
    IntentExample("product.catalog", "商品分类浏览", "READ_ONLY", "想看看有什么可买的"),
    IntentExample("product.catalog", "商品分类浏览", "READ_ONLY", "有什么选择"),
    IntentExample("product.catalog", "商品分类浏览", "READ_ONLY", "给我介绍一下你们的商品"),
    IntentExample("product.catalog", "商品分类浏览", "READ_ONLY", "我想了解一下你们的产品"),
    IntentExample("product.catalog", "商品分类浏览", "READ_ONLY", "你们店里有什么"),
    IntentExample("product.catalog", "商品分类浏览", "READ_ONLY", "有哪些商品可以看"),

    #  product.filter_search — 条件筛选
    IntentExample("product.filter_search", "条件筛选", "READ_ONLY", "有哪些款式"),
    IntentExample("product.filter_search", "条件筛选", "READ_ONLY", "有哪些型号"),
    IntentExample("product.filter_search", "条件筛选", "READ_ONLY", "什么价位"),
    IntentExample("product.filter_search", "条件筛选", "READ_ONLY", "有便宜点的吗"),
    IntentExample("product.filter_search", "条件筛选", "READ_ONLY", "预算低一点有什么推荐"),
    IntentExample("product.filter_search", "条件筛选", "READ_ONLY", "有没有现货"),
    IntentExample("product.filter_search", "条件筛选", "READ_ONLY", "哪些有现货"),
    IntentExample("product.filter_search", "条件筛选", "READ_ONLY", "有什么颜色"),
    IntentExample("product.filter_search", "条件筛选", "READ_ONLY", "有什么尺寸"),
    IntentExample("product.filter_search", "条件筛选", "READ_ONLY", "帮我筛选一下"),
    IntentExample("product.filter_search", "条件筛选", "READ_ONLY", "有没有大尺寸的"),
    IntentExample("product.filter_search", "条件筛选", "READ_ONLY", "找一下这个价位的"),
    IntentExample("product.filter_search", "条件筛选", "READ_ONLY", "有没有其他颜色的"),
    IntentExample("product.filter_search", "条件筛选", "READ_ONLY", "价格最低的有哪些"),
    IntentExample("product.filter_search", "条件筛选", "READ_ONLY", "按条件帮我找找"),
    # 槽位化样本 — 预算/价格/规格/条件泛化
    IntentExample("product.filter_search", "条件筛选", "READ_ONLY", "有没有预算以内的商品推荐"),
    IntentExample("product.filter_search", "条件筛选", "READ_ONLY", "推荐一下预算以内的商品"),
    IntentExample("product.filter_search", "条件筛选", "READ_ONLY", "帮我找价格不超过预算的商品"),
    IntentExample("product.filter_search", "条件筛选", "READ_ONLY", "有没有指定价格以内的商品"),
    IntentExample("product.filter_search", "条件筛选", "READ_ONLY", "预算范围内有哪些商品"),
    IntentExample("product.filter_search", "条件筛选", "READ_ONLY", "这个价位有什么推荐"),
    IntentExample("product.filter_search", "条件筛选", "READ_ONLY", "有没有便宜一点的商品推荐"),
    IntentExample("product.filter_search", "条件筛选", "READ_ONLY", "推荐符合预算的商品"),
    IntentExample("product.filter_search", "条件筛选", "READ_ONLY", "找一下符合条件的商品"),
    IntentExample("product.filter_search", "条件筛选", "READ_ONLY", "有没有满足要求的商品"),
    IntentExample("product.filter_search", "条件筛选", "READ_ONLY", "帮我筛选符合需求的商品"),
    IntentExample("product.filter_search", "条件筛选", "READ_ONLY", "有没有价格合适的商品"),
    IntentExample("product.filter_search", "条件筛选", "READ_ONLY", "有没有性价比高一点的商品"),
    IntentExample("product.filter_search", "条件筛选", "READ_ONLY", "价格低一点的有哪些"),
    IntentExample("product.filter_search", "条件筛选", "READ_ONLY", "有没有符合规格的商品"),
    IntentExample("product.filter_search", "条件筛选", "READ_ONLY", "有没有指定规格的商品"),
    IntentExample("product.filter_search", "条件筛选", "READ_ONLY", "有没有某种配置的商品"),
    IntentExample("product.filter_search", "条件筛选", "READ_ONLY", "按我的要求找一下商品"),
    IntentExample("product.filter_search", "条件筛选", "READ_ONLY", "有没有符合我要求的商品"),
    IntentExample("product.filter_search", "条件筛选", "READ_ONLY", "帮我过滤一下商品"),
    IntentExample("product.filter_search", "条件筛选", "READ_ONLY", "按条件过滤商品"),
    IntentExample("product.filter_search", "条件筛选", "READ_ONLY", "符合要求的商品有哪些"),
    IntentExample("product.filter_search", "条件筛选", "READ_ONLY", "有没有满足条件的商品"),
    IntentExample("product.filter_search", "条件筛选", "READ_ONLY", "找特定条件的商品"),
    IntentExample("product.filter_search", "条件筛选", "READ_ONLY", "我想要某种规格的商品"),
    IntentExample("product.filter_search", "条件筛选", "READ_ONLY", "帮我按预算找商品"),

    #  product.pagination_sort — 翻页与排序
    IntentExample("product.pagination_sort", "翻页排序", "READ_ONLY", "有没有新品"),
    IntentExample("product.pagination_sort", "翻页排序", "READ_ONLY", "最近有什么新品"),
    IntentExample("product.pagination_sort", "翻页排序", "READ_ONLY", "下一页"),
    IntentExample("product.pagination_sort", "翻页排序", "READ_ONLY", "还有没有其他选择"),
    IntentExample("product.pagination_sort", "翻页排序", "READ_ONLY", "按价格排序"),
    IntentExample("product.pagination_sort", "翻页排序", "READ_ONLY", "按销量排序"),
    IntentExample("product.pagination_sort", "翻页排序", "READ_ONLY", "按最新排序"),
    IntentExample("product.pagination_sort", "翻页排序", "READ_ONLY", "只看新品"),
    IntentExample("product.pagination_sort", "翻页排序", "READ_ONLY", "有没有更多款式"),
    IntentExample("product.pagination_sort", "翻页排序", "READ_ONLY", "还有别的吗"),

    # product.semantic_recommend — 智能推荐
    IntentExample("product.semantic_recommend", "智能推荐", "READ_ONLY", "帮我推荐商品"),
    IntentExample("product.semantic_recommend", "智能推荐", "READ_ONLY", "推荐一下"),
    IntentExample("product.semantic_recommend", "智能推荐", "READ_ONLY", "有什么可以推荐的"),
    IntentExample("product.semantic_recommend", "智能推荐", "READ_ONLY", "有没有推荐的"),
    IntentExample("product.semantic_recommend", "智能推荐", "READ_ONLY", "有没有热销款"),
    IntentExample("product.semantic_recommend", "智能推荐", "READ_ONLY", "卖得好的有哪些"),
    IntentExample("product.semantic_recommend", "智能推荐", "READ_ONLY", "有没有适合送礼的"),
    IntentExample("product.semantic_recommend", "智能推荐", "READ_ONLY", "现在主推什么"),
    IntentExample("product.semantic_recommend", "智能推荐", "READ_ONLY", "哪些比较受欢迎"),
    IntentExample("product.semantic_recommend", "智能推荐", "READ_ONLY", "有什么推荐款"),
    IntentExample("product.semantic_recommend", "智能推荐", "READ_ONLY", "哪款更适合我"),
    IntentExample("product.semantic_recommend", "智能推荐", "READ_ONLY", "哪个更推荐"),
    # 槽位化样本 — 选择困难/用途导向/条件推荐
    IntentExample("product.semantic_recommend", "智能推荐", "READ_ONLY", "不知道选哪个好"),
    IntentExample("product.semantic_recommend", "智能推荐", "READ_ONLY", "帮我挑一个"),
    IntentExample("product.semantic_recommend", "智能推荐", "READ_ONLY", "哪款比较适合我"),
    IntentExample("product.semantic_recommend", "智能推荐", "READ_ONLY", "有什么值得推荐的商品"),
    IntentExample("product.semantic_recommend", "智能推荐", "READ_ONLY", "帮我推荐适合我的商品"),
    IntentExample("product.semantic_recommend", "智能推荐", "READ_ONLY", "有没有适合送人的商品"),
    IntentExample("product.semantic_recommend", "智能推荐", "READ_ONLY", "有没有适合日常使用的商品"),
    IntentExample("product.semantic_recommend", "智能推荐", "READ_ONLY", "我不知道买哪个"),
    IntentExample("product.semantic_recommend", "智能推荐", "READ_ONLY", "你帮我看看哪个合适"),
    IntentExample("product.semantic_recommend", "智能推荐", "READ_ONLY", "有什么适合我的商品"),

    #  product.detail — 商品详情
    IntentExample("product.detail", "商品详情", "READ_ONLY", "这个适合什么场景"),
    IntentExample("product.detail", "商品详情", "READ_ONLY", "有什么功能"),
    IntentExample("product.detail", "商品详情", "READ_ONLY", "这款怎么样"),
    IntentExample("product.detail", "商品详情", "READ_ONLY", "适合送人吗"),
    IntentExample("product.detail", "商品详情", "READ_ONLY", "质量怎么样"),
    IntentExample("product.detail", "商品详情", "READ_ONLY", "有什么特点"),
    IntentExample("product.detail", "商品详情", "READ_ONLY", "这个好不好用"),
    IntentExample("product.detail", "商品详情", "READ_ONLY", "这个值得买吗"),
    IntentExample("product.detail", "商品详情", "READ_ONLY", "适合什么人用"),
    IntentExample("product.detail", "商品详情", "READ_ONLY", "这个靠谱吗"),
    IntentExample("product.detail", "商品详情", "READ_ONLY", "有什么卖点"),
    IntentExample("product.detail", "商品详情", "READ_ONLY", "可以介绍一下这个吗"),
    IntentExample("product.detail", "商品详情", "READ_ONLY", "这个有什么优势"),
    IntentExample("product.detail", "商品详情", "READ_ONLY", "这个有什么缺点"),
    IntentExample("product.detail", "商品详情", "READ_ONLY", "这个评价怎么样"),
    IntentExample("product.detail", "商品详情", "READ_ONLY", "这个多少钱"),
    IntentExample("product.detail", "商品详情", "READ_ONLY", "价格多少"),
    IntentExample("product.detail", "商品详情", "READ_ONLY", "卖多少钱"),
    IntentExample("product.detail", "商品详情", "READ_ONLY", "多少钱一个"),
    IntentExample("product.detail", "商品详情", "READ_ONLY", "这个贵不贵"),
    IntentExample("product.detail", "商品详情", "READ_ONLY", "价格怎么算"),
    IntentExample("product.detail", "商品详情", "READ_ONLY", "现在什么价"),
    IntentExample("product.detail", "商品详情", "READ_ONLY", "这个价位多少"),
    IntentExample("product.detail", "商品详情", "READ_ONLY", "最低多少钱"),
    IntentExample("product.detail", "商品详情", "READ_ONLY", "报个价"),
    IntentExample("product.detail", "商品详情", "READ_ONLY", "大概多少钱"),
    IntentExample("product.detail", "商品详情", "READ_ONLY", "费用多少"),
    IntentExample("product.detail", "商品详情", "READ_ONLY", "这个有货吗"),
    IntentExample("product.detail", "商品详情", "READ_ONLY", "还有库存吗"),
    IntentExample("product.detail", "商品详情", "READ_ONLY", "缺货了吗"),
    IntentExample("product.detail", "商品详情", "READ_ONLY", "什么时候补货"),
    IntentExample("product.detail", "商品详情", "READ_ONLY", "帮我查一下库存"),
    IntentExample("product.detail", "商品详情", "READ_ONLY", "现在能买到吗"),
    IntentExample("product.detail", "商品详情", "READ_ONLY", "还有吗"),
    IntentExample("product.detail", "商品详情", "READ_ONLY", "有现成的吗"),
    IntentExample("product.detail", "商品详情", "READ_ONLY", "现在有没有"),
    IntentExample("product.detail", "商品详情", "READ_ONLY", "库存够吗"),
    IntentExample("product.detail", "商品详情", "READ_ONLY", "这个还能下单吗"),
    IntentExample("product.detail", "商品详情", "READ_ONLY", "还有多少库存"),
    IntentExample("product.detail", "商品详情", "READ_ONLY", "现在有货不"),
    IntentExample("product.detail", "商品详情", "READ_ONLY", "现在还能买吗"),
    IntentExample("product.detail", "商品详情", "READ_ONLY", "还能买吗"),
    IntentExample("product.detail", "商品详情", "READ_ONLY", "是否有库存"),
    IntentExample("product.detail", "商品详情", "READ_ONLY", "有可售的吗"),

    #  product.compare — 商品对比
    IntentExample("product.compare", "商品对比", "READ_ONLY", "哪个好用"),
    IntentExample("product.compare", "商品对比", "READ_ONLY", "有什么区别"),
    IntentExample("product.compare", "商品对比", "READ_ONLY", "和另一款有什么区别"),
    IntentExample("product.compare", "商品对比", "READ_ONLY", "这几个怎么选"),
    IntentExample("product.compare", "商品对比", "READ_ONLY", "哪个性价比高"),
    IntentExample("product.compare", "商品对比", "READ_ONLY", "这款和那款区别大吗"),

    #  product.attribute_query — 属性查询
    IntentExample("product.attribute_query", "属性查询", "READ_ONLY", "参数是什么"),
    IntentExample("product.attribute_query", "属性查询", "READ_ONLY", "规格是什么"),

    #  product.sku_query — SKU 属性查询
    IntentExample("product.sku_query", "SKU 查询", "READ_ONLY", "有红色的吗"),
    IntentExample("product.sku_query", "SKU 查询", "READ_ONLY", "有没有黑色的"),
    IntentExample("product.sku_query", "SKU 查询", "READ_ONLY", "有 256G 的吗"),
    IntentExample("product.sku_query", "SKU 查询", "READ_ONLY", "有大容量的吗"),
    IntentExample("product.sku_query", "SKU 查询", "READ_ONLY", "这个有别的颜色吗"),
    IntentExample("product.sku_query", "SKU 查询", "READ_ONLY", "这款有蓝色的吗"),
    IntentExample("product.sku_query", "SKU 查询", "READ_ONLY", "有没有其他规格"),
    IntentExample("product.sku_query", "SKU 查询", "READ_ONLY", "有什么配置可选"),
    IntentExample("product.sku_query", "SKU 查询", "READ_ONLY", "这款有别的尺寸吗"),
    IntentExample("product.sku_query", "SKU 查询", "READ_ONLY", "支持什么规格"),

    #  order.list — 订单列表
    IntentExample("order.list", "订单列表", "READ_ONLY", "查订单"),
    IntentExample("order.list", "订单列表", "READ_ONLY", "订单查一下"),
    IntentExample("order.list", "订单列表", "READ_ONLY", "帮我看看订单"),
    IntentExample("order.list", "订单列表", "READ_ONLY", "我买的东西怎么样了"),
    IntentExample("order.list", "订单列表", "READ_ONLY", "我的单子怎么样了"),
    IntentExample("order.list", "订单列表", "READ_ONLY", "看一下我的订单"),
    IntentExample("order.list", "订单列表", "READ_ONLY", "帮我查下订单"),

    #  order.detail — 订单详情
    IntentExample("order.detail", "订单详情", "READ_ONLY", "订单进度怎么样"),
    IntentExample("order.detail", "订单详情", "READ_ONLY", "我的订单到哪一步了"),
    IntentExample("order.detail", "订单详情", "READ_ONLY", "订单有没有处理"),
    IntentExample("order.detail", "订单详情", "READ_ONLY", "订单确认了吗"),
    IntentExample("order.detail", "订单详情", "READ_ONLY", "订单还没动静吗"),
    IntentExample("order.detail", "订单详情", "READ_ONLY", "订单处理到哪了"),
    IntentExample("order.detail", "订单详情", "READ_ONLY", "订单什么时候能处理"),
    IntentExample("order.detail", "订单详情", "READ_ONLY", "帮我查一下订单状态"),
    IntentExample("order.detail", "订单详情", "READ_ONLY", "订单现在什么状态"),
    IntentExample("order.detail", "订单详情", "READ_ONLY", "我的订单有结果了吗"),
    IntentExample("order.detail", "订单详情", "READ_ONLY", "查一下我的订单状态"),

    #  order.shipping_status — 物流状态
    IntentExample("order.shipping_status", "物流状态", "READ_ONLY", "我的订单怎么还没发货"),
    IntentExample("order.shipping_status", "物流状态", "READ_ONLY", "订单什么时候能发"),
    IntentExample("order.shipping_status", "物流状态", "READ_ONLY", "查物流"),
    IntentExample("order.shipping_status", "物流状态", "READ_ONLY", "快递查一下"),
    IntentExample("order.shipping_status", "物流状态", "READ_ONLY", "物流信息有吗"),
    IntentExample("order.shipping_status", "物流状态", "READ_ONLY", "快递单号是多少"),
    IntentExample("order.shipping_status", "物流状态", "READ_ONLY", "什么时候送到"),
    IntentExample("order.shipping_status", "物流状态", "READ_ONLY", "派送了吗"),
    IntentExample("order.shipping_status", "物流状态", "READ_ONLY", "到哪了"),
    IntentExample("order.shipping_status", "物流状态", "READ_ONLY", "物流怎么没更新"),
    IntentExample("order.shipping_status", "物流状态", "READ_ONLY", "快递怎么还没到"),
    IntentExample("order.shipping_status", "物流状态", "READ_ONLY", "包裹到哪了"),
    IntentExample("order.shipping_status", "物流状态", "READ_ONLY", "怎么还没送到"),
    IntentExample("order.shipping_status", "物流状态", "READ_ONLY", "什么时候能收到"),
    IntentExample("order.shipping_status", "物流状态", "READ_ONLY", "能帮我看下物流吗"),
    IntentExample("order.shipping_status", "物流状态", "READ_ONLY", "配送到哪里了"),
    IntentExample("order.shipping_status", "物流状态", "READ_ONLY", "有没有物流信息"),
    IntentExample("order.shipping_status", "物流状态", "READ_ONLY", "发出来了吗"),
    IntentExample("order.shipping_status", "物流状态", "READ_ONLY", "物流到哪里了"),
    IntentExample("order.shipping_status", "物流状态", "READ_ONLY", "快递到哪了"),
    IntentExample("order.shipping_status", "物流状态", "READ_ONLY", "帮我查下快递"),
    IntentExample("order.shipping_status", "物流状态", "READ_ONLY", "帮我查下物流"),

    #  order.filter — 订单筛选
    IntentExample("order.filter", "订单筛选", "READ_ONLY", "未发货的订单有哪些"),
    IntentExample("order.filter", "订单筛选", "READ_ONLY", "待付款订单"),
    IntentExample("order.filter", "订单筛选", "READ_ONLY", "已经完成的订单"),
    IntentExample("order.filter", "订单筛选", "READ_ONLY", "已取消的订单有哪些"),
    IntentExample("order.filter", "订单筛选", "READ_ONLY", "帮我查一下待发货的"),
    IntentExample("order.filter", "订单筛选", "READ_ONLY", "哪些订单还没付款"),
    IntentExample("order.filter", "订单筛选", "READ_ONLY", "看看我退款中的订单"),
    IntentExample("order.filter", "订单筛选", "READ_ONLY", "本周的订单有哪些"),
    IntentExample("order.filter", "订单筛选", "READ_ONLY", "上个月的订单"),
    IntentExample("order.filter", "订单筛选", "READ_ONLY", "待收货的订单"),

    #  order.create — 下单
    IntentExample("order.create", "下单", "HIGH_RISK_WRITE", "我想买"),
    IntentExample("order.create", "下单", "HIGH_RISK_WRITE", "买这个"),
    IntentExample("order.create", "下单", "HIGH_RISK_WRITE", "给我下单"),
    IntentExample("order.create", "下单", "HIGH_RISK_WRITE", "我要这个"),
    IntentExample("order.create", "下单", "HIGH_RISK_WRITE", "就买这个"),
    IntentExample("order.create", "下单", "HIGH_RISK_WRITE", "这个来一个"),
    IntentExample("order.create", "下单", "HIGH_RISK_WRITE", "这款我要了"),
    IntentExample("order.create", "下单", "HIGH_RISK_WRITE", "帮我订一下"),
    IntentExample("order.create", "下单", "HIGH_RISK_WRITE", "加入订单"),
    IntentExample("order.create", "下单", "HIGH_RISK_WRITE", "帮我下一单"),
    IntentExample("order.create", "下单", "HIGH_RISK_WRITE", "我要买这个"),
    IntentExample("order.create", "下单", "HIGH_RISK_WRITE", "订一件"),
    IntentExample("order.create", "下单", "HIGH_RISK_WRITE", "给我来一份"),
    IntentExample("order.create", "下单", "HIGH_RISK_WRITE", "就选这款吧"),
    IntentExample("order.create", "下单", "HIGH_RISK_WRITE", "帮我生成订单"),
    IntentExample("order.create", "下单", "HIGH_RISK_WRITE", "我要下单"),
    IntentExample("order.create", "下单", "HIGH_RISK_WRITE", "可以购买吗"),
    IntentExample("order.create", "下单", "HIGH_RISK_WRITE", "帮我下单"),

    #  order.cancel — 取消订单
    IntentExample("order.cancel", "取消订单", "HIGH_RISK_WRITE", "取消订单"),
    IntentExample("order.cancel", "取消订单", "HIGH_RISK_WRITE", "我不想要了"),
    IntentExample("order.cancel", "取消订单", "HIGH_RISK_WRITE", "帮我取消"),
    IntentExample("order.cancel", "取消订单", "HIGH_RISK_WRITE", "取消一下"),
    IntentExample("order.cancel", "取消订单", "HIGH_RISK_WRITE", "订单取消"),

    #  order.confirm — 确认订单
    IntentExample("order.confirm", "确认订单", "HIGH_RISK_WRITE", "确认"),
    IntentExample("order.confirm", "确认订单", "HIGH_RISK_WRITE", "可以"),
    IntentExample("order.confirm", "确认订单", "HIGH_RISK_WRITE", "没问题"),
    IntentExample("order.confirm", "确认订单", "HIGH_RISK_WRITE", "就这样"),
    IntentExample("order.confirm", "确认订单", "HIGH_RISK_WRITE", "确认提交"),
    IntentExample("order.confirm", "确认订单", "HIGH_RISK_WRITE", "确认购买"),
    IntentExample("order.confirm", "确认订单", "HIGH_RISK_WRITE", "直接下单"),
    IntentExample("order.confirm", "确认订单", "HIGH_RISK_WRITE", "可以下单"),
    IntentExample("order.confirm", "确认订单", "HIGH_RISK_WRITE", "帮我提交"),
    IntentExample("order.confirm", "确认订单", "HIGH_RISK_WRITE", "确认订单"),
    IntentExample("order.confirm", "确认订单", "HIGH_RISK_WRITE", "就这个了"),
    IntentExample("order.confirm", "确认订单", "HIGH_RISK_WRITE", "帮我下了"),
    IntentExample("order.confirm", "确认订单", "HIGH_RISK_WRITE", "没问题下单吧"),
    IntentExample("order.confirm", "确认订单", "HIGH_RISK_WRITE", "确认无误"),
    IntentExample("order.confirm", "确认订单", "HIGH_RISK_WRITE", "提交吧"),
    IntentExample("order.confirm", "确认订单", "HIGH_RISK_WRITE", "可以提交"),

    #  knowledge.policy — 政策咨询
    IntentExample("knowledge.policy", "政策咨询", "READ_ONLY", "能优惠吗"),
    IntentExample("knowledge.policy", "政策咨询", "READ_ONLY", "有没有折扣"),
    IntentExample("knowledge.policy", "政策咨询", "READ_ONLY", "有没有优惠"),
    IntentExample("knowledge.policy", "政策咨询", "READ_ONLY", "价格能不能低一点"),
    IntentExample("knowledge.policy", "政策咨询", "READ_ONLY", "今天能发吗"),
    IntentExample("knowledge.policy", "政策咨询", "READ_ONLY", "什么时候发货"),
    IntentExample("knowledge.policy", "政策咨询", "READ_ONLY", "几天能到"),
    IntentExample("knowledge.policy", "政策咨询", "READ_ONLY", "发货要多久"),
    IntentExample("knowledge.policy", "政策咨询", "READ_ONLY", "明天能收到吗"),
    IntentExample("knowledge.policy", "政策咨询", "READ_ONLY", "配送要几天"),
    IntentExample("knowledge.policy", "政策咨询", "READ_ONLY", "现在下单什么时候能到"),
    IntentExample("knowledge.policy", "政策咨询", "READ_ONLY", "能不能便宜点"),
    IntentExample("knowledge.policy", "政策咨询", "READ_ONLY", "打个折吧"),
    IntentExample("knowledge.policy", "政策咨询", "READ_ONLY", "多买能便宜吗"),
    IntentExample("knowledge.policy", "政策咨询", "READ_ONLY", "能便宜点吗"),
    IntentExample("knowledge.policy", "政策咨询", "READ_ONLY", "打不打折"),
    IntentExample("knowledge.policy", "政策咨询", "READ_ONLY", "有没有优惠活动"),
    IntentExample("knowledge.policy", "政策咨询", "READ_ONLY", "有什么优惠"),
    IntentExample("knowledge.policy", "政策咨询", "READ_ONLY", "有优惠吗"),
    IntentExample("knowledge.policy", "政策咨询", "READ_ONLY", "最近有什么促销"),
    IntentExample("knowledge.policy", "政策咨询", "READ_ONLY", "有没有满减活动"),
    IntentExample("knowledge.policy", "政策咨询", "READ_ONLY", "现在有什么活动"),

    #  knowledge.qa — 知识问答
    IntentExample("knowledge.qa", "知识问答", "READ_ONLY", "支付有哪些方式"),
    IntentExample("knowledge.qa", "知识问答", "READ_ONLY", "支持什么支付"),
    IntentExample("knowledge.qa", "知识问答", "READ_ONLY", "怎么付款"),
    IntentExample("knowledge.qa", "知识问答", "READ_ONLY", "可以微信支付吗"),
    IntentExample("knowledge.qa", "知识问答", "READ_ONLY", "付款方式有哪些"),
    IntentExample("knowledge.qa", "知识问答", "READ_ONLY", "可以开发票吗"),
    IntentExample("knowledge.qa", "知识问答", "READ_ONLY", "帮我开发票"),
    IntentExample("knowledge.qa", "知识问答", "READ_ONLY", "电子发票怎么开"),
    IntentExample("knowledge.qa", "知识问答", "READ_ONLY", "我要发票"),
    IntentExample("knowledge.qa", "知识问答", "READ_ONLY", "发票什么时候发"),
    IntentExample("knowledge.qa", "知识问答", "READ_ONLY", "能开票吗"),

    #  knowledge.product_qa — 商品知识
    IntentExample("knowledge.product_qa", "商品知识", "READ_ONLY", "这个保修多久"),
    IntentExample("knowledge.product_qa", "商品知识", "READ_ONLY", "怎么清洗"),
    IntentExample("knowledge.product_qa", "商品知识", "READ_ONLY", "这个怎么用"),
    IntentExample("knowledge.product_qa", "商品知识", "READ_ONLY", "这款保修期多长时间"),
    IntentExample("knowledge.product_qa", "商品知识", "READ_ONLY", "怎么安装"),
    IntentExample("knowledge.product_qa", "商品知识", "READ_ONLY", "这个耐不耐用"),
    IntentExample("knowledge.product_qa", "商品知识", "READ_ONLY", "使用要注意什么"),
    IntentExample("knowledge.product_qa", "商品知识", "READ_ONLY", "怎么保养"),
    IntentExample("knowledge.product_qa", "商品知识", "READ_ONLY", "这个防水吗"),
    IntentExample("knowledge.product_qa", "商品知识", "READ_ONLY", "这个材质怎么样"),

    #  memory.save — 保存偏好
    IntentExample("memory.save", "保存偏好", "LOW_RISK_WRITE", "帮我记住这个"),
    IntentExample("memory.save", "保存偏好", "LOW_RISK_WRITE", "记一下我喜欢"),
    IntentExample("memory.save", "保存偏好", "LOW_RISK_WRITE", "备注一下"),
    IntentExample("memory.save", "保存偏好", "LOW_RISK_WRITE", "收藏这个"),
    IntentExample("memory.save", "保存偏好", "LOW_RISK_WRITE", "记住我喜欢的颜色"),
    IntentExample("memory.save", "保存偏好", "LOW_RISK_WRITE", "记一下我的要求"),
    IntentExample("memory.save", "保存偏好", "LOW_RISK_WRITE", "帮我备注一下"),
    IntentExample("memory.save", "保存偏好", "LOW_RISK_WRITE", "我不喜欢这个"),
    IntentExample("memory.save", "保存偏好", "LOW_RISK_WRITE", "帮我记着"),

    #  memory.recall — 记忆召回
    IntentExample("memory.recall", "记忆召回", "READ_ONLY", "我喜欢什么颜色"),
    IntentExample("memory.recall", "记忆召回", "READ_ONLY", "我上次买过什么"),
    IntentExample("memory.recall", "记忆召回", "READ_ONLY", "我之前说过什么"),
    IntentExample("memory.recall", "记忆召回", "READ_ONLY", "我有什么偏好"),
    IntentExample("memory.recall", "记忆召回", "READ_ONLY", "帮我查一下我的偏好"),

    #  template.greeting — 问候
    IntentExample("template.greeting", "问候", "READ_ONLY", "你好"),
    IntentExample("template.greeting", "问候", "READ_ONLY", "在吗"),
    IntentExample("template.greeting", "问候", "READ_ONLY", "哈喽"),
    IntentExample("template.greeting", "问候", "READ_ONLY", "您好"),
    IntentExample("template.greeting", "问候", "READ_ONLY", "嗨"),
    IntentExample("template.greeting", "问候", "READ_ONLY", "hello"),
    IntentExample("template.greeting", "问候", "READ_ONLY", "hi"),

    #  template.confirmation — 确认回复
    IntentExample("template.confirmation", "确认回复", "READ_ONLY", "谢谢"),
    IntentExample("template.confirmation", "确认回复", "READ_ONLY", "好的"),
    IntentExample("template.confirmation", "确认回复", "READ_ONLY", "辛苦了"),

    #  template.farewell — 告别
    IntentExample("template.farewell", "告别", "READ_ONLY", "不用了谢谢"),
    IntentExample("template.farewell", "告别", "READ_ONLY", "没事了"),
    IntentExample("template.farewell", "告别", "READ_ONLY", "我先走了"),
    IntentExample("template.farewell", "告别", "READ_ONLY", "先这样吧"),
    IntentExample("template.farewell", "告别", "READ_ONLY", "再见"),

    #  human.transfer — 转人工
    IntentExample("human.transfer", "转人工", "HIGH_RISK_WRITE", "我要退货"),
    IntentExample("human.transfer", "转人工", "HIGH_RISK_WRITE", "我要退款"),
    IntentExample("human.transfer", "转人工", "HIGH_RISK_WRITE", "怎么退款"),
    IntentExample("human.transfer", "转人工", "HIGH_RISK_WRITE", "怎么退货"),
    IntentExample("human.transfer", "转人工", "HIGH_RISK_WRITE", "不满意可以退吗"),
    IntentExample("human.transfer", "转人工", "HIGH_RISK_WRITE", "收到货有问题"),
    IntentExample("human.transfer", "转人工", "HIGH_RISK_WRITE", "想换一个"),
    IntentExample("human.transfer", "转人工", "HIGH_RISK_WRITE", "申请售后"),
    IntentExample("human.transfer", "转人工", "HIGH_RISK_WRITE", "售后怎么处理"),
    IntentExample("human.transfer", "转人工", "HIGH_RISK_WRITE", "可以退换吗"),
    IntentExample("human.transfer", "转人工", "HIGH_RISK_WRITE", "退款什么时候到"),
    IntentExample("human.transfer", "转人工", "HIGH_RISK_WRITE", "退钱"),
    IntentExample("human.transfer", "转人工", "HIGH_RISK_WRITE", "转人工"),
    IntentExample("human.transfer", "转人工", "HIGH_RISK_WRITE", "找人工客服"),
    IntentExample("human.transfer", "转人工", "HIGH_RISK_WRITE", "我要人工"),
    IntentExample("human.transfer", "转人工", "HIGH_RISK_WRITE", "让客服处理"),
    IntentExample("human.transfer", "转人工", "HIGH_RISK_WRITE", "人工处理一下"),
    IntentExample("human.transfer", "转人工", "HIGH_RISK_WRITE", "找真人客服"),
    IntentExample("human.transfer", "转人工", "HIGH_RISK_WRITE", "我要投诉"),
    IntentExample("human.transfer", "转人工", "HIGH_RISK_WRITE", "你们客服呢"),
)


def build_intent_examples(
    tenant_examples: list[IntentExample] | None = None,
    *,
    include_defaults: bool = True,
) -> list[IntentExample]:
    """构建意图样本列表：租户专属样本 + 平台默认兜底。

    合并后按 scenario_id 去重，租户样本优先级高于平台默认。
    """
    result: list[IntentExample] = []
    if include_defaults:
        result.extend(DEFAULT_INTENT_EXAMPLES)
    if tenant_examples:
        seen = {e.scenario_id for e in result}
        result.extend(e for e in tenant_examples if e.scenario_id not in seen)
    return result
