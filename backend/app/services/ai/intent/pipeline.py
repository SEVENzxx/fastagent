"""IntentRecognitionPipeline：10 层意图识别总编排。

注意：`intent/` 目录里的文件名按字母排序显示，不代表执行顺序。
真实执行顺序看 `PIPELINE_STEPS` 和 `recognize()` / `_recognize_segment()`。
"""

from __future__ import annotations

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
from app.services.ai.intent.types import AmbiguityDecision, IntentHit, IntentResult, PendingIntentState, RoutedIntent
from app.services.ai.intent.vector_retriever import VectorIntentRetriever, VectorProvider


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

    async def recognize(
        self,
        text: str | None,
        *,
        pending_state: PendingIntentState | None = None,
    ) -> IntentResult:
        """识别意图，返回 IntentResult。"""
        # Step 1: TextNormalizer
        original = str(text or "")
        normalized = self.normalizer.normalize(original)

        # Step 2: RuleMatcher
        # 强规则只处理明确、高风险诉求；命中 HUMAN/SILENT 时直接停止后续向量和 LLM。
        strong_hit = self.rule_matcher.match(normalized)
        if strong_hit is not None and strong_hit.route in {"HUMAN", "SILENT"}:
            return IntentResult(
                original_text=original,
                normalized_text=normalized,
                primary_intent=strong_hit.intent,
                confidence=strong_hit.confidence,
                hits=[strong_hit],
                candidates=strong_hit.candidates,
                is_multi_intent=False,
                need_clarification=False,
                source="rule_matcher",
                reason=strong_hit.reason,
            )

        # Step 3: KeywordEntityExtractor
        # 关键词/实体层只产出加权信号，不直接决定最终 intent。
        signals = self.keyword_entity.extract(normalized)

        # Step 4: ContextStateResolver
        # 如果上一轮正在等待订单号/手机号等槽位，这里优先把当前输入当作槽位补全处理。
        context_hit = self.context_state.resolve(normalized, signals, pending_state)
        if context_hit is not None:
            return IntentResult(
                original_text=original,
                normalized_text=normalized,
                primary_intent=context_hit.intent,
                confidence=context_hit.confidence,
                hits=[context_hit],
                candidates=context_hit.candidates,
                is_multi_intent=False,
                need_clarification=False,
                source="context_state",
                reason=context_hit.reason,
            )

        # Step 5: MessageSegmenter
        # 拆句后，每个 segment 走 Step 6-9 独立识别，最后合并 hits。
        segments = self.segmenter.segment(
            normalized,
            enable_multi_intent=self.config.enable_multi_intent,
        )
        if not segments:
            return self._unknown_result(original, normalized, "空文本或无法拆分")

        hits: list[IntentHit] = []
        for segment in segments:
            hits.append(await self._recognize_segment(segment, normalized, signals))

        primary_hit = max(hits, key=lambda item: item.confidence) if hits else None
        candidates = [candidate for hit in hits for candidate in hit.candidates]
        return IntentResult(
            original_text=original,
            normalized_text=normalized,
            primary_intent=primary_hit.intent if primary_hit else "unknown_intent",
            confidence=primary_hit.confidence if primary_hit else 0.0,
            hits=hits,
            candidates=candidates,
            is_multi_intent=len([hit for hit in hits if hit.intent != "unknown_intent"]) > 1,
            need_clarification=any(hit.ambiguous for hit in hits),
            source=self._source_for_hits(hits),
            reason="多意图识别完成" if len(hits) > 1 else (primary_hit.reason if primary_hit else "无候选"),
        )

    async def recognize_and_route(
        self,
        text: str | None,
        *,
        pending_state: PendingIntentState | None = None,
    ) -> RoutedIntent:
        """识别并路由，返回 RoutedIntent。"""
        # Step 10: IntentRouter
        return self.router.route(await self.recognize(text, pending_state=pending_state))

    async def _recognize_segment(
        self,
        segment: str,
        full_text: str,
        signals,
    ) -> IntentHit:
        # Step 6: VectorIntentRetriever
        # 向量层只召回候选，不直接决定最终 intent。
        vector_candidates = await self.vector_retriever.retrieve(segment)

        # Step 7: IntentFusionScorer
        fused = self.fusion_scorer.score(
            vector_candidates,
            signals,
            segment=segment,
            full_text=full_text,
        )
        # Step 8: AmbiguityDetector
        decision = self.ambiguity_detector.detect(fused)

        # Step 9: LLMIntentJudge
        # 只有低置信/歧义时才调用，且只能从 candidates 中选择。
        if decision.need_llm:
            judged = await self.llm_judge.judge(segment, decision.candidates)
            if judged is not None:
                selected = self._candidate_decision(judged.primary_intent, decision)
                return self._hit_from_decision(
                    segment,
                    selected,
                    ambiguous=False,
                    need_reason=judged.reason,
                    source_candidates=decision.candidates,
                )

        return self._hit_from_decision(
            segment,
            decision,
            ambiguous=decision.ambiguous,
            need_reason=decision.reason,
            source_candidates=decision.candidates,
        )

    def _hit_from_decision(
        self,
        segment: str,
        decision: AmbiguityDecision,
        *,
        ambiguous: bool,
        need_reason: str | None,
        source_candidates,
    ) -> IntentHit:
        route = self.config.route_for(decision.intent)
        return IntentHit(
            segment=segment,
            intent=decision.intent,
            label=self.config.label_for(decision.intent),
            confidence=decision.confidence,
            route=route.route,
            skill=route.skill,
            candidates=list(source_candidates or []),
            ambiguous=ambiguous,
            reason=need_reason,
        )

    def _candidate_decision(self, intent: str, fallback: AmbiguityDecision) -> AmbiguityDecision:
        for candidate in fallback.candidates:
            if candidate.intent == intent:
                return AmbiguityDecision(
                    intent=candidate.intent,
                    label=candidate.label,
                    confidence=candidate.score,
                    ambiguous=False,
                    need_llm=False,
                    need_clarification=False,
                    reason="LLM 选择候选意图",
                    candidates=fallback.candidates,
                )
        return fallback

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
        if any(hit.ambiguous for hit in hits):
            return "ambiguous"
        if any(hit.candidates for hit in hits):
            return "fusion"
        return "unknown"
