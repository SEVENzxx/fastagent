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
from app.services.ai.intent.types import IntentCandidate, IntentHit, IntentResult, PendingIntentState, ROUTE_HUMAN, ROUTE_SILENT, RoutedIntent
from app.services.ai.intent.vector_retriever import VectorIntentRetriever, VectorProvider

logger = logging.getLogger(__name__)

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
        """识别意图，返回 IntentResult。

        ── 流水线步骤 ──
          1. Normalizer          文本清洗
          2. RuleMatcher         强规则匹配（高风险直接返回）
          3. KeywordEntity       关键词/实体抽取 + intent 加权
          4. ContextState        多轮槽位补全（pending state）
          5. Segmenter           多意图分句
          6. VectorRetriever     向量意图召回
          7. FusionScorer        融合打分
          8. AmbiguityDetector   歧义判断
          9. LLMIntentJudge      仅模糊候选触发精判
         10. IntentRouter        IntentResult → RoutedIntent
        """

        # ── 1: 文本清洗 ──
        started = time.perf_counter()
        original = str(text or "")
        normalized = self.normalizer.normalize(original)

        # ── 2: 强规则匹配（转人工/投诉/辱骂等高优先级规则）──
        strong_hit = self.rule_matcher.match(normalized)
        if strong_hit is not None and strong_hit.route in {ROUTE_HUMAN, ROUTE_SILENT}:
            logger.info(
                "意图识别 — 强规则命中：intent=%s route=%s confidence=%.2f",
                strong_hit.intent, strong_hit.route, strong_hit.confidence,
            )
            return self._early_result(original, normalized, strong_hit, "rule_matcher")

        # ── 3: 关键词/实体抽取 ──
        signals = self.keyword_entity.extract(normalized)

        # ── 4: 多轮槽位补全 ──
        context_hit = self.context_state.resolve(normalized, signals, pending_state)
        if context_hit is not None:
            logger.info(
                "意图识别 — 槽位补全命中：intent=%s route=%s elapsed_ms=%.0f",
                context_hit.intent, context_hit.route,
                (time.perf_counter() - started) * 1000,
            )
            return self._early_result(original, normalized, context_hit, "context_state")

        # ── 5: 多意图分句 ──
        segments = self.segmenter.segment(
            normalized, enable_multi_intent=self.config.enable_multi_intent,
        )
        if not segments:
            return self._unknown_result(original, normalized, "空文本或无法拆分")

        # ── 6-9: 每个 segment 独立走 向量召回 → 融合打分 → 歧义判断 → LLM 精判 ──
        hits: list[IntentHit] = []
        for segment in segments:
            hits.append(await self._recognize_segment(segment, normalized, signals))

        # ── 组装 IntentResult ──
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
            "意图识别完成：intent=%s confidence=%.2f hits=%s multi=%s elapsed_ms=%.0f",
            result.primary_intent, result.confidence, len(result.hits),
            result.is_multi_intent, (time.perf_counter() - started) * 1000,
        )
        return result

    async def recognize_and_route(
        self,
        text: str | None,
        *,
        pending_state: PendingIntentState | None = None,
    ) -> RoutedIntent:
        """意图识别 + 路由，返回 RoutedIntent。"""

        # ── 1: 意图识别 ──
        result = await self.recognize(text, pending_state=pending_state)

        # ── 2: 路由映射 ──
        routed = self.router.route(result)
        return routed

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _recognize_segment(
        self, segment: str, full_text: str, signals,
    ) -> IntentHit:
        """单个 segment 的意图识别（步骤 6-9）。

        6. 向量召回 → 7. 融合打分 → 8. 歧义判断 → 9. LLM 精判
        """

        # ── 6: 向量意图召回 ──
        vector_candidates = await self.vector_retriever.retrieve(segment)

        # ── 7: 融合打分（vector + keyword + context）──
        fused = self.fusion_scorer.score(
            vector_candidates, signals, segment=segment, full_text=full_text,
        )

        # ── 8: 歧义判断 ──
        top, is_ambiguous, need_llm, need_clarification, amb_reason = (
            self.ambiguity_detector.detect(fused)
        )

        # ── 9: LLM 精判（仅模糊候选触发，节省 LLM 调用）──
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
