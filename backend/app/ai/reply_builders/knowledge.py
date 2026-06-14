"""KnowledgeReplyBuilder — 知识场景回复构建器。

所有回复内容在此集中构建，Handler 不直接拼接回复字符串。
"""

from __future__ import annotations

from typing import Any


class KnowledgeReplyBuilder:
    """知识场景回复构建器。"""

    @staticmethod
    def qa_direct(items: list[dict[str, Any]]) -> str:
        """QA 对直接命中时渲染标准答案。

        单条直接返回 answer；多条带编号列表。
        格式与旧 GeneralQAFlow._render_qa_answers 一致。
        """
        if not items:
            return ""
        if len(items) == 1:
            return str(items[0].get("answer") or "").strip()

        parts: list[str] = []
        for index, item in enumerate(items, start=1):
            answer = str(item.get("answer") or "").strip()
            if not answer:
                continue
            question = str(item.get("question") or "").strip()
            prefix = f"{index}. 关于{question}：" if question else f"{index}. "
            parts.append(f"{prefix}\n{answer}")
        return "\n\n".join(parts)

    @staticmethod
    def knowledge_direct(items: list[dict[str, Any]]) -> str:
        """知识分块直接返回（短内容）。"""
        if not items:
            return ""
        parts: list[str] = []
        for item in items:
            content = str(item.get("content") or "").strip()
            if content:
                parts.append(content)
        return "\n\n".join(parts)

    @staticmethod
    def knowledge_summary(
        items: list[dict[str, Any]],
        summary: str,
    ) -> str:
        """LLM 摘要后附加参考来源。"""
        parts = [summary]
        sources = []
        seen_titles: set[str] = set()
        for item in items:
            title = str(item.get("title") or "").strip()
            if title and title not in seen_titles:
                seen_titles.add(title)
                sources.append(title)
        if sources:
            parts.append("参考来源：")
            parts.extend(f"- {s}" for s in sources)
        return "\n\n".join(parts)

    @staticmethod
    def no_knowledge() -> str:
        """无任何知识命中时的回复。"""
        return "未查到相关信息。"
