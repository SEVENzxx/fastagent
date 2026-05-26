"""Phase 8 分层意图识别流水线测试。"""

import pytest

from app.config import settings
from app.services.ai.config.intent_config import DEFAULT_INTENT_CONFIG
from app.services.ai.intent.pipeline import IntentRecognitionPipeline
from app.services.ai.intent.types import IntentCandidate, PendingIntentState


@pytest.fixture(autouse=True)
def disable_real_embedding_for_unit_tests(monkeypatch):
    """意图流水线单测默认不访问外部 embedding 服务，避免单测受网络影响。"""
    monkeypatch.setattr(settings, "AI_EMBEDDING_ENABLED", False)


@pytest.mark.asyncio
async def test_strong_rule_transfer_returns_human_without_vector_or_llm():
    """强规则命中转人工，直接返回 HUMAN。"""
    called = False

    async def vector_provider(_text, _top_k, _min_score):
        nonlocal called
        called = True
        return []

    pipeline = IntentRecognitionPipeline(vector_provider=vector_provider)
    routed = await pipeline.recognize_and_route("我要转人工")

    assert routed.route == "HUMAN"
    assert routed.primary_intent == "transfer_request"
    assert called is False


@pytest.mark.asyncio
async def test_price_question_recognized_as_product_price():
    """“这个多少钱？”识别为 product_price。"""
    result = await IntentRecognitionPipeline().recognize("这个多少钱？")

    assert result.primary_intent == "product_price"
    assert result.hits[0].route == "AGENT"
    assert result.hits[0].skill == "product_price"


@pytest.mark.asyncio
async def test_stock_question_recognized_as_product_stock():
    """“这个有货吗？”识别为 product_stock。"""
    result = await IntentRecognitionPipeline().recognize("这个有货吗？")

    assert result.primary_intent == "product_stock"
    assert result.hits[0].skill == "product_stock"


@pytest.mark.asyncio
async def test_multi_question_builds_multiple_hits():
    """多问题拆句后分别识别。"""
    result = await IntentRecognitionPipeline().recognize("这个多少钱？有货吗？今天能发吗？")

    intents = [hit.intent for hit in result.hits]
    assert result.is_multi_intent is True
    assert intents == ["product_price", "product_stock", "delivery_time"]


@pytest.mark.asyncio
async def test_keyword_boost_affects_order_and_delivery_candidates():
    """订单/发货关键词会影响 order_status 和 delivery_time 候选。"""
    result = await IntentRecognitionPipeline().recognize("我的订单怎么还没发货？")

    candidate_intents = {candidate.intent for candidate in result.candidates}
    assert result.primary_intent in {"order_status", "delivery_time"}
    assert {"order_status", "delivery_time"}.issubset(candidate_intents)


@pytest.mark.asyncio
async def test_close_candidate_scores_mark_ambiguous():
    """候选分数接近时触发真实 LLMIntentJudge API 调用。"""
    async def vector_provider(_text, _top_k, _min_score):
        return [
            IntentCandidate("product_price", "商品价格", 0.82, "vector", "多少钱"),
            IntentCandidate("product_stock", "商品库存", 0.80, "vector", "有货吗"),
        ]

    pipeline = IntentRecognitionPipeline(vector_provider=vector_provider)
    result = await pipeline.recognize("这个怎么弄")

    assert result.primary_intent in {"product_price", "product_stock"}
    assert result.hits[0].reason


@pytest.mark.asyncio
async def test_no_candidates_returns_unknown_intent():
    """没有候选时返回 unknown_intent。"""
    async def vector_provider(_text, _top_k, _min_score):
        return []

    pipeline = IntentRecognitionPipeline(vector_provider=vector_provider)
    result = await pipeline.recognize("完全无法匹配的内容")

    assert result.primary_intent == "unknown_intent"
    assert result.hits[0].route == "GENERAL_REPLY"


@pytest.mark.asyncio
async def test_low_confidence_triggers_llm_intent_judge():
    """低置信度时触发真实 LLMIntentJudge API 调用。"""
    async def vector_provider(_text, _top_k, _min_score):
        return [
            IntentCandidate("product_price", "商品价格", 0.78, "vector", "价格多少"),
            IntentCandidate("product_inquiry", "商品咨询", 0.74, "vector", "介绍一下"),
        ]

    pipeline = IntentRecognitionPipeline(vector_provider=vector_provider)
    result = await pipeline.recognize("这个贵不贵")

    assert result.primary_intent == "product_price"
    assert result.hits[0].reason


@pytest.mark.asyncio
async def test_routed_intent_supports_hits_list():
    """RoutedIntent 支持 hits 列表。"""
    routed = await IntentRecognitionPipeline().recognize_and_route("这个多少钱？有货吗？")

    assert routed.is_multi_intent is True
    assert len(routed.hits) == 2
    assert routed.primary_intent == "product_price"


def test_intent_route_map_maps_route_and_skill():
    """intent route map 能正确映射 route 和 skill。"""
    price = DEFAULT_INTENT_CONFIG.route_for("product_price")
    human = DEFAULT_INTENT_CONFIG.route_for("transfer_request")

    assert price.route == "AGENT"
    assert price.skill == "product_price"
    assert human.route == "HUMAN"
    assert human.skill == "human_service"


@pytest.mark.asyncio
async def test_pending_order_state_accepts_bare_order_number():
    """等待订单号时，用户只输入订单号也能直接补全 order_status。"""
    called = False

    async def vector_provider(_text, _top_k, _min_score):
        nonlocal called
        called = True
        return []

    pending = PendingIntentState(
        intent="order_status",
        skill="order_status",
        required_entities=["order_no"],
        filled_entities={},
        last_prompt="麻烦提供你的订单号",
    )
    pipeline = IntentRecognitionPipeline(vector_provider=vector_provider)
    result = await pipeline.recognize("202605260001", pending_state=pending)

    assert result.primary_intent == "order_status"
    assert result.source == "context_state"
    assert result.hits[0].skill == "order_status"
    assert "order_no=202605260001" in (result.hits[0].reason or "")
    assert called is False


@pytest.mark.asyncio
async def test_pending_state_does_not_override_strong_rule():
    """即使正在等待订单号，用户改说投诉时也必须优先走强规则。"""
    pending = PendingIntentState(
        intent="order_status",
        skill="order_status",
        required_entities=["order_no"],
    )

    routed = await IntentRecognitionPipeline().recognize_and_route("我要投诉", pending_state=pending)

    assert routed.primary_intent == "complaint"
    assert routed.route == "HUMAN"
