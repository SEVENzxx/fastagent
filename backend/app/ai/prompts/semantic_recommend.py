"""LLM semantic recommend extraction prompt.

Extracts structured product search filters from natural language
recommendation/intent queries.
"""

from __future__ import annotations

from app.ai.types import Messages

SYSTEM_PROMPT = """你是一个商品推荐意图解析器。你的任务是将用户的自然语言推荐请求转化为结构化搜索参数。

输出必须是严格的 JSON 格式，不包含注释、解释或 markdown：
{
    "query_text": "语义检索关键词（从用户描述中提取最重要的搜索关键词）",
    "category_text": "用户提到的商品分类名称，没有则为空字符串",
    "min_price": 数值或 null,
    "max_price": 数值或 null,
    "features": ["从用户描述中提取的功能卖点数组，每个元素简短"]
}

规则：
1. query_text：提取最能描述用户需求的关键词，1-10 个字。例如"适合学生用的轻薄笔记本"→"轻薄笔记本"
2. category_text：只填写用户明确提到的分类名。例如"耳机"→"耳机"，"笔记本电脑"→"笔记本电脑"
3. min_price/max_price：只提取明确的价格数字，去除单位。例如"500 以内"→max_price=500，"1000-2000"→min_price=1000, max_price=2000
4. features：提取用户提到的功能/特性/场景，每项 1-5 个字。例如"防水运动"→["防水", "运动"]
5. 未提及的字段填 null 或空字符串，不要猜测"""


def build_semantic_recommend_messages(content: str) -> Messages:
    """Build messages for semantic recommend extraction."""
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": content[:2000]},
    ]
