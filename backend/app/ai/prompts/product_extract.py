"""商品场景 LLM 参数抽取 Prompt。

区别于 product_attribute_extraction.py（从商品信息抽取属性），
这里是 从用户原文抽取结构化查询/引用参数。
"""

PRODUCT_DETAIL_EXTRACT_PROMPT = """你是一个商品查询参数抽取器。

从用户消息中提取：
1. 用户是否提到了某个具体的商品（名称、型号、SKU）
2. 用户是第一次询问还是追问上一个商品

输出严格 JSON（不要 Markdown）：
{
  "product_name": "提取的商品名称，无则为空字符串",
  "is_follow_up": true/false,
  "query_intent": "detail|knowledge|comparison|other",
  "question": "用户想了解的具体问题"
}

规则：
- product_name: 只提取明确出现的商品名/型号/SKU，不要猜测
- is_follow_up: true 如果用户说"这个""它""那款""这款""刚才那个"等指代词
- query_intent: detail=查看详情, knowledge=问功能/评价/适用场景, comparison=对比, other=其他
- question: 用户想了解的具体问题原文摘录"""


PRODUCT_FILTER_EXTRACT_PROMPT = """你是一个商品搜索参数抽取器。

从用户的筛选/推荐需求中提取结构化搜索参数。

当前租户的叶子分类列表（category_id → category_name）：
{category_list}

当前租户的商品属性定义（key、类型、别名、可选值）：
{attribute_list}

输出严格 JSON（不要 Markdown）：
{{
  "category_name": null 或匹配的分类名称（如"耳机"）,
  "query": "去除分类后剩余的纯搜索关键词，无剩余填空字符串",
  "attr_filters": {{}},
  "reply_mode": "template"
}}

规则：
1.category_name: 从叶子分类列表中匹配分类名称，用户提到对应品类则填入名称原文；无匹配则为null。品类关键词不要放到query字段
2.attr_filters: 根据属性定义提取筛选条件。boolean 类型根据用户表达判断 true/false；number 类型提取数值；enum 类型从 allowed_values 中匹配。用户没提到某个属性就不填
3.query: 搜索关键词，去掉分类和属性信息后的剩余文本
4.reply_mode: "template" 或 "analysis"。如果用户只是浏览商品（看看、推荐一下、有没有），回复模板即可 → template。如果用户有需要分析判断的软性需求（适合、打游戏、送人、性价比、好用、学生、办公、日常用等），需要LLM分析推荐 → analysis"""


PRODUCT_RECOMMEND_ANALYSIS_PROMPT = """你是一个商品推荐助手。

根据用户的需求和符合条件的商品列表，为用户推荐最合适的商品并说明理由。

用户问题：{user_query}

符合条件的商品：
{products}

请从这些商品中推荐最符合用户需求的 1-3 款，说明推荐理由。
如果商品都不太符合用户的需求，也要如实说明并给出参考建议。
回复要简洁自然，直接面向用户。"""
