"""OrderReferenceResolver — 订单引用解析组件。

纯规则 + 上下文实现，不调用 LLM。
将用户文本中的订单引用解析为具体 order_id 或引用类型。

优先级：显式订单号 → 序号引用 → 状态条件+时间条件（组合）
→ 列表意图 → active_order_id + 指代/物流 → 兜底订单意图

返回 OrderReferenceResult，由 Handler 决定如何查询。
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field

from app.ai.components.status_resolver import StatusResolver
from app.ai.context.session_context import SessionContext


class OrderReferenceResult(BaseModel):
    """订单引用解析结果。"""

    resolved: bool = False                           # 是否唯一确定一个订单
    order_id: int | None = None                      # 确定的订单 ID
    order_number: str | None = None                  # 提取的订单号字符串
    status: str | None = None                        # 单一状态过滤（精确匹配）
    statuses: list[str] = Field(default_factory=list)  # 状态组过滤（多个状态，如未发货组）
    time_ref: str | None = None                      # 时间范围: "today" / "yesterday" / "this_month" / "recent"
    reference_type: str = "unresolved"                # 引用类型: "order_number" / "ordinal" / "status" / "time" / "active" / "recent"
    candidates: list[dict[str, Any]] = Field(default_factory=list)
    need_clarification: bool = False
    reason: str = ""


# ── 正则 ──

# 订单号：8 位以上连续数字（generate_id 输出 14 位左右）
# 使用数字边界而非 \b（中文环境下 \b 因 Unicode \w 包含 CJK 而失效）
_RE_ORDER_NUMBER = re.compile(r"(?<!\d)(\d{8,})(?!\d)")

# 序号引用：第N个（支持"第一个"、"刚才第一个"、"看第一个"等）
_RE_ORDER_ORDINAL = re.compile(r"第([一二两三四五六七八九十\d]+)个")

# 时间关键词 → time_ref
_TIME_KEYWORDS: dict[str, str] = {
    "今天": "today",
    "昨日": "yesterday",
    "昨天": "yesterday",
    "这个月": "this_month",
    "本月": "this_month",
    "最近": "recent",
    "近期": "recent",
}

# 中文数字 → int
_CHINESE_DIGITS: dict[str, int] = {
    "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
    "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
}


def _chinese_to_int(s: str) -> int:
    """中文数字转 int。"""
    if s.isdigit():
        return int(s)
    if "十" in s:
        parts = s.split("十")
        left = _CHINESE_DIGITS.get(parts[0], 1) if parts[0] else 1
        right = _CHINESE_DIGITS.get(parts[1], 0) if len(parts) > 1 and parts[1] else 0
        return left * 10 + right
    return _CHINESE_DIGITS.get(s, 0)


def _extract_order_number(text: str) -> str | None:
    """从文本中提取订单号（8 位以上连续数字）。"""
    m = _RE_ORDER_NUMBER.search(text)
    return m.group(1) if m else None


def _extract_ordinal(text: str) -> int | None:
    """从文本中提取序号（第N个订单）。"""
    m = _RE_ORDER_ORDINAL.search(text)
    if not m:
        return None
    return _chinese_to_int(m.group(1))


def _extract_time_ref(text: str) -> str | None:
    """从文本中提取时间范围。"""
    for keyword, ref in _TIME_KEYWORDS.items():
        if keyword in text:
            return ref
    return None


def _has_order_intent(text: str) -> bool:
    """判断文本是否包含订单查询意图。"""
    t = text.strip()
    if not t:
        return False
    order_words = ("订单", "单号", "下单", "订 ")
    return any(w in t for w in order_words)


def _has_shipping_intent(text: str) -> bool:
    """判断文本是否包含物流/发货查询意图。"""
    t = text.strip()
    if not t:
        return False
    shipping_words = ("发货", "物流", "快递", "配送", "到哪了", "运到哪里", "运输")
    return any(w in t for w in shipping_words)


def _has_deixis_ref(text: str) -> bool:
    """判断文本是否包含指代引用（这个/该/此/当前）。"""
    deixis_words = ("这个", "该", "此", "当前")
    return any(w in text for w in deixis_words)


def _has_list_intent(text: str) -> bool:
    """判断是否为订单列表意图（不引用具体订单）。

    如"查看我的订单"、"查订单"等，即使 active_order_id 存在也不应解析。
    """
    t = text.strip().rstrip("的").rstrip("吧")
    list_patterns = ("查看我的订单", "我的订单", "订单列表", "所有订单", "查订单")
    return t in list_patterns


class OrderReferenceResolver:
    """订单引用解析器。

    纯文本规则解析，不查询数据库。解析结果由 Handler 驱动 DB 查询。
    """

    async def resolve(
        self,
        text: str,
        contact_id: int,
        context: SessionContext,
    ) -> OrderReferenceResult:
        """解析订单引用。

        优先级：
          1. 显式订单号（8 位以上数字）→ order_number，resolved=True
          2. 序号引用 → 从 recent_orders 取对应项
          3. 状态 + 时间组合过滤 → status/statuses + time_ref（组合返回）
          4. 列表意图 → recent，不引用具体订单
          5. active_order_id + 指代引用或物流查询 → resolved
          6. 兜底订单意图 → recent
        """
        _ = contact_id  # 阶段 6 暂不使用，阶段 7 Handler 注入时按 contact 过滤

        if not isinstance(text, str) or not text.strip():
            return OrderReferenceResult(
                reason="输入文本为空",
                reference_type="unresolved",
            )

        # 1. 显式订单号
        order_number = _extract_order_number(text)
        if order_number:
            return OrderReferenceResult(
                resolved=True,
                order_id=int(order_number),
                order_number=order_number,
                reference_type="order_number",
                reason=f"解析到订单号 {order_number}",
            )

        # 2. 序号引用（"第一个订单"）
        ordinal = _extract_ordinal(text)
        if ordinal is not None and context.recent_orders:
            idx = ordinal - 1
            if 0 <= idx < len(context.recent_orders):
                order = context.recent_orders[idx]
                oid = order.get("id") or order.get("order_id")
                return OrderReferenceResult(
                    resolved=True,
                    order_id=int(oid) if oid else None,
                    order_number=str(oid) if oid else None,
                    reference_type="ordinal",
                    candidates=list(context.recent_orders),
                    reason=f"序号引用: 第{ordinal}个订单",
                )

        # 3. 状态条件 + 时间条件（组合过滤，不提前 return）
        status_group = StatusResolver.resolve_group(text)
        single_status = StatusResolver.resolve(text) if not status_group else None
        time_ref = _extract_time_ref(text)

        if status_group or single_status or time_ref:
            kwargs: dict[str, Any] = {
                "resolved": False,
                "reference_type": "status" if (status_group or single_status) else "time",
            }
            reason_parts: list[str] = []
            if status_group:
                kwargs["statuses"] = list(status_group)
                reason_parts.append(f"状态过滤: {status_group}")
            elif single_status:
                kwargs["status"] = single_status
                reason_parts.append(f"订单状态: {single_status}")
            if time_ref:
                kwargs["time_ref"] = time_ref
                reason_parts.append(f"时间范围: {time_ref}")
            kwargs["reason"] = " + ".join(reason_parts)
            return OrderReferenceResult(**kwargs)

        # 5. 列表意图（不引用具体订单，优先于 active 检查）
        if _has_list_intent(text):
            return OrderReferenceResult(
                resolved=False,
                reference_type="recent",
                reason="订单列表意图",
            )

        # 6. 上下文 active_order_id + 指代引用或物流查询
        ctx_order_id = context.active_order_id
        if ctx_order_id:
            if _has_deixis_ref(text) and _has_order_intent(text):
                return OrderReferenceResult(
                    resolved=True,
                    order_id=int(ctx_order_id),
                    order_number=ctx_order_id,
                    reference_type="active",
                    reason=f"指代引用活跃订单 {ctx_order_id}",
                )
            if _has_shipping_intent(text):
                return OrderReferenceResult(
                    resolved=True,
                    order_id=int(ctx_order_id),
                    order_number=ctx_order_id,
                    reference_type="active",
                    reason=f"物流查询引用活跃订单 {ctx_order_id}",
                )

        # 7. 兜底：近期订单意图
        if _has_order_intent(text) or _has_shipping_intent(text):
            return OrderReferenceResult(
                resolved=False,
                reference_type="recent",
                reason="订单查询意图，无精确引用",
            )

        return OrderReferenceResult(
            reason="未识别到订单引用",
            reference_type="unresolved",
        )
