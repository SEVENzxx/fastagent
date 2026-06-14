"""RecognitionPipeline 强规则匹配。

从 intent/config.py 迁移的强规则，输出 ScenarioDecision。
规则路径不触发 LLM 和 Vector。

匹配规则：
  - HUMAN 类规则：子串匹配（"投诉"匹配"我要投诉"）
  - SILENT 类规则：短词精确匹配（"好"不匹配"你好"），长词子串匹配
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.ai.recognition.types import ScenarioDecision

# ── 规则类别 ──
RuleRoute = Literal["HUMAN", "SILENT"]


@dataclass(frozen=True, slots=True)
class StrongRule:
    """强规则 — 关键词命中后直接返回 ScenarioDecision，跳过后续链路。"""
    scenario_id: str
    label: str
    keywords: tuple[str, ...]
    confidence: float = 1.0
    route: RuleRoute = "HUMAN"
    reason: str = ""


# SILENT 规则中，这些短词使用精确匹配（避免"你好"误配"好"）
_SILENT_EXACT: frozenset[str] = frozenset({
    "好", "行", "嗯", "哦", "OK", "ok", "thx",
})


def _match_keywords(text: str, rule: StrongRule) -> bool:
    """按规则类型匹配关键词。"""
    for kw in rule.keywords:
        if rule.route == "SILENT" and kw in _SILENT_EXACT:
            # 短词精确匹配
            if text == kw.lower():
                return True
        else:
            # 子串匹配
            if kw.lower() in text:
                return True
    return False


# ══ 强规则定义 ══
# 按优先级降序排列（HUMAN > SILENT）
_RULES: tuple[StrongRule, ...] = (
    # ══ HUMAN: 转人工/投诉/辱骂/法律威胁 ══
    StrongRule("human.transfer", "转人工",
        ("转人工", "人工客服", "真人客服", "找客服", "给我转人工"),
        confidence=1.0, route="HUMAN", reason="用户明确要求人工介入"),
    StrongRule("human.transfer", "辱骂攻击",
        ("傻逼", "草泥马", "你妈", "操你", "去死", "垃圾东西"),
        confidence=1.0, route="HUMAN", reason="辱骂/攻击性言论"),
    StrongRule("human.transfer", "法律威胁",
        ("起诉", "工商局", "12315", "报警", "律师函", "法院", "消协", "投诉你们公司"),
        confidence=1.0, route="HUMAN", reason="法律/监管投诉"),
    StrongRule("human.transfer", "投诉",
        ("投诉", "举报", "差评", "严重不满", "太差了", "太坑了"),
        confidence=0.98, route="HUMAN", reason="投诉类高风险场景"),
    StrongRule("human.transfer", "删除账号",
        ("删除账号", "注销账号", "销号", "删除账户", "怎么注销"),
        confidence=0.98, route="HUMAN", reason="账号删除需人工确认"),
    StrongRule("human.transfer", "退货退款",
        ("退款", "退货", "我要退", "申请退款", "退钱", "怎么退", "给我退了", "不想要了"),
        confidence=0.96, route="HUMAN", reason="退换货需人工处理"),
    StrongRule("human.transfer", "退订",
        ("退订", "别发了", "不要推送", "别再发了"),
        confidence=0.96, route="HUMAN", reason="退订需人工确认"),
    # ══ SILENT: 确认/感谢/空消息 ══
    StrongRule("template.confirmation", "确认类短句",
        ("好的", "知道了", "嗯", "哦", "收到", "明白", "行", "好", "OK", "ok"),
        confidence=1.0, route="SILENT", reason="纯确认/收到"),
    StrongRule("template.farewell", "感谢类短句",
        ("谢谢", "多谢", "感谢", "谢谢啦", "thx"),
        confidence=1.0, route="SILENT", reason="纯感谢"),
)


class RuleMatcher:
    """强规则匹配器。

    命中 HUMAN/SILENT 规则时直接返回 ScenarioDecision。
    不命中时返回 None，由后续 pipeline 步骤处理。
    """

    def match(self, text: str) -> ScenarioDecision | None:
        """对归一化后的文本进行强规则匹配。"""
        text_lower = text.lower().strip()

        if not text_lower:
            return ScenarioDecision(
                scenario_id="template.silent",
                confidence=1.0,
                entities={"reason": "空消息"},
            )

        for rule in _RULES:
            if _match_keywords(text_lower, rule):
                return ScenarioDecision(
                    scenario_id=rule.scenario_id,
                    confidence=rule.confidence,
                    entities={"reason": rule.reason},
                )

        return None
