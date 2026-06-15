"""MemoryReplyBuilder — 记忆场景回复构建器。

Handler 不直接拼接回复字符串。
"""

from __future__ import annotations


class MemoryReplyBuilder:
    """记忆场景回复构建器。"""

    @staticmethod
    def saved(items: list[str]) -> str:
        """偏好已保存回复。"""
        if not items:
            return ""
        return f"已帮您记住：{'，'.join(items)}。以后我会按您的偏好来推荐。"

    @staticmethod
    def nothing_saved() -> str:
        """未识别到偏好时的回复。"""
        return "我还没识别到需要记住的具体内容，可以再说清楚一点。"

    @staticmethod
    def error(msg: str | None = None) -> str:
        """保存失败回复。"""
        return msg or "抱歉，保存偏好信息时遇到了问题，请稍后再试。"

    @staticmethod
    def no_text() -> str:
        """缺少文本时的提示。"""
        return "请描述您想记住的信息。"

    @staticmethod
    def no_contact() -> str:
        """缺少客户标识时的提示。"""
        return "请先确认客户身份。"

    @staticmethod
    def recall(items: list[dict]) -> str:
        """记忆召回回复。"""
        if not items:
            return "目前还没有保存关于您的偏好信息。"
        parts = ["我记得关于您的信息："]
        for item in items:
            key = item.get("key", "")
            value = item.get("value", "")
            if key and value:
                parts.append(f"  - {key}：{value}")
        return "\n".join(parts)
