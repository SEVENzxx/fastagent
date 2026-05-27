"""IntentRecognitionPipeline：10 层意图识别总编排。

注意：`intent/` 目录里的文件名按字母排序显示，不代表执行顺序。
真实执行顺序看 `PIPELINE_STEPS` 和 `recognize()` / `_recognize_segment()`。
"""

from __future__ import annotations

import logging
import time

from app.services.ai.config.intent_config import DEFAULT_INTENT_CONFIG, IntentRecognitionConfig
from app.services.ai.intent.ambiguity import AmbiguityDetector
from app.services.ai.intent.context_state import ContextStateResolver
from app.services.ai.intent.fusion_scorer import IntentFusionScorer
from app.services.ai.intent.keyword_entity import KeywordEntityExtractor
from app.services.ai.intent.llm_judge import CompletionCallable, LLMIntentJudge
from app.services.ai.intent.normalizer import TextNormalizer
from app.services.ai.intent.router import IntentRouter
from app.services.ai.intent.rule_matcher import RuleMatcher
from app.services.ai.intent.segmenter import MessageSegmenter
from app.services.ai.intent.types import IntentCandidate, IntentHit, IntentResult, PendingIntentState, RoutedIntent
from app.services.ai.intent.vector_retriever import VectorIntentRetriever, VectorProvider

logger = logging.getLogger(__name__)

PIPELINE_STEPS: tuple[tuple[int, str, str], ...] = (
    (1, "TextNormalizer", "文本清洗，输出 normalized_text"),
    (2, "RuleMatcher", "强规则匹配，高风险 should_stop 可直接返回"),
    (3, "KeywordEntityExtractor", "抽取关键词/实体/intent_boosts/risk_flags"),
    (4, "ContextStateResolver", "处理上一轮 pending intent 的槽位补全"),
    (5, "MessageSegmenter", "多问题拆句，每个 segment 独立识别"),
    (6, "VectorIntentRetriever", "向量候选召回，只返回 IntentCandidate"),
    (7, "IntentFusionScorer", "融合 vector_score + keyword_boost + context_boost"),
    (8, "AmbiguityDetector", "判断高置信、低置信、歧义、无候选"),
    (9, "LLMIntentJudge", "仅在需要时从候选中精判"),
    (10, "IntentRouter", "IntentResult 映射 RoutedIntent"),
)


