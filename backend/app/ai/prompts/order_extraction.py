"""订单实体抽取 prompt（备用）。

当前订单场景以规则为主，此 prompt 仅在规则无法覆盖的复杂表达时使用。
"""

from __future__ import annotations

from app.ai.types import Messages

SYSTEM_PROMPT = """你是一个订单实体抽取器。从用户消息中抽取订单相关信息，输出 JSON。

输出格式：
{
    "order_number": "用户提到的订单号，没有则为 null",
    "status": "用户提到的订单状态，没有则为 null（可选值：draft/pending_customer_confirm/customer_confirmed/agent_confirmed/shipped/signed/cancelled）",
    "time_ref": "时间范围（可选：today/yesterday/this_month/recent），没有则为 null",
    "product_name": "用户提到的商品名，没有则为 null"
}

规则：
1. 只抽取用户直接提到的信息，不推断不联想
2. 状态词映射为英文枚举值
3. 未提供的信息字段填 null"""


def build_order_extraction_messages(content: str) -> Messages:
    """构建订单实体抽取消息。"""
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": content[:2000]},
    ]
