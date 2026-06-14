"""意图向量召回样本。

平台默认提供一批通用电商客服意图样本，覆盖全量常用客服场景。
每条样本标注了 intent（意图标识）、label（中文标签）、skill（一级领域路由）、risk_level（风险等级）。

索引机制：
  - 通过 VectorSearchService 写入 Qdrant collection `fastagent_intent_samples`
  - tenant_id=0 为平台共享样本，所有租户召回时通用
  - bootstrap 启动时自动索引（幂等 upsert），同时保留首次请求懒加载兜底
  - SCHEMA_VERSION 变更时自动清理旧 point 并重新 upsert

样本设计原则：
  - 每个意图 5-30 条不同表达方式（直接问句、口语化、敬语）
  - 覆盖电商客服高频场景：商品搜索、商品咨询、询价、库存、下单、订单、物流、发票、售后、闲聊
  - SaaS 通用原则：不包含具体商品品类（耳机、茶叶、衣服等）、属性（防水、续航等）、品牌、型号
  - 具体品类/属性相关应由租户在「自定义意图样本管理」页面自行配置

SCHEMA_VERSION 历史：
  v1: 初始版本 (AGENT/HUMAN/GENERAL_REPLY/SILENT 旧路由)
  v2: 路由迁移为 skill 一级路由，新增 risk_level
  v3: 大规模扩充样本量，移除具体品类词，聚焦 SaaS 通用表达
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

# 样本 schema 版本：变更时 bootstrap 会清理旧版本 point 并重新索引
SCHEMA_VERSION = 4

SkillType = Literal["TEMPLATE", "PRODUCT", "ORDER", "RAG", "MEMORY", "HUMAN", "FALLBACK"]
RiskLevelType = Literal["READ_ONLY", "LOW_RISK_WRITE", "HIGH_RISK_WRITE"]


@dataclass(frozen=True, slots=True)
class IntentExample:
    """标准意图样本 metadata。

    intent:        意图唯一标识
    label:         中文展示名称
    skill:         一级领域路由（PRODUCT / ORDER / RAG / TEMPLATE / HUMAN / FALLBACK）
    risk_level:    操作风险等级
    example_text:  用户实际可能发送的原始问句样本
    route:         旧路由类型（保留兼容，后续版本移除）
    """

    intent: str
    label: str
    skill: SkillType
    risk_level: RiskLevelType
    example_text: str
    route: str = ""  # 旧字段，保留兼容，新代码使用 skill


# ── 平台默认意图样本 ─────────────────────────────────────────────────────────
# tenant_id=0 全局共享，新租户开箱即用。租户可通过管理后台新增/覆盖专属样本。
# 每条 example_text 来自真实电商客服对话场景，确保向量召回的高匹配率。
#
# 重要：禁止在此加入具体商品品类、品牌、型号、属性、行业词。
#       这些应由租户在「自定义意图样本」页面配置。

DEFAULT_INTENT_EXAMPLES: tuple[IntentExample, ...] = (

    # ═════════════════════════════════════════════════════════════════════
    # 商品搜索（PRODUCT / product_search）
    # 用户想浏览、搜索、推荐商品，不涉及具体品类
    # ═════════════════════════════════════════════════════════════════════
    IntentExample("product_search", "商品搜索", "PRODUCT", "READ_ONLY", "你们有什么产品"),
    IntentExample("product_search", "商品搜索", "PRODUCT", "READ_ONLY", "你们有什么商品"),
    IntentExample("product_search", "商品搜索", "PRODUCT", "READ_ONLY", "公司有什么产品"),
    IntentExample("product_search", "商品搜索", "PRODUCT", "READ_ONLY", "有什么卖的"),
    IntentExample("product_search", "商品搜索", "PRODUCT", "READ_ONLY", "你们主要卖什么"),
    IntentExample("product_search", "商品搜索", "PRODUCT", "READ_ONLY", "给我看看商品"),
    IntentExample("product_search", "商品搜索", "PRODUCT", "READ_ONLY", "我想看看商品"),
    IntentExample("product_search", "商品搜索", "PRODUCT", "READ_ONLY", "看看你们卖什么"),
    IntentExample("product_search", "商品搜索", "PRODUCT", "READ_ONLY", "帮我推荐商品"),
    IntentExample("product_search", "商品搜索", "PRODUCT", "READ_ONLY", "推荐一下"),
    IntentExample("product_search", "商品搜索", "PRODUCT", "READ_ONLY", "有什么可以推荐的"),
    IntentExample("product_search", "商品搜索", "PRODUCT", "READ_ONLY", "有没有推荐的"),
    IntentExample("product_search", "商品搜索", "PRODUCT", "READ_ONLY", "有没有热销款"),
    IntentExample("product_search", "商品搜索", "PRODUCT", "READ_ONLY", "卖得好的有哪些"),
    IntentExample("product_search", "商品搜索", "PRODUCT", "READ_ONLY", "有哪些款式"),
    IntentExample("product_search", "商品搜索", "PRODUCT", "READ_ONLY", "有哪些型号"),
    IntentExample("product_search", "商品搜索", "PRODUCT", "READ_ONLY", "给我列一下产品"),
    IntentExample("product_search", "商品搜索", "PRODUCT", "READ_ONLY", "我想买东西"),
    IntentExample("product_search", "商品搜索", "PRODUCT", "READ_ONLY", "想看看有什么可买的"),
    IntentExample("product_search", "商品搜索", "PRODUCT", "READ_ONLY", "有什么选择"),
    IntentExample("product_search", "商品搜索", "PRODUCT", "READ_ONLY", "有没有适合送礼的"),
    IntentExample("product_search", "商品搜索", "PRODUCT", "READ_ONLY", "有没有新品"),
    IntentExample("product_search", "商品搜索", "PRODUCT", "READ_ONLY", "最近有什么新品"),
    IntentExample("product_search", "商品搜索", "PRODUCT", "READ_ONLY", "现在主推什么"),
    IntentExample("product_search", "商品搜索", "PRODUCT", "READ_ONLY", "哪些比较受欢迎"),
    IntentExample("product_search", "商品搜索", "PRODUCT", "READ_ONLY", "有什么推荐款"),
    IntentExample("product_search", "商品搜索", "PRODUCT", "READ_ONLY", "给我介绍一下你们的商品"),
    IntentExample("product_search", "商品搜索", "PRODUCT", "READ_ONLY", "我想了解一下你们的产品"),
    IntentExample("product_search", "商品搜索", "PRODUCT", "READ_ONLY", "你们店里有什么"),
    IntentExample("product_search", "商品搜索", "PRODUCT", "READ_ONLY", "有哪些商品可以看"),

    # ═════════════════════════════════════════════════════════════════════
    # 商品咨询（PRODUCT / product_inquiry）
    # 用户想了解商品详细信息，不涉及具体属性词
    # ═════════════════════════════════════════════════════════════════════
    IntentExample("product_inquiry", "商品咨询", "PRODUCT", "READ_ONLY", "这个适合什么场景"),
    IntentExample("product_inquiry", "商品咨询", "PRODUCT", "READ_ONLY", "哪个好用"),
    IntentExample("product_inquiry", "商品咨询", "PRODUCT", "READ_ONLY", "有什么功能"),
    IntentExample("product_inquiry", "商品咨询", "PRODUCT", "READ_ONLY", "这款怎么样"),
    IntentExample("product_inquiry", "商品咨询", "PRODUCT", "READ_ONLY", "适合送人吗"),
    IntentExample("product_inquiry", "商品咨询", "PRODUCT", "READ_ONLY", "质量怎么样"),
    IntentExample("product_inquiry", "商品咨询", "PRODUCT", "READ_ONLY", "有什么特点"),
    IntentExample("product_inquiry", "商品咨询", "PRODUCT", "READ_ONLY", "有什么区别"),
    IntentExample("product_inquiry", "商品咨询", "PRODUCT", "READ_ONLY", "哪款更适合我"),
    IntentExample("product_inquiry", "商品咨询", "PRODUCT", "READ_ONLY", "这个好不好用"),
    IntentExample("product_inquiry", "商品咨询", "PRODUCT", "READ_ONLY", "这个值得买吗"),
    IntentExample("product_inquiry", "商品咨询", "PRODUCT", "READ_ONLY", "参数是什么"),
    IntentExample("product_inquiry", "商品咨询", "PRODUCT", "READ_ONLY", "规格是什么"),
    IntentExample("product_inquiry", "商品咨询", "PRODUCT", "READ_ONLY", "和另一款有什么区别"),
    IntentExample("product_inquiry", "商品咨询", "PRODUCT", "READ_ONLY", "适合什么人用"),
    IntentExample("product_inquiry", "商品咨询", "PRODUCT", "READ_ONLY", "这个靠谱吗"),
    IntentExample("product_inquiry", "商品咨询", "PRODUCT", "READ_ONLY", "有什么卖点"),
    IntentExample("product_inquiry", "商品咨询", "PRODUCT", "READ_ONLY", "这几个怎么选"),
    IntentExample("product_inquiry", "商品咨询", "PRODUCT", "READ_ONLY", "哪个性价比高"),
    IntentExample("product_inquiry", "商品咨询", "PRODUCT", "READ_ONLY", "这款和那款区别大吗"),
    IntentExample("product_inquiry", "商品咨询", "PRODUCT", "READ_ONLY", "可以介绍一下这个吗"),
    IntentExample("product_inquiry", "商品咨询", "PRODUCT", "READ_ONLY", "这个有什么优势"),
    IntentExample("product_inquiry", "商品咨询", "PRODUCT", "READ_ONLY", "这个有什么缺点"),
    IntentExample("product_inquiry", "商品咨询", "PRODUCT", "READ_ONLY", "这个评价怎么样"),
    IntentExample("product_inquiry", "商品咨询", "PRODUCT", "READ_ONLY", "哪个更推荐"),

    # ═════════════════════════════════════════════════════════════════════
    # 商品价格（PRODUCT / product_price）
    # 只写通用价格表达，活动/满减/优惠规则走 promotion_inquiry
    # ═════════════════════════════════════════════════════════════════════
    IntentExample("product_price", "商品价格", "PRODUCT", "READ_ONLY", "这个多少钱"),
    IntentExample("product_price", "商品价格", "PRODUCT", "READ_ONLY", "价格多少"),
    IntentExample("product_price", "商品价格", "PRODUCT", "READ_ONLY", "什么价位"),
    IntentExample("product_price", "商品价格", "PRODUCT", "READ_ONLY", "卖多少钱"),
    IntentExample("product_price", "商品价格", "PRODUCT", "READ_ONLY", "多少钱一个"),
    IntentExample("product_price", "商品价格", "PRODUCT", "READ_ONLY", "这个贵不贵"),
    IntentExample("product_price", "商品价格", "PRODUCT", "READ_ONLY", "有便宜点的吗"),
    IntentExample("product_price", "商品价格", "PRODUCT", "READ_ONLY", "预算低一点有什么推荐"),
    IntentExample("product_price", "商品价格", "PRODUCT", "READ_ONLY", "价格怎么算"),
    IntentExample("product_price", "商品价格", "PRODUCT", "READ_ONLY", "现在什么价"),
    IntentExample("product_price", "商品价格", "PRODUCT", "READ_ONLY", "这个价位多少"),
    IntentExample("product_price", "商品价格", "PRODUCT", "READ_ONLY", "能优惠吗"),
    IntentExample("product_price", "商品价格", "PRODUCT", "READ_ONLY", "最低多少钱"),
    IntentExample("product_price", "商品价格", "PRODUCT", "READ_ONLY", "有没有折扣"),
    IntentExample("product_price", "商品价格", "PRODUCT", "READ_ONLY", "有没有优惠"),
    IntentExample("product_price", "商品价格", "PRODUCT", "READ_ONLY", "报个价"),
    IntentExample("product_price", "商品价格", "PRODUCT", "READ_ONLY", "价格能不能低一点"),
    IntentExample("product_price", "商品价格", "PRODUCT", "READ_ONLY", "大概多少钱"),
    IntentExample("product_price", "商品价格", "PRODUCT", "READ_ONLY", "费用多少"),

    # ═════════════════════════════════════════════════════════════════════
    # 商品库存（PRODUCT / product_stock）
    # 只写通用库存表达
    # ═════════════════════════════════════════════════════════════════════
    IntentExample("product_stock", "商品库存", "PRODUCT", "READ_ONLY", "这个有货吗"),
    IntentExample("product_stock", "商品库存", "PRODUCT", "READ_ONLY", "还有库存吗"),
    IntentExample("product_stock", "商品库存", "PRODUCT", "READ_ONLY", "有没有现货"),
    IntentExample("product_stock", "商品库存", "PRODUCT", "READ_ONLY", "缺货了吗"),
    IntentExample("product_stock", "商品库存", "PRODUCT", "READ_ONLY", "什么时候补货"),
    IntentExample("product_stock", "商品库存", "PRODUCT", "READ_ONLY", "帮我查一下库存"),
    IntentExample("product_stock", "商品库存", "PRODUCT", "READ_ONLY", "现在能买到吗"),
    IntentExample("product_stock", "商品库存", "PRODUCT", "READ_ONLY", "还有吗"),
    IntentExample("product_stock", "商品库存", "PRODUCT", "READ_ONLY", "有现成的吗"),
    IntentExample("product_stock", "商品库存", "PRODUCT", "READ_ONLY", "现在有没有"),
    IntentExample("product_stock", "商品库存", "PRODUCT", "READ_ONLY", "库存够吗"),
    IntentExample("product_stock", "商品库存", "PRODUCT", "READ_ONLY", "这个还能下单吗"),
    IntentExample("product_stock", "商品库存", "PRODUCT", "READ_ONLY", "还有多少库存"),
    IntentExample("product_stock", "商品库存", "PRODUCT", "READ_ONLY", "现在有货不"),
    IntentExample("product_stock", "商品库存", "PRODUCT", "READ_ONLY", "哪些有现货"),
    IntentExample("product_stock", "商品库存", "PRODUCT", "READ_ONLY", "现在还能买吗"),
    IntentExample("product_stock", "商品库存", "PRODUCT", "READ_ONLY", "还能买吗"),
    IntentExample("product_stock", "商品库存", "PRODUCT", "READ_ONLY", "是否有库存"),
    IntentExample("product_stock", "商品库存", "PRODUCT", "READ_ONLY", "有可售的吗"),

    # ═════════════════════════════════════════════════════════════════════
    # 订单状态（ORDER / order_status）
    # ═════════════════════════════════════════════════════════════════════
    IntentExample("order_status", "订单状态", "ORDER", "READ_ONLY", "查订单"),
    IntentExample("order_status", "订单状态", "ORDER", "READ_ONLY", "订单查一下"),
    IntentExample("order_status", "订单状态", "ORDER", "READ_ONLY", "帮我看看订单"),
    IntentExample("order_status", "订单状态", "ORDER", "READ_ONLY", "我买的东西怎么样了"),
    IntentExample("order_status", "订单状态", "ORDER", "READ_ONLY", "订单进度怎么样"),
    IntentExample("order_status", "订单状态", "ORDER", "READ_ONLY", "我的订单到哪一步了"),
    IntentExample("order_status", "订单状态", "ORDER", "READ_ONLY", "订单有没有处理"),
    IntentExample("order_status", "订单状态", "ORDER", "READ_ONLY", "订单确认了吗"),
    IntentExample("order_status", "订单状态", "ORDER", "READ_ONLY", "订单还没动静吗"),
    IntentExample("order_status", "订单状态", "ORDER", "READ_ONLY", "我的单子怎么样了"),
    IntentExample("order_status", "订单状态", "ORDER", "READ_ONLY", "订单处理到哪了"),
    IntentExample("order_status", "订单状态", "ORDER", "READ_ONLY", "订单什么时候能处理"),
    IntentExample("order_status", "订单状态", "ORDER", "READ_ONLY", "帮我查一下订单状态"),
    IntentExample("order_status", "订单状态", "ORDER", "READ_ONLY", "订单现在什么状态"),
    IntentExample("order_status", "订单状态", "ORDER", "READ_ONLY", "看一下我的订单"),
    IntentExample("order_status", "订单状态", "ORDER", "READ_ONLY", "我的订单有结果了吗"),
    IntentExample("order_status", "订单状态", "ORDER", "READ_ONLY", "我的订单怎么还没发货"),
    IntentExample("order_status", "订单状态", "ORDER", "READ_ONLY", "帮我查下订单"),
    IntentExample("order_status", "订单状态", "ORDER", "READ_ONLY", "订单什么时候能发"),
    IntentExample("order_status", "订单状态", "ORDER", "READ_ONLY", "查一下我的订单状态"),

    # ═════════════════════════════════════════════════════════════════════
    # 物流状态（ORDER / logistics_status）
    # ═════════════════════════════════════════════════════════════════════
    IntentExample("logistics_status", "物流状态", "ORDER", "READ_ONLY", "查物流"),
    IntentExample("logistics_status", "物流状态", "ORDER", "READ_ONLY", "快递查一下"),
    IntentExample("logistics_status", "物流状态", "ORDER", "READ_ONLY", "物流信息有吗"),
    IntentExample("logistics_status", "物流状态", "ORDER", "READ_ONLY", "快递单号是多少"),
    IntentExample("logistics_status", "物流状态", "ORDER", "READ_ONLY", "什么时候送到"),
    IntentExample("logistics_status", "物流状态", "ORDER", "READ_ONLY", "派送了吗"),
    IntentExample("logistics_status", "物流状态", "ORDER", "READ_ONLY", "到哪了"),
    IntentExample("logistics_status", "物流状态", "ORDER", "READ_ONLY", "物流怎么没更新"),
    IntentExample("logistics_status", "物流状态", "ORDER", "READ_ONLY", "快递怎么还没到"),
    IntentExample("logistics_status", "物流状态", "ORDER", "READ_ONLY", "包裹到哪了"),
    IntentExample("logistics_status", "物流状态", "ORDER", "READ_ONLY", "怎么还没送到"),
    IntentExample("logistics_status", "物流状态", "ORDER", "READ_ONLY", "什么时候能收到"),
    IntentExample("logistics_status", "物流状态", "ORDER", "READ_ONLY", "能帮我看下物流吗"),
    IntentExample("logistics_status", "物流状态", "ORDER", "READ_ONLY", "配送到哪里了"),
    IntentExample("logistics_status", "物流状态", "ORDER", "READ_ONLY", "有没有物流信息"),
    IntentExample("logistics_status", "物流状态", "ORDER", "READ_ONLY", "发出来了吗"),
    IntentExample("logistics_status", "物流状态", "ORDER", "READ_ONLY", "物流到哪里了"),
    IntentExample("logistics_status", "物流状态", "ORDER", "READ_ONLY", "快递到哪了"),
    IntentExample("logistics_status", "物流状态", "ORDER", "READ_ONLY", "帮我查下快递"),
    IntentExample("logistics_status", "物流状态", "ORDER", "READ_ONLY", "帮我查下物流"),

    # ═════════════════════════════════════════════════════════════════════
    # 下单（ORDER / place_order）
    # ═════════════════════════════════════════════════════════════════════
    IntentExample("place_order", "下单", "ORDER", "HIGH_RISK_WRITE", "我想买"),
    IntentExample("place_order", "下单", "ORDER", "HIGH_RISK_WRITE", "买这个"),
    IntentExample("place_order", "下单", "ORDER", "HIGH_RISK_WRITE", "给我下单"),
    IntentExample("place_order", "下单", "ORDER", "HIGH_RISK_WRITE", "我要这个"),
    IntentExample("place_order", "下单", "ORDER", "HIGH_RISK_WRITE", "就买这个"),
    IntentExample("place_order", "下单", "ORDER", "HIGH_RISK_WRITE", "这个来一个"),
    IntentExample("place_order", "下单", "ORDER", "HIGH_RISK_WRITE", "这款我要了"),
    IntentExample("place_order", "下单", "ORDER", "HIGH_RISK_WRITE", "帮我订一下"),
    IntentExample("place_order", "下单", "ORDER", "HIGH_RISK_WRITE", "加入订单"),
    IntentExample("place_order", "下单", "ORDER", "HIGH_RISK_WRITE", "帮我下一单"),
    IntentExample("place_order", "下单", "ORDER", "HIGH_RISK_WRITE", "我要买这个"),
    IntentExample("place_order", "下单", "ORDER", "HIGH_RISK_WRITE", "订一件"),
    IntentExample("place_order", "下单", "ORDER", "HIGH_RISK_WRITE", "给我来一份"),
    IntentExample("place_order", "下单", "ORDER", "HIGH_RISK_WRITE", "就选这款吧"),
    IntentExample("place_order", "下单", "ORDER", "HIGH_RISK_WRITE", "帮我生成订单"),
    IntentExample("place_order", "下单", "ORDER", "HIGH_RISK_WRITE", "我要下单"),
    IntentExample("place_order", "下单", "ORDER", "HIGH_RISK_WRITE", "可以购买吗"),
    IntentExample("place_order", "下单", "ORDER", "HIGH_RISK_WRITE", "帮我下单"),

    # ═════════════════════════════════════════════════════════════════════
    # 确认订单（ORDER / confirm_order）
    # ═════════════════════════════════════════════════════════════════════
    IntentExample("confirm_order", "确认订单", "ORDER", "HIGH_RISK_WRITE", "确认"),
    IntentExample("confirm_order", "确认订单", "ORDER", "HIGH_RISK_WRITE", "可以"),
    IntentExample("confirm_order", "确认订单", "ORDER", "HIGH_RISK_WRITE", "没问题"),
    IntentExample("confirm_order", "确认订单", "ORDER", "HIGH_RISK_WRITE", "就这样"),
    IntentExample("confirm_order", "确认订单", "ORDER", "HIGH_RISK_WRITE", "确认提交"),
    IntentExample("confirm_order", "确认订单", "ORDER", "HIGH_RISK_WRITE", "确认购买"),
    IntentExample("confirm_order", "确认订单", "ORDER", "HIGH_RISK_WRITE", "直接下单"),
    IntentExample("confirm_order", "确认订单", "ORDER", "HIGH_RISK_WRITE", "可以下单"),
    IntentExample("confirm_order", "确认订单", "ORDER", "HIGH_RISK_WRITE", "帮我提交"),
    IntentExample("confirm_order", "确认订单", "ORDER", "HIGH_RISK_WRITE", "确认订单"),
    IntentExample("confirm_order", "确认订单", "ORDER", "HIGH_RISK_WRITE", "就这个了"),
    IntentExample("confirm_order", "确认订单", "ORDER", "HIGH_RISK_WRITE", "帮我下了"),
    IntentExample("confirm_order", "确认订单", "ORDER", "HIGH_RISK_WRITE", "没问题下单吧"),
    IntentExample("confirm_order", "确认订单", "ORDER", "HIGH_RISK_WRITE", "确认无误"),
    IntentExample("confirm_order", "确认订单", "ORDER", "HIGH_RISK_WRITE", "提交吧"),
    IntentExample("confirm_order", "确认订单", "ORDER", "HIGH_RISK_WRITE", "可以提交"),

    # ═════════════════════════════════════════════════════════════════════
    # 退货退款（HUMAN / return_refund）
    # 强规则优先，向量兜底
    # ═════════════════════════════════════════════════════════════════════
    IntentExample("return_refund", "退货退款", "HUMAN", "HIGH_RISK_WRITE", "我要退货"),
    IntentExample("return_refund", "退货退款", "HUMAN", "HIGH_RISK_WRITE", "我要退款"),
    IntentExample("return_refund", "退货退款", "HUMAN", "HIGH_RISK_WRITE", "怎么退款"),
    IntentExample("return_refund", "退货退款", "HUMAN", "HIGH_RISK_WRITE", "怎么退货"),
    IntentExample("return_refund", "退货退款", "HUMAN", "HIGH_RISK_WRITE", "不满意可以退吗"),
    IntentExample("return_refund", "退货退款", "HUMAN", "HIGH_RISK_WRITE", "收到货有问题"),
    IntentExample("return_refund", "退货退款", "HUMAN", "HIGH_RISK_WRITE", "想换一个"),
    IntentExample("return_refund", "退货退款", "HUMAN", "HIGH_RISK_WRITE", "申请售后"),
    IntentExample("return_refund", "退货退款", "HUMAN", "HIGH_RISK_WRITE", "售后怎么处理"),
    IntentExample("return_refund", "退货退款", "HUMAN", "HIGH_RISK_WRITE", "可以退换吗"),
    IntentExample("return_refund", "退货退款", "HUMAN", "HIGH_RISK_WRITE", "退款什么时候到"),
    IntentExample("return_refund", "退货退款", "HUMAN", "HIGH_RISK_WRITE", "退钱"),

    # ═════════════════════════════════════════════════════════════════════
    # 取消（HUMAN / cancel）
    # 强规则优先，向量兜底
    # ═════════════════════════════════════════════════════════════════════
    IntentExample("cancel", "取消操作", "HUMAN", "HIGH_RISK_WRITE", "取消订单"),
    IntentExample("cancel", "取消操作", "HUMAN", "HIGH_RISK_WRITE", "我不想要了"),
    IntentExample("cancel", "取消操作", "HUMAN", "HIGH_RISK_WRITE", "帮我取消"),
    IntentExample("cancel", "取消操作", "HUMAN", "HIGH_RISK_WRITE", "取消一下"),
    IntentExample("cancel", "取消操作", "HUMAN", "HIGH_RISK_WRITE", "先不要了"),
    IntentExample("cancel", "取消操作", "HUMAN", "HIGH_RISK_WRITE", "不买了"),
    IntentExample("cancel", "取消操作", "HUMAN", "HIGH_RISK_WRITE", "订单取消"),
    IntentExample("cancel", "取消操作", "HUMAN", "HIGH_RISK_WRITE", "取消这次操作"),

    # ═════════════════════════════════════════════════════════════════════
    # 转人工（HUMAN / transfer_request）
    # 强规则优先，向量兜底
    # ═════════════════════════════════════════════════════════════════════
    IntentExample("transfer_request", "转人工", "HUMAN", "HIGH_RISK_WRITE", "转人工"),
    IntentExample("transfer_request", "转人工", "HUMAN", "HIGH_RISK_WRITE", "找人工客服"),
    IntentExample("transfer_request", "转人工", "HUMAN", "HIGH_RISK_WRITE", "我要人工"),
    IntentExample("transfer_request", "转人工", "HUMAN", "HIGH_RISK_WRITE", "让客服处理"),
    IntentExample("transfer_request", "转人工", "HUMAN", "HIGH_RISK_WRITE", "人工处理一下"),
    IntentExample("transfer_request", "转人工", "HUMAN", "HIGH_RISK_WRITE", "找真人客服"),
    IntentExample("transfer_request", "转人工", "HUMAN", "HIGH_RISK_WRITE", "我要投诉"),
    IntentExample("transfer_request", "转人工", "HUMAN", "HIGH_RISK_WRITE", "你们客服呢"),

    # ═════════════════════════════════════════════════════════════════════
    # 闲聊/问候（TEMPLATE / chitchat）
    # ═════════════════════════════════════════════════════════════════════
    IntentExample("chitchat", "闲聊", "TEMPLATE", "READ_ONLY", "你好"),
    IntentExample("chitchat", "闲聊", "TEMPLATE", "READ_ONLY", "在吗"),
    IntentExample("chitchat", "闲聊", "TEMPLATE", "READ_ONLY", "谢谢"),
    IntentExample("chitchat", "闲聊", "TEMPLATE", "READ_ONLY", "好的"),
    IntentExample("chitchat", "闲聊", "TEMPLATE", "READ_ONLY", "辛苦了"),
    IntentExample("chitchat", "闲聊", "TEMPLATE", "READ_ONLY", "再见"),
    IntentExample("chitchat", "闲聊", "TEMPLATE", "READ_ONLY", "哈喽"),
    IntentExample("chitchat", "闲聊", "TEMPLATE", "READ_ONLY", "您好"),
    IntentExample("chitchat", "闲聊", "TEMPLATE", "READ_ONLY", "嗨"),
    IntentExample("chitchat", "闲聊", "TEMPLATE", "READ_ONLY", "hello"),
    IntentExample("chitchat", "闲聊", "TEMPLATE", "READ_ONLY", "hi"),

    # ═════════════════════════════════════════════════════════════════════
    # 退出（HUMAN / exit）
    # ═════════════════════════════════════════════════════════════════════
    IntentExample("exit", "退出会话", "HUMAN", "READ_ONLY", "不用了谢谢"),
    IntentExample("exit", "退出会话", "HUMAN", "READ_ONLY", "没事了"),
    IntentExample("exit", "退出会话", "HUMAN", "READ_ONLY", "我先走了"),
    IntentExample("exit", "退出会话", "HUMAN", "READ_ONLY", "先这样吧"),

    # ═════════════════════════════════════════════════════════════════════
    # 发货时效（RAG / delivery_time）
    # ═════════════════════════════════════════════════════════════════════
    IntentExample("delivery_time", "发货时效", "RAG", "READ_ONLY", "今天能发吗"),
    IntentExample("delivery_time", "发货时效", "RAG", "READ_ONLY", "什么时候发货"),
    IntentExample("delivery_time", "发货时效", "RAG", "READ_ONLY", "几天能到"),
    IntentExample("delivery_time", "发货时效", "RAG", "READ_ONLY", "发货要多久"),
    IntentExample("delivery_time", "发货时效", "RAG", "READ_ONLY", "明天能收到吗"),
    IntentExample("delivery_time", "发货时效", "RAG", "READ_ONLY", "配送要几天"),
    IntentExample("delivery_time", "发货时效", "RAG", "READ_ONLY", "现在下单什么时候能到"),

    # ═════════════════════════════════════════════════════════════════════
    # 议价（RAG / discount_request）
    # ═════════════════════════════════════════════════════════════════════
    IntentExample("discount_request", "议价", "RAG", "READ_ONLY", "能不能便宜点"),
    IntentExample("discount_request", "议价", "RAG", "READ_ONLY", "打个折吧"),
    IntentExample("discount_request", "议价", "RAG", "READ_ONLY", "多买能便宜吗"),
    IntentExample("discount_request", "议价", "RAG", "READ_ONLY", "能便宜点吗"),
    IntentExample("discount_request", "议价", "RAG", "READ_ONLY", "打不打折"),

    # ═════════════════════════════════════════════════════════════════════
    # 优惠活动咨询（RAG / promotion_inquiry）
    # ═════════════════════════════════════════════════════════════════════
    IntentExample("promotion_inquiry", "优惠活动咨询", "RAG", "READ_ONLY", "有没有优惠活动"),
    IntentExample("promotion_inquiry", "优惠活动咨询", "RAG", "READ_ONLY", "有什么优惠"),
    IntentExample("promotion_inquiry", "优惠活动咨询", "RAG", "READ_ONLY", "有优惠吗"),
    IntentExample("promotion_inquiry", "优惠活动咨询", "RAG", "READ_ONLY", "最近有什么促销"),
    IntentExample("promotion_inquiry", "优惠活动咨询", "RAG", "READ_ONLY", "有没有满减活动"),
    IntentExample("promotion_inquiry", "优惠活动咨询", "RAG", "READ_ONLY", "现在有什么活动"),

    # ═════════════════════════════════════════════════════════════════════
    # 支付方式咨询（RAG / payment_inquiry）
    # ═════════════════════════════════════════════════════════════════════
    IntentExample("payment_inquiry", "支付方式咨询", "RAG", "READ_ONLY", "支付有哪些方式"),
    IntentExample("payment_inquiry", "支付方式咨询", "RAG", "READ_ONLY", "支持什么支付"),
    IntentExample("payment_inquiry", "支付方式咨询", "RAG", "READ_ONLY", "怎么付款"),
    IntentExample("payment_inquiry", "支付方式咨询", "RAG", "READ_ONLY", "可以微信支付吗"),
    IntentExample("payment_inquiry", "支付方式咨询", "RAG", "READ_ONLY", "付款方式有哪些"),

    # ═════════════════════════════════════════════════════════════════════
    # 发票（RAG / invoice）
    # ═════════════════════════════════════════════════════════════════════
    IntentExample("invoice", "发票", "RAG", "READ_ONLY", "可以开发票吗"),
    IntentExample("invoice", "发票", "RAG", "READ_ONLY", "帮我开发票"),
    IntentExample("invoice", "发票", "RAG", "READ_ONLY", "电子发票怎么开"),
    IntentExample("invoice", "发票", "RAG", "READ_ONLY", "我要发票"),
    IntentExample("invoice", "发票", "RAG", "READ_ONLY", "发票什么时候发"),
    IntentExample("invoice", "发票", "RAG", "READ_ONLY", "能开票吗"),

    # ═════════════════════════════════════════════════════════════════════
    # 保存偏好（MEMORY / save_preference）
    # ═════════════════════════════════════════════════════════════════════
    IntentExample("save_preference", "保存偏好", "MEMORY", "LOW_RISK_WRITE", "帮我记住这个"),
    IntentExample("save_preference", "保存偏好", "MEMORY", "LOW_RISK_WRITE", "记一下我喜欢"),
    IntentExample("save_preference", "保存偏好", "MEMORY", "LOW_RISK_WRITE", "备注一下"),
    IntentExample("save_preference", "保存偏好", "MEMORY", "LOW_RISK_WRITE", "收藏这个"),
    IntentExample("save_preference", "保存偏好", "MEMORY", "LOW_RISK_WRITE", "记住我喜欢的颜色"),
    IntentExample("save_preference", "保存偏好", "MEMORY", "LOW_RISK_WRITE", "记一下我的要求"),
    IntentExample("save_preference", "保存偏好", "MEMORY", "LOW_RISK_WRITE", "帮我备注一下"),
    IntentExample("save_preference", "保存偏好", "MEMORY", "LOW_RISK_WRITE", "我不喜欢这个"),
    IntentExample("save_preference", "保存偏好", "MEMORY", "LOW_RISK_WRITE", "帮我记着"),
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
