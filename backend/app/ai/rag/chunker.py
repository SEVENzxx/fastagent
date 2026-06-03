"""滑动窗口分块器 — Markdown 标题感知 + 重叠 + token 估算"""

from __future__ import annotations

import re

from app.config import settings


class TextChunker:
    """将长文本切分为语义感知的分块。

    默认参数从 config 读取：
    - chunk_size = 500 字符
    - chunk_overlap = 100 字符
    - min_chunk_size = 100 字符
    """

    def __init__(
        self,
        *,
        chunk_size: int | None = None,
        chunk_overlap: int | None = None,
        min_chunk_size: int | None = None,
    ) -> None:
        self.chunk_size = chunk_size or settings.AI_KNOWLEDGE_CHUNK_SIZE
        self.chunk_overlap = chunk_overlap or settings.AI_KNOWLEDGE_CHUNK_OVERLAP
        self.min_chunk_size = min_chunk_size or settings.AI_KNOWLEDGE_MIN_CHUNK_SIZE

    def chunk(self, text: str, doc_title: str = "") -> list[dict]:
        """切分文本，返回 [{content, chunk_index, token_count, metadata}]。"""
        if not text.strip():
            return []

        sections = self._split_by_headings(text)
        chunks: list[dict] = []
        current_heading = ""

        for heading, body in sections:
            if heading:
                current_heading = heading
            if not body.strip():
                continue
            section_chunks = self._chunk_section(body, current_heading, doc_title)
            chunks.extend(section_chunks)

        # 重新编号，并合并过小的尾部分块。
        chunks = self._merge_small_tail(chunks)

        for idx, chunk in enumerate(chunks):
            chunk["chunk_index"] = idx
            chunk["token_count"] = self._estimate_tokens(chunk["content"])

        return chunks

    def _split_by_headings(self, text: str) -> list[tuple[str, str]]:
        """按 Markdown 标题切分为 (heading, body) 对。"""
        pattern = r"^(#{1,3})\s+(.+)$"
        lines = text.split("\n")
        sections: list[tuple[str, str]] = []
        current_heading = ""
        current_body: list[str] = []

        for line in lines:
            match = re.match(pattern, line.strip())
            if match:
                if current_body:
                    sections.append((current_heading, "\n".join(current_body)))
                level = len(match.group(1))
                current_heading = ("  " * (level - 1)) + match.group(2)
                current_body = []
            else:
                current_body.append(line)

        if current_body:
            sections.append((current_heading, "\n".join(current_body)))
        elif current_heading and not sections:
            sections.append((current_heading, ""))

        if not sections:
            sections.append(("", text))

        return sections

    def _chunk_section(
        self, text: str, heading: str, doc_title: str
    ) -> list[dict]:
        """段内滑动窗口切分。"""
        chunks: list[dict] = []
        start = 0
        text_len = len(text)

        while start < text_len:
            end = min(start + self.chunk_size, text_len)
            content = text[start:end].strip()
            if content:
                chunks.append({
                    "content": (f"## {heading}\n\n" if heading else "") + content,
                    "chunk_index": 0,
                    "token_count": 0,
                    "metadata": {
                        "heading": heading or None,
                        "doc_title": doc_title or None,
                    },
                })
            if end >= text_len:
                break
            start = end - self.chunk_overlap

        return chunks

    def _merge_small_tail(self, chunks: list[dict]) -> list[dict]:
        """合并过短的尾块到前一块。"""
        if len(chunks) >= 2 and len(chunks[-1]["content"]) < self.min_chunk_size:
            chunks[-2]["content"] += "\n\n" + chunks[-1]["content"]
            chunks.pop()
        return chunks

    def _estimate_tokens(self, text: str) -> int:
        """简易 token 估算：中文 ~1.5 字符/token, 英文 ~4 字符/token。"""
        chinese_chars = sum(1 for c in text if "一" <= c <= "鿿")
        other_chars = len(text) - chinese_chars
        return int(chinese_chars / 1.5 + other_chars / 4)
