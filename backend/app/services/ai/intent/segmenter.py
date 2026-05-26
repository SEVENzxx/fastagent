"""MessageSegmenter：多问题拆句。"""

from __future__ import annotations

import re


class MessageSegmenter:
    """识别一句话中的多个问题，避免过度拆分短句。"""

    _split_pattern = re.compile(r"[?？!！;；\n]+")

    def segment(self, normalized_text: str, *, enable_multi_intent: bool = True) -> list[str]:
        """拆分消息；短句或关闭多意图时直接返回原文。"""
        text = normalized_text.strip()
        if not text:
            return []
        if not enable_multi_intent:
            return [text]

        pieces = [piece.strip(" ，,。.") for piece in self._split_pattern.split(text)]
        segments = [piece for piece in pieces if piece]
        if len(segments) <= 1:
            return [text]

        # 过短寒暄不独立成任务，保留在后续 context_boost 中即可。
        return [segment for segment in segments if segment not in {"你好", "您好", "谢谢", "再见"}]
