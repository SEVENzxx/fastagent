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

注意：只输出叶子分类（末端分类）的名称。如果用户提到的品类名精确匹配某个叶子分类，填入 category_name；如果匹配多个叶子分类（如"电脑"匹配"笔记本电脑"和"台式机/一体机"），填入 category_names 数组；无精确匹配则为null。

当前租户的商品属性定义（key、类型、别名、可选值）：
{attribute_list}

输出严格 JSON（不要 Markdown）：
{{
  "category_name": null 或叶子分类名称,
  "category_names": [],
  "query": "去除分类后剩余的纯搜索关键词，无剩余填空字符串",
  "attr_filters": {{}},
  "reply_mode": "template"
}}

规则：
1.category_name/category_names: 从叶子分类列表中精确匹配。用户提到对应品类则填入名称原文；匹配到多个叶子时用 category_names 数组；无完全匹配则为null/null[]。品类关键词不要放到query字段
2.attr_filters: 根据属性定义提取筛选条件。boolean 类型根据用户表达判断 true/false；number 类型提取数值；enum 类型从 allowed_values 中匹配。用户必须明确提到某属性值（如"i7处理器"、"RTX 4090"、"16寸"、"黑色"）才填入。仅从使用场景推断（如"打游戏"、"办公"、"送人"、"性价比"、"学生"）不填入具体属性值，应留空由后续 analysis 步骤处理
3.query: 搜索关键词。如果分类已匹配且剩余文本仅为请求语气词（推荐/推荐一下/看看/有什么/有没有/找/帮我/我想看/浏览等），query填空字符串
4.reply_mode: "template" 或 "analysis"。
   "template": 用户只是浏览/翻看商品（推荐一下、看看、有什么、有没有、随便看看等），无需LLM分析，直接模板展示
   "analysis": 用户有需要分析判断的软性需求（适合、打游戏、送人、性价比、好用、学生、办公、日常用等），需要LLM分析推荐"""


PRODUCT_RECOMMEND_ANALYSIS_PROMPT = """你是一个商品推荐助手。

根据用户的需求和符合条件的商品列表，为用户推荐最合适的商品并说明理由。

用户问题：{user_query}

符合条件的商品：
{products}

请输出严格 JSON（不要 Markdown），格式如下：
{{
  "recommended_ids": [1, 3, 5],
  "recommendation_reply": "面向用户的推荐回复"
}}

规则：
- recommended_ids: 从上方商品列表中选出最符合用户需求的 1-3 款的序号（行号），不要编造不存在的序号，如果没有特别合适的推荐则回空数组
- recommendation_reply: 用 1.2.3 重新编号列出推荐商品并附简短理由，格式为「1. 商品名 - ¥价格 - 理由」，不要使用原始行号。直接面向用户，语气自然"""
