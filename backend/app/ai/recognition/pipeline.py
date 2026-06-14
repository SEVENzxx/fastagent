"""RecognitionPipeline — 场景识别主流程。

流程：
  1. 文本归一化
  2. 上下文优先：短确认 + 草稿订单 → order.confirm
  3. 强规则匹配 → HUMAN / SILENT 直接返回
  4. 粗实体抽取
  5. 向量召回候选
  6. LLM 判决（有候选或从零判断）
  7. 兜底

输出：ScenarioDecision(scenario_id, confidence, entities)
旧 GlobalIntentEngine 不受影响，两者并存。
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
from app.ai.recognition.entity_extractors import extract_all
from app.ai.recognition.rule_matcher import RuleMatcher
from app.ai.recognition.types import ScenarioDecision
from app.ai.settings import HIGH_CONFIDENCE_GAP, HIGH_CONFIDENCE_SCORE

logger = logging.getLogger(__name__)

# 短确认 + 草稿订单 → 走 order.confirm，优先于 SILENT 规则
_CONFIRM_SIGNALS: frozenset[str] = frozenset({
    "好的", "确认", "可以", "没问题", "行", "就这个", "下单", "OK", "ok",
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
        """识别用户消息的场景。

        Args:
            message: 用户消息原文
            context: 当前会话上下文（可选）

        Returns:
            ScenarioDecision
        """
        started = time.perf_counter()
        normalized = self._normalizer.normalize(str(message or ""))

        # ── 1: 上下文优先（短确认 + 草稿订单 → order.confirm）──
        # 这一步必须在规则匹配之前，否则"好的"会被 SILENT 规则截获
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

        # ── 2: 强规则匹配（不触发 LLM / Vector）──
        rule_result = self._rule_matcher.match(normalized)
        if rule_result is not None:
            elapsed = (time.perf_counter() - started) * 1000
            logger.info(
                "【场景识别】强规则命中 scenario=%s confidence=%.2f tenant=%s elapsed=%.0fms",
                rule_result.scenario_id, rule_result.confidence,
                self._ctx_get(context, "tenant_id", 0), elapsed,
            )
            return rule_result

        # ── 3: 粗实体抽取（提示，非最终业务 ID）──
        entities = extract_all(normalized)

        # ── 4: 向量召回候选 ──
        candidates = await self._vector.retrieve(normalized, tenant_id=self._ctx_get(context, "tenant_id", 0))

        # ── 5: 无向量候选 → LLM 直接判决 ──
        if not candidates:
            llm_result = await self._llm_judge(normalized, [])
            if llm_result is not None:
                llm_result.entities.update(entities)
                elapsed = (time.perf_counter() - started) * 1000
                logger.info(
                    "【场景识别】LLM 直接判决 scenario=%s confidence=%.2f elapsed=%.0fms",
                    llm_result.scenario_id, llm_result.confidence, elapsed,
                )
                return llm_result
            # LLM 失败 → 兜底
            elapsed = (time.perf_counter() - started) * 1000
            logger.warning(
                "【场景识别】完全兜底 elapsed=%.0fms", elapsed,
            )
            return ScenarioDecision(
                scenario_id="template.fallback",
                confidence=0.0,
                entities=entities,
            )

        # ── 6: 高置信候选 → 同 intent 集群或最高分明显领先则直接返回 ──
        top = candidates[0]
        if self._high_confidence_eligible(top, candidates):
            scenario_id = self._map_intent_to_scenario(top.intent, top.skill.value)
            elapsed = (time.perf_counter() - started) * 1000
            logger.info(
                "【场景识别】向量高置信 scenario=%s confidence=%.2f tenant=%s elapsed=%.0fms",
                scenario_id, top.score,
                self._ctx_get(context, "tenant_id", 0), elapsed,
            )
            return ScenarioDecision(
                scenario_id=scenario_id,
                confidence=top.score,
                entities=entities,
            )

        # ── 7: LLM 精判（有候选）──
        llm_result = await self._llm_judge(normalized, candidates[:5])
        if llm_result is not None:
            llm_result.entities.update(entities)
            elapsed = (time.perf_counter() - started) * 1000
            logger.info(
                "【场景识别】LLM 判决 scenario=%s confidence=%.2f elapsed=%.0fms",
                llm_result.scenario_id, llm_result.confidence, elapsed,
            )
            return llm_result

        # ── 8: LLM 失败 → 取最高分候选 ──
        top = max(candidates, key=lambda c: c.score)
        scenario_id = self._map_intent_to_scenario(top.intent, top.skill.value)
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
        """高置信候选检查：同集群或分数明显领先 且 intent 映射不歧义。"""
        # 歧义 intent 不走高置信短路，交给 LLM 判断
        ambiguous_intents = {"product_search", "product_inquiry", "chitchat", "unknown_intent"}
        if top.intent in ambiguous_intents:
            return False

        top_k = min(3, len(candidates))
        all_same_intent = all(
            c.intent == top.intent and c.skill == top.skill
            for c in candidates[:top_k]
        )
        second = candidates[1] if len(candidates) > 1 else None
        gap = top.score - (second.score if second else 0)
        return top.score >= HIGH_CONFIDENCE_SCORE and (
            gap >= HIGH_CONFIDENCE_GAP or all_same_intent
        )

    async def _llm_judge(
        self,
        text: str,
        candidates: list[Any],
    ) -> ScenarioDecision | None:
        """调用 LLM 做场景判决。"""
        candidate_list = [
            {"intent": c.intent, "label": c.label, "score": c.score, "skill": c.skill.value}
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
                max_tokens=200,
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

    @staticmethod
    def _map_intent_to_scenario(intent: str, skill: str) -> str:
        """旧 intent 名 → 新 scenario_id 映射。

        歧义 intent（product_search, product_inquiry 等）不在这里映射，
        由 LLM 判决步骤处理。
        """
        _INTENT_TO_SCENARIO: dict[str, str] = {
            # HUMAN
            "transfer_request": "human.transfer",
            "complaint": "human.transfer",
            "abuse": "human.transfer",
            "return_refund": "human.transfer",
            # PRODUCT （只映射无歧义的）
            "product_price": "product.filter_search",
            "product_stock": "product.sku_query",
            # ORDER
            "place_order": "order.create",
            "confirm_order": "order.confirm",
            "order_status": "order.list",
            "logistics_status": "order.shipping_status",
            # RAG / KNOWLEDGE
            "delivery_time": "knowledge.policy",
            "promotion_inquiry": "knowledge.policy",
            "discount_request": "knowledge.policy",
            "invoice": "knowledge.qa",
            "payment_inquiry": "knowledge.qa",
            # MEMORY
            "save_preference": "memory.save",
            # TEMPLATE
            "silent_empty": "template.silent",
            "silent_noise": "template.silent",
            "silent_ack": "template.confirmation",
            "silent_thanks": "template.farewell",
        }
        return _INTENT_TO_SCENARIO.get(intent, "template.fallback")
