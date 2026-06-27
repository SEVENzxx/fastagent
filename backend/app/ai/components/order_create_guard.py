"""OrderCreateGuard — 下单创建输入校验组件。

只做纯文本规则判断，不调用 DB/Redis/LLM/Skill，避免 Handler 内散落关键字规则。
"""

from __future__ import annotations

import re


class OrderCreateGuard:
    """下单创建流程的输入校验组件。"""

    _START_PREFIXES = ("下单", "购买", "我要买", "我要下单", "帮我买", "买")
    _CONFIRM_PREFIXES = ("确认", "确定", "是", "yes", "y")
    _CANCEL_WORDS = {"取消", "取消下单", "算了", "不要了", "不买了", "no", "n"}
    _BUY_QUANTITY_PATTERN = re.compile(r"^买\d+(个|件|台|双|份|盒|瓶)?$")

    @classmethod
    def looks_like_new_order_start(cls, text: str) -> bool:
        """判断用户输入是否像一次新的下单发起。"""
        normalized = re.sub(r"\s+", "", text.strip().lower())
        if not normalized:
            return False
        if normalized in cls._CANCEL_WORDS:
            return False
        if any(normalized.startswith(prefix) for prefix in cls._CONFIRM_PREFIXES):
            return False
        if cls._BUY_QUANTITY_PATTERN.fullmatch(normalized):
            return False
        return any(normalized.startswith(prefix) for prefix in cls._START_PREFIXES)
