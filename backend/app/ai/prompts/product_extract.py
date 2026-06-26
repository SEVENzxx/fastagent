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
  "attr_filters": {{}}
}}

规则：
1.category_name: 从叶子分类列表中匹配分类名称，用户提到对应品类则填入名称原文；无匹配则为null。品类关键词不要放到query字段
2.attr_filters: 根据属性定义提取筛选条件。boolean 类型根据用户表达判断 true/false；number 类型提取数值；enum 类型从 allowed_values 中匹配。用户没提到某个属性就不填
3.query: 搜索关键词，去掉分类和属性信息后的剩余文本"""
