"""HumanReplyBuilder — 转人工场景回复构建器。

Handler 不直接拼接回复字符串。
"""

from __future__ import annotations


class HumanReplyBuilder:
    """转人工回复构建器。"""

    @staticmethod
    def transfer() -> str:
        """转人工话术。"""
        return "正在为您转接人工客服，请稍候…"
