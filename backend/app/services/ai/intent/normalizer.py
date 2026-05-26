"""TextNormalizer：文本清洗。"""

from __future__ import annotations

import re
import unicodedata


class TextNormalizer:
    """只做不改变语义的文本归一化。"""

    def normalize(self, text: str | None) -> str:
        """清洗用户输入文本。"""
        normalized = unicodedata.normalize("NFKC", str(text or ""))
        normalized = normalized.replace("\u200b", "").replace("\ufeff", "")
        normalized = re.sub(r"\s+", " ", normalized)
        return normalized.strip()
