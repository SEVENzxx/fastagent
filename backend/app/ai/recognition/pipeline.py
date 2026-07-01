"""RecognitionPipeline — 场景识别主流程。

流程：
  1. 文本归一化
  2. 上下文优先：短确认 + 草稿订单 → order.confirm
  3. 无上下文歧义词澄清：确认/取消等 → template.clarify（不走向量/LLM）
  4. 强规则匹配 → HUMAN / SILENT 直接返回
  5. 场景识别（向量 + LLM）

输出：ScenarioDecision(scenario_id, confidence, entities)
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from app.ai.recognition.normalizer import TextNormalizer
from app.ai.recognition.vector_adapter import IntentVectorAdapter
from app.ai.llm.gateway import LLMUseCase, complete
from app.ai.prompts.scene_recognition import (
    RECOGNITION_DIRECT_PROMPT,
    RECOGNITION_SYSTEM_PROMPT,
)
from app.ai.recognition.rule_matcher import RuleMatcher
from app.ai.recognition.types import ScenarioDecision
from app.common.constants.config import HIGH_CONFIDENCE_GAP, HIGH_CONFIDENCE_SCORE, SCENE_RECOGNITION_MAX_TOKENS

logger = logging.getLogger(__name__)

# 短确认 + 草稿订单 → 走 order.confirm，优先于 SILENT 规则
_CONFIRM_SIGNALS: frozenset[str] = frozenset({
    "好的", "确认", "可以", "没问题", "行", "就这个", "下单", "OK", "ok",
})

# 依赖上下文的歧义词 — 无业务上下文时不走向量/LLM，直接引导澄清
_AMBIGUOUS_KEYWORDS: frozenset[str] = frozenset({
    "确认", "取消", "不取消", "算了", "不要了",
})


class RecognitionPipeline:
    """场景识别主流程。

    与旧 GlobalIntentEngine 并存，输出 ScenarioDecision。
    规则路径不触发 LLM 和 Vector。
    """

    def __init__(self) -> None:
        self._normalizer = TextNormalizer()
        self._rule_matcher = RuleMatcher()
        self._vector = IntentVectorAdapter()

    @staticmethod
    def _ctx_get(context: Any, key: str, default: Any = None) -> Any:
        """统一读取上下文字段，兼容 dict / Pydantic / object。"""
        if context is None:
            return default
        if isinstance(context, dict):
            return context.get(key, default)
        return getattr(context, key, default)

    async def recognize(
        self,
        message: str,
        context: Any | None = None,
    ) -> ScenarioDecision:
        """识别用户消息的场景。"""
        started = time.perf_counter()
        normalized = self._normalizer.normalize(str(message or ""))
        tenant_id = self._ctx_get(context, "tenant_id", 0)

        # ── 1: 上下文优先（短确认 + 草稿订单 → order.confirm）──
        priority = self._check_scene_priority(normalized, context, started)
        if priority is not None:
            return priority

        # ── 1.5: 无上下文歧义词澄清（确认/取消等关键词无对应流程时引导，不走向量/LLM）──
        clarify = self._check_ambiguous_without_context(normalized, context, started)
        if clarify is not None:
            return clarify

        # ── 2: 强规则匹配（不触发 LLM / Vector）──
        rule_hit = self._check_rule_match(normalized, started)
        if rule_hit is not None:
            return rule_hit

        # ── 3: 场景识别（向量 + LLM）──
        candidates = await self._vector.retrieve(normalized, tenant_id=tenant_id)

        if not candidates:
            decision = await self._decide_without_candidates(normalized, {}, started)
        else:
            decision = await self._decide_with_candidates(normalized, candidates, {}, started)

        return decision

    # ──────────────────────────────────────
    # 决策子步骤
    # ──────────────────────────────────────

    def _check_scene_priority(
        self, normalized: str, context: Any, started: float,
    ) -> ScenarioDecision | None:
        """上下文优先：短确认 + 草稿订单 → order.confirm。"""
        if context and normalized.strip() in _CONFIRM_SIGNALS and self._ctx_get(context, "draft_order_id"):
            elapsed = (time.perf_counter() - started) * 1000
            logger.info(
                "【场景识别】上下文优先 order.confirm tenant=%s elapsed=%.0fms",
                self._ctx_get(context, "tenant_id", 0), elapsed,
            )
            return ScenarioDecision(
                scenario_id="order.confirm",
                confidence=0.92,
                entities={"reason": "短确认词+草稿订单"},
            )
        return None

    def _check_ambiguous_without_context(
        self, normalized: str, context: Any, started: float,
    ) -> ScenarioDecision | None:
        """无业务上下文时，确认/取消类歧义词不走向量/LLM，直接引导澄清。

        有 draft_order_id / active_order_id 说明有进行中的流程，不拦截。
        """
        if context and (
            self._ctx_get(context, "draft_order_id")
            or self._ctx_get(context, "active_order_id")
        ):
            return None

        stripped = normalized.strip()
        if stripped not in _AMBIGUOUS_KEYWORDS:
            return None

        elapsed = (time.perf_counter() - started) * 1000
        logger.info(
            "【场景识别】歧义词无上下文，引导澄清 keyword=%s elapsed=%.0fms",
            stripped, elapsed,
        )
        return ScenarioDecision(
            scenario_id="template.clarify",
            confidence=0.8,
            entities={"reason": f"歧义词「{stripped}」无业务上下文，引导用户表达真实意图"},
        )

    def _check_rule_match(self, normalized: str, started: float) -> ScenarioDecision | None:
        """强规则匹配。"""
        rule_result = self._rule_matcher.match(normalized)
        if rule_result is None:
            return None
        elapsed = (time.perf_counter() - started) * 1000
        logger.info(
            "【场景识别】强规则命中 scenario=%s confidence=%.2f tenant=%s elapsed=%.0fms",
            rule_result.scenario_id, rule_result.confidence,
            self._ctx_get(None, "tenant_id", 0), elapsed,
        )
        return rule_result

    async def _decide_without_candidates(
        self, normalized: str, entities: dict, started: float,
    ) -> ScenarioDecision:
        """无向量候选 → LLM 直接判决或兜底。"""
        llm_result = await self._llm_judge(normalized, [])
        if llm_result is not None:
            llm_result.entities.update(entities)
            elapsed = (time.perf_counter() - started) * 1000
            logger.info(
                "【场景识别】LLM 直接判决 scenario=%s confidence=%.2f elapsed=%.0fms",
                llm_result.scenario_id, llm_result.confidence, elapsed,
            )
            return llm_result
        elapsed = (time.perf_counter() - started) * 1000
        logger.warning("【场景识别】完全兜底 elapsed=%.0fms", elapsed)
        return ScenarioDecision(
            scenario_id="template.fallback",
            confidence=0.0,
            entities=entities,
        )

    async def _decide_with_candidates(
        self, normalized: str, candidates: list, entities: dict, started: float,
    ) -> ScenarioDecision:
        """有向量候选 → 高置信短路 / LLM 精判 / 降级。"""
        top = candidates[0]
        if self._high_confidence_eligible(top, candidates):
            scenario_id = top.scenario_id
            elapsed = (time.perf_counter() - started) * 1000
            logger.info(
                "【场景识别】向量高置信 scenario=%s confidence=%.2f tenant=%s elapsed=%.0fms",
                scenario_id, top.score,
                self._ctx_get(None, "tenant_id", 0), elapsed,
            )
            return ScenarioDecision(
                scenario_id=scenario_id,
                confidence=top.score,
                entities=entities,
            )

        llm_result = await self._llm_judge(normalized, candidates[:5])
        if llm_result is not None:
            llm_result.entities.update(entities)
            elapsed = (time.perf_counter() - started) * 1000
            logger.info(
                "【场景识别】LLM 判决 scenario=%s confidence=%.2f elapsed=%.0fms",
                llm_result.scenario_id, llm_result.confidence, elapsed,
            )
            return llm_result

        top = max(candidates, key=lambda c: c.score)
        scenario_id = top.scenario_id
        elapsed = (time.perf_counter() - started) * 1000
        logger.warning(
            "【场景识别】LLM 降级兜底 scenario=%s confidence=%.2f elapsed=%.0fms",
            scenario_id, top.score, elapsed,
        )
        return ScenarioDecision(
            scenario_id=scenario_id,
            confidence=top.score,
            entities=entities,
        )

    # ──────────────────────────────────────
    # 内部方法
    # ──────────────────────────────────────

    @staticmethod
    def _high_confidence_eligible(top: Any, candidates: list[Any]) -> bool:
        """高置信候选检查：同集群或分数明显领先 且 scenario_id 映射不歧义。"""
        # 歧义 scenario_id 不走高置信短路，交给 LLM 判断
        ambiguous_scenarios = {"product.detail", "product.compare", "template.farewell", "template.fallback"}
        if top.scenario_id in ambiguous_scenarios:
            return False

        top_k = min(3, len(candidates))
        all_same_scenario = all(
            c.scenario_id == top.scenario_id and c.skill == top.skill
            for c in candidates[:top_k]
        )
        second = candidates[1] if len(candidates) > 1 else None
        gap = top.score - (second.score if second else 0)
        return top.score >= HIGH_CONFIDENCE_SCORE and (
            gap >= HIGH_CONFIDENCE_GAP or all_same_scenario
        )

    async def _llm_judge(
        self,
        text: str,
        candidates: list[Any],
    ) -> ScenarioDecision | None:
        """调用 LLM 做场景判决。"""
        candidate_list = [
            {"scenario_id": c.scenario_id, "label": c.label, "score": c.score, "skill": c.skill.value}
            for c in candidates
        ]

        if not candidate_list:
            messages = [
                {"role": "system", "content": RECOGNITION_DIRECT_PROMPT},
                {"role": "user", "content": f"用户消息：{text}"},
            ]
        else:
            user_prompt = (
                f"用户消息：{text}\n"
                f"候选场景：{json.dumps(candidate_list, ensure_ascii=False)}"
            )
            messages = [
                {"role": "system", "content": RECOGNITION_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ]

        try:
            raw = await complete(
                LLMUseCase.INTENT_JUDGE,
                messages,
                max_tokens=SCENE_RECOGNITION_MAX_TOKENS,
                temperature=0.1,
            )
            content = (raw or "").strip()
            if content.startswith("```"):
                content = content.split("\n", 1)[-1]
                if content.endswith("```"):
                    content = content[:-3]
                content = content.strip()

            data = json.loads(content)
            return ScenarioDecision(
                scenario_id=data.get("scenario_id", "template.fallback"),
                confidence=float(data.get("confidence", 0.5)),
                entities={"reason": data.get("reason", "")},
            )
        except (json.JSONDecodeError, ValueError, TypeError) as exc:
            logger.warning("LLM 场景判决失败（格式错误）：%s", exc)
            return None
        except Exception as exc:
            logger.warning("LLM 场景判决失败（服务错误）：%s", exc)
            return None


