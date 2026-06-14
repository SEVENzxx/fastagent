"""TemplateReplyBuilder — 模板场景回复构建器。

Handler 不直接拼接回复字符串。
"""

from __future__ import annotations


class TemplateReplyBuilder:
    """模板回复构建器。

    模板映射集中管理，Handler 不散落文案。
    """

    _TEMPLATES: dict[str, str] = {
        "template.greeting": "您好！有什么可以帮您的吗？",
        "template.confirmation": "好的，已为您处理。",
        "template.farewell": "不客气，祝您购物愉快！",
        "template.silent": "...",
        "template.fallback": "抱歉，我没有理解您的意思，请重新描述一下？",
    }

    _DEFAULT: str = _TEMPLATES["template.fallback"]

    @staticmethod
    def for_scenario(scenario_id: str) -> str:
        """根据 scenario_id 返回对应模板回复。"""
        return TemplateReplyBuilder._TEMPLATES.get(scenario_id, TemplateReplyBuilder._DEFAULT)