class IntentRecognitionPipeline:
    """企业客服分层意图识别流水线。"""

    def __init__(
        self,
        config: IntentRecognitionConfig | None = None,
        vector_provider: VectorProvider | None = None,
        llm_completion: CompletionCallable | None = None,
    ) -> None:
        self.config = config or DEFAULT_INTENT_CONFIG
        self.normalizer = TextNormalizer()
        self.rule_matcher = RuleMatcher(self.config)
        self.keyword_entity = KeywordEntityExtractor(self.config)
        self.context_state = ContextStateResolver(self.config)
        self.segmenter = MessageSegmenter()
        self.vector_retriever = VectorIntentRetriever(self.config, provider=vector_provider)
        self.fusion_scorer = IntentFusionScorer(self.config)
        self.ambiguity_detector = AmbiguityDetector(self.config)
        self.llm_judge = LLMIntentJudge(llm_completion)
        self.router = IntentRouter(self.config)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def recognize(
        self,
        text: str | None,
        *,
        pending_state: PendingIntentState | None = None,
    ) -> IntentResult:
        """识别意图，返回 IntentResult。"""
        started = time.perf_counter()
        original = str(text or "")
        normalized = self.normalizer.normalize(original)
        logger.info("意图识别流水线开始：text_len=%s normalized_len=%s", len(original), len(normalized))

        # Step 2: RuleMatcher — 强规则提前退出
        strong_hit = self.rule_matcher.match(normalized)
        if strong_hit is not None and strong_hit.route in {"HUMAN", "SILENT"}:
            logger.info(
                "意图识别命中强规则并提前结束：intent=%s route=%s confidence=%.4f elapsed_ms=%.0f",
                strong_hit.intent, strong_hit.route, strong_hit.confidence,
                (time.perf_counter() - started) * 1000,
            )
            return self._early_result(original, normalized, strong_hit, "rule_matcher")

        # Step 3: KeywordEntityExtractor
        signals = self.keyword_entity.extract(normalized)

        # Step 4: ContextStateResolver — 槽位补全
        context_hit = self.context_state.resolve(normalized, signals, pending_state)
        if context_hit is not None:
            logger.info(
                "意图识别通过待补槽状态完成：intent=%s route=%s confidence=%.4f elapsed_ms=%.0f",
                context_hit.intent, context_hit.route, context_hit.confidence,
                (time.perf_counter() - started) * 1000,
            )
            return self._early_result(original, normalized, context_hit, "context_state")

        # Step 5: MessageSegmenter
        segments = self.segmenter.segment(
            normalized, enable_multi_intent=self.config.enable_multi_intent,
        )
        if not segments:
            logger.info("意图识别返回未知意图：reason=empty_segments elapsed_ms=%.0f",
                        (time.perf_counter() - started) * 1000)
            return self._unknown_result(original, normalized, "空文本或无法拆分")

        logger.info("意图识别拆句完成：segments=%s", len(segments))

        # Step 6-9: 每个 segment 独立识别
        hits: list[IntentHit] = []
        for segment in segments:
            hits.append(await self._recognize_segment(segment, normalized, signals))

        # Step 10 在 recognize_and_route() 中调用
        primary_hit = max(hits, key=lambda item: item.confidence) if hits else None
        candidates = [c for hit in hits for c in hit.candidates]
        result = IntentResult(
            original_text=original,
            normalized_text=normalized,
            primary_intent=primary_hit.intent if primary_hit else "unknown_intent",
            confidence=primary_hit.confidence if primary_hit else 0.0,
            hits=hits,
            candidates=candidates,
            is_multi_intent=len([h for h in hits if h.intent != "unknown_intent"]) > 1,
            need_clarification=any(h.ambiguous for h in hits),
            source=self._source_for_hits(hits),
            reason="多意图识别完成" if len(hits) > 1 else (primary_hit.reason if primary_hit else "无候选"),
        )
        logger.info(
            "意图识别流水线完成：primary_intent=%s confidence=%.4f hits=%s candidates=%s "
            "multi=%s clarify=%s source=%s elapsed_ms=%.0f",
            result.primary_intent, result.confidence, len(result.hits), len(result.candidates),
            result.is_multi_intent, result.need_clarification, result.source,
            (time.perf_counter() - started) * 1000,
        )
        return result

    async def recognize_and_route(
        self,
        text: str | None,
        *,
        pending_state: PendingIntentState | None = None,
    ) -> RoutedIntent:
        """识别并路由，返回 RoutedIntent。"""
        result = await self.recognize(text, pending_state=pending_state)
        routed = self.router.route(result)
        logger.info(
            "意图路由完成：primary_intent=%s route=%s skill=%s confidence=%.4f hits=%s",
            routed.primary_intent, routed.route, routed.skill, routed.confidence, len(routed.hits),
        )
        return routed

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _recognize_segment(
        self, segment: str, full_text: str, signals,
    ) -> IntentHit:
        """Step 6-9：单个 segment 的意图识别。"""

        # Step 6: VectorIntentRetriever
        vector_candidates = await self.vector_retriever.retrieve(segment)

        # Step 7: IntentFusionScorer → list[IntentCandidate]
        fused = self.fusion_scorer.score(
            vector_candidates, signals, segment=segment, full_text=full_text,
        )

        # Step 8: AmbiguityDetector → (top, is_ambiguous, need_llm, need_clarification, reason)
        top, is_ambiguous, need_llm, need_clarification, amb_reason = (
            self.ambiguity_detector.detect(fused)
        )
        logger.info(
            "意图片段打分完成：segment_len=%s candidates=%s selected=%s confidence=%.4f ambiguous=%s need_llm=%s",
            len(segment), len(fused), top.intent, top.score, is_ambiguous, need_llm,
        )

        # Step 9: LLMIntentJudge → (primary_intent, secondary, need_clarification, reason) | None
        if need_llm:
            judged = await self.llm_judge.judge(segment, fused)
            if judged is not None:
                primary_intent, _, _, judge_reason = judged
                selected = next((c for c in fused if c.intent == primary_intent), top)
                return self._make_hit(segment, selected, fused, False, judge_reason)

        return self._make_hit(segment, top, fused, is_ambiguous, amb_reason)

    def _make_hit(
        self,
        segment: str,
        candidate: IntentCandidate,
        candidates: list[IntentCandidate],
        ambiguous: bool,
        reason: str | None,
    ) -> IntentHit:
        """从候选构造 IntentHit。"""
        route = self.config.route_for(candidate.intent)
        return IntentHit(
            segment=segment,
            intent=candidate.intent,
            label=candidate.label,
            confidence=candidate.score,
            route=route.route,
            skill=route.skill,
            candidates=candidates,
            ambiguous=ambiguous,
            reason=reason,
        )

    def _early_result(
        self, original: str, normalized: str, hit: IntentHit, source: str,
    ) -> IntentResult:
        """构造提前退出的 IntentResult。"""
        return IntentResult(
            original_text=original,
            normalized_text=normalized,
            primary_intent=hit.intent,
            confidence=hit.confidence,
            hits=[hit],
            candidates=hit.candidates,
            is_multi_intent=False,
            need_clarification=False,
            source=source,
            reason=hit.reason,
        )

    def _unknown_result(self, original: str, normalized: str, reason: str) -> IntentResult:
        route = self.config.route_for("unknown_intent")
        hit = IntentHit(
            segment=normalized,
            intent="unknown_intent",
            label=self.config.label_for("unknown_intent"),
            confidence=0.0,
            route=route.route,
            skill=route.skill,
            candidates=[],
            ambiguous=False,
            reason=reason,
        )
        return IntentResult(
            original_text=original,
            normalized_text=normalized,
            primary_intent="unknown_intent",
            confidence=0.0,
            hits=[hit],
            candidates=[],
            is_multi_intent=False,
            need_clarification=True,
            source="unknown",
            reason=reason,
        )

    def _source_for_hits(self, hits: list[IntentHit]) -> str:
        if any(h.ambiguous for h in hits):
            return "ambiguous"
        if any(h.candidates for h in hits):
            return "fusion"
        return "unknown"
