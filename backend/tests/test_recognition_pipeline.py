"""RecognitionPipeline 单元测试。

覆盖 7 个关键场景：
  1. examples.py 可导入且非空
  2. 强规则直接返回（转人工 → human.transfer，空消息 → template.silent）
  3. "你好" 不被误判为 template.confirmation（_SILENT_EXACT 精确匹配）
  4. "谢谢" → template.farewell（非 template.greeting）
  5. 上下文优先：短确认+草稿订单 → order.confirm
  6. 歧义 intent 不短路为 product.filter_search
  7. recognize(message, context) 调用约定兼容位置/关键字参数
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.ai.recognition.examples import DEFAULT_INTENT_EXAMPLES
from app.ai.recognition.entity_extractors import extract_all
from app.ai.recognition.pipeline import RecognitionPipeline
from app.ai.recognition.types import ScenarioDecision
from app.ai.recognition.types import IntentCandidate, SkillName
from app.ai.context.session_context import SessionContext


@pytest.fixture
def pipeline() -> RecognitionPipeline:
    return RecognitionPipeline()


# ══════════════════════════════════════════════
# 1. examples.py 导入
# ══════════════════════════════════════════════


class TestExamplesImport:
    """验证 examples.py 正确导出旧样本数据。"""

    def test_default_intent_examples_importable(self) -> None:
        """DEFAULT_INTENT_EXAMPLES 可导入且非空。"""
        assert DEFAULT_INTENT_EXAMPLES is not None
        assert len(DEFAULT_INTENT_EXAMPLES) > 0


# ══════════════════════════════════════════════
# 2. 强规则路径
# ══════════════════════════════════════════════


class TestRulePath:
    """验证强规则直接返回，不触发 LLM 和 Vector。"""

    @pytest.mark.asyncio
    async def test_transfer_human(self, pipeline: RecognitionPipeline) -> None:
        """转人工 → human.transfer。"""
        result = await pipeline.recognize("转人工")
        assert isinstance(result, ScenarioDecision)
        assert result.scenario_id == "human.transfer"
        assert result.confidence == 1.0

    @pytest.mark.asyncio
    async def test_complaint(self, pipeline: RecognitionPipeline) -> None:
        """投诉 → human.transfer。"""
        result = await pipeline.recognize("我要投诉你们")
        assert result.scenario_id == "human.transfer"
        assert result.confidence == 0.98

    @pytest.mark.asyncio
    async def test_empty_message(self, pipeline: RecognitionPipeline) -> None:
        """空消息 → template.silent。"""
        result = await pipeline.recognize("")
        assert result.scenario_id == "template.silent"
        assert result.confidence == 1.0

    @pytest.mark.asyncio
    async def test_empty_whitespace(self, pipeline: RecognitionPipeline) -> None:
        """纯空白 → template.silent。"""
        result = await pipeline.recognize("   ")
        assert result.scenario_id == "template.silent"


# ══════════════════════════════════════════════
# 3. "你好" 不误判
# ══════════════════════════════════════════════


class TestHelloNotConfirmation:
    """验证"你好"不会被误判为 template.confirmation。

    修复：_SILENT_EXACT 要求短词精确匹配，"好"不匹配"你好"。
    """

    @pytest.mark.asyncio
    async def test_hello_not_confirmation(self, pipeline: RecognitionPipeline) -> None:
        """"你好" → NOT template.confirmation。"""
        with patch.object(
            pipeline._vector, "retrieve", new=AsyncMock(return_value=[]),
        ), patch(
            "app.ai.recognition.pipeline.complete",
            new=AsyncMock(
                return_value='{"scenario_id": "template.greeting", "confidence": 0.9, "reason": "问候"}'
            ),
        ):
            result = await pipeline.recognize("你好")
            assert result.scenario_id != "template.confirmation"
            assert result.scenario_id == "template.greeting"


# ══════════════════════════════════════════════
# 4. "谢谢" → template.farewell
# ══════════════════════════════════════════════


class TestThankYouFarewell:
    """验证"谢谢"归类为 template.farewell。

    修复：SILENT 规则中"谢谢"子串匹配 → template.farewell。
    """

    @pytest.mark.asyncio
    async def test_thank_you(self, pipeline: RecognitionPipeline) -> None:
        """"谢谢" → template.farewell。"""
        result = await pipeline.recognize("谢谢")
        assert result.scenario_id == "template.farewell"
        assert result.confidence == 1.0

    @pytest.mark.asyncio
    async def test_thanks_variants(self, pipeline: RecognitionPipeline) -> None:
        """感谢类变体均 → template.farewell。"""
        for text in ("多谢", "感谢", "谢谢啦", "thx"):
            result = await pipeline.recognize(text)
            assert result.scenario_id == "template.farewell", f"'{text}' 应为 template.farewell"


# ══════════════════════════════════════════════
# 5. 上下文优先：短确认+草稿订单
# ══════════════════════════════════════════════


class TestContextPriority:
    """验证上下文优先逻辑（短确认+草稿订单）优先于规则匹配。"""

    @pytest.mark.asyncio
    async def test_confirm_with_draft(self, pipeline: RecognitionPipeline) -> None:
        """"好的" + draft_order_id → order.confirm（而非 template.confirmation）。"""
        result = await pipeline.recognize("好的", context={"draft_order_id": 123})
        assert result.scenario_id == "order.confirm"
        assert result.confidence == 0.92

    @pytest.mark.asyncio
    async def test_confirm_signals_with_draft(self, pipeline: RecognitionPipeline) -> None:
        """各种确认词 + draft_order_id → order.confirm。"""
        context = {"draft_order_id": 456}
        for text in ("确认", "可以", "没问题", "下单", "就这个"):
            result = await pipeline.recognize(text, context=context)
            assert result.scenario_id == "order.confirm", f"'{text}' + draft 应为 order.confirm"

    @pytest.mark.asyncio
    async def test_confirm_without_draft_falls_to_rules(self, pipeline: RecognitionPipeline) -> None:
        """"好的" 无草稿订单 → 走规则匹配 → template.confirmation。"""
        result = await pipeline.recognize("好的")
        assert result.scenario_id == "template.confirmation"

    @pytest.mark.asyncio
    async def test_non_confirm_with_draft(self, pipeline: RecognitionPipeline) -> None:
        """非确认词 + draft_order_id → 不走上下文优先（走正常流程）。"""
        with patch.object(
            pipeline._vector, "retrieve", new=AsyncMock(return_value=[]),
        ), patch(
            "app.ai.recognition.pipeline.complete",
            new=AsyncMock(
                return_value=(
                    '{"scenario_id": "product.filter_search",'
                    ' "confidence": 0.8, "reason": "商品搜索"}'
                )
            ),
        ):
            result = await pipeline.recognize("耳机", context={"draft_order_id": 789})
            assert result.scenario_id != "order.confirm"

    @pytest.mark.asyncio
    async def test_ok_without_draft(self, pipeline: RecognitionPipeline) -> None:
        """"OK" 无草稿 → 规则匹配 → template.confirmation。"""
        result = await pipeline.recognize("OK")
        assert result.scenario_id == "template.confirmation"


# ══════════════════════════════════════════════
# 5b. SessionContext 兼容性
# ══════════════════════════════════════════════


class TestSessionContextCompat:
    """验证真实 SessionContext 对象传递不崩溃。"""

    @pytest.mark.asyncio
    async def test_session_context_with_draft(self, pipeline: RecognitionPipeline) -> None:
        """"好的" + SessionContext(draft_order_id='d1') → order.confirm。"""
        ctx = SessionContext(draft_order_id="d1")
        result = await pipeline.recognize("好的", context=ctx)
        assert result.scenario_id == "order.confirm"

    @pytest.mark.asyncio
    async def test_session_context_rule_path(self, pipeline: RecognitionPipeline) -> None:
        """SessionContext + 转人工 → human.transfer，不崩溃。"""
        ctx = SessionContext(tenant_id=42)
        result = await pipeline.recognize("转人工", context=ctx)
        assert result.scenario_id == "human.transfer"
        assert result.confidence == 1.0

    @pytest.mark.asyncio
    async def test_session_context_no_draft_falls_to_rules(self, pipeline: RecognitionPipeline) -> None:
        """SessionContext 无草稿 + "好的" → template.confirmation。"""
        ctx = SessionContext()  # 没有 draft_order_id
        result = await pipeline.recognize("好的", context=ctx)
        assert result.scenario_id == "template.confirmation"

    @pytest.mark.asyncio
    async def test_session_context_tenant_id(self, pipeline: RecognitionPipeline) -> None:
        """SessionContext(tenant_id=99) 传递给 vector 不崩溃。"""
        with patch.object(
            pipeline._vector, "retrieve", new=AsyncMock(return_value=[]),
        ), patch(
            "app.ai.recognition.pipeline.complete",
            new=AsyncMock(
                return_value='{"scenario_id": "template.greeting", "confidence": 0.9, "reason": "问候"}'
            ),
        ):
            ctx = SessionContext(tenant_id=99)
            result = await pipeline.recognize("你好", context=ctx)
            assert result.scenario_id == "template.greeting"


# ══════════════════════════════════════════════
# 6. 歧义 intent 不短路
# ══════════════════════════════════════════════


class TestAmbiguousIntents:
    """验证歧义 intent 不走高置信短路。"""

    @pytest.mark.asyncio
    async def test_product_search_does_not_shortcut(self, pipeline: RecognitionPipeline) -> None:
        """product_search 歧义 → 不短路，走 LLM 判决。"""
        candidates = [
            IntentCandidate(
                scenario_id="product.detail", label="商品详情",
                score=0.95, skill=SkillName.PRODUCT,
            ),
        ]
        with patch.object(
            pipeline._vector, "retrieve", new=AsyncMock(return_value=candidates),
        ), patch(
            "app.ai.recognition.pipeline.complete",
            new=AsyncMock(
                return_value=(
                    '{"scenario_id": "product.catalog",'
                    ' "confidence": 0.85, "reason": "商品浏览"}'
                )
            ),
        ):
            result = await pipeline.recognize("你们有什么产品")
            # 不应走高置信短路（product.detail 是歧义场景）
            assert result.scenario_id != "product.filter_search"
            # 应通过 LLM 判决
            assert result.scenario_id == "product.catalog"

    @pytest.mark.asyncio
    async def test_chitchat_does_not_shortcut(self, pipeline: RecognitionPipeline) -> None:
        """chitchat 歧义 → 不短路。"""
        candidates = [
            IntentCandidate(
                scenario_id="template.farewell", label="结束对话",
                score=0.95, skill=SkillName.TEMPLATE,
            ),
        ]
        with patch.object(
            pipeline._vector, "retrieve", new=AsyncMock(return_value=candidates),
        ), patch(
            "app.ai.recognition.pipeline.complete",
            new=AsyncMock(
                return_value=(
                    '{"scenario_id": "template.greeting",'
                    ' "confidence": 0.9, "reason": "问候"}'
                )
            ),
        ):
            result = await pipeline.recognize("哈哈")
            assert result.scenario_id != "product.filter_search"
            assert result.scenario_id == "template.greeting"

    @pytest.mark.asyncio
    async def test_non_ambiguous_shortcuts(self, pipeline: RecognitionPipeline) -> None:
        """非歧义 intent 可以走高置信短路。"""
        candidates = [
            IntentCandidate(
                scenario_id="order.confirm", label="确认订单",
                score=0.95, skill=SkillName.ORDER,
            ),
            IntentCandidate(
                scenario_id="order.confirm", label="确认订单",
                score=0.80, skill=SkillName.ORDER,
            ),
        ]
        with patch.object(
            pipeline._vector, "retrieve", new=AsyncMock(return_value=candidates),
        ):
            result = await pipeline.recognize("确认下单")
            assert result.scenario_id == "order.confirm"


# ══════════════════════════════════════════════
# 8. 实体抽取边界
# ══════════════════════════════════════════════


class TestEntityExtraction:
    """验证实体抽取避免误抽和边界正确。"""

    def test_quantity_not_price(self) -> None:
        """"给我下单3个第三款耳机" → 不抽价格。"""
        entities = extract_all("给我下单3个第三款耳机")
        assert "price_min" not in entities, "数量 3 不应被当作价格"
        assert "price_max" not in entities
        assert entities.get("quantity") == 3

    def test_order_ref_not_price(self) -> None:
        """"订单123456怎么样" → 不抽价格。"""
        entities = extract_all("订单123456怎么样")
        assert "price_min" not in entities, "订单号 123456 不应被当作价格"
        assert "price_max" not in entities
        assert entities.get("order_ref") == "123456"

    def test_price_within_max_only(self) -> None:
        """"200以内" → price_max=200，无 price_min。"""
        entities = extract_all("我需要200以内的耳机")
        assert entities.get("price_max") == 200
        assert "price_min" not in entities

    def test_price_below_max_only(self) -> None:
        """"不超过200" → price_max=200。"""
        entities = extract_all("不超过200的耳机")
        assert entities.get("price_max") == 200
        assert "price_min" not in entities

    def test_price_budget_max_only(self) -> None:
        """"预算3000" → price_max=3000。"""
        entities = extract_all("预算3000")
        assert entities.get("price_max") == 3000
        assert "price_min" not in entities

    def test_price_above_min_only(self) -> None:
        """"200元以上" → price_min=200。"""
        entities = extract_all("200元以上的商品")
        assert entities.get("price_min") == 200
        assert "price_max" not in entities

    def test_exact_price(self) -> None:
        """"200元" → price_min=200, price_max=200。"""
        entities = extract_all("200元")
        assert entities.get("price_min") == 200
        assert entities.get("price_max") == 200

    def test_price_range(self) -> None:
        """"500-1000元" → price_min=500, price_max=1000。"""
        entities = extract_all("500-1000元")
        assert entities.get("price_min") == 500
        assert entities.get("price_max") == 1000

    def test_price_keyword_validates(self) -> None:
        """"价格500" → price_min=500, price_max=500。"""
        entities = extract_all("价格500")
        assert entities.get("price_min") == 500
        assert entities.get("price_max") == 500

    def test_approximate_price(self) -> None:
        """"200左右" → price_min=200, price_max=200。"""
        entities = extract_all("200左右")
        assert entities.get("price_min") == 200
        assert entities.get("price_max") == 200

    def test_range_product_index_not_price(self) -> None:
        """"第1-2款有什么区别" → 不抽价格区间。"""
        entities = extract_all("第1-2款有什么区别")
        assert "price_min" not in entities
        assert "price_max" not in entities

    def test_range_quantity_not_price(self) -> None:
        """"3到5个耳机" → 不抽价格区间，抽 quantity=5。"""
        entities = extract_all("3到5个耳机")
        assert "price_min" not in entities, "数量范围 3-5 不应被当作价格"
        assert "price_max" not in entities
        assert entities.get("quantity") == 5

    def test_range_order_ref_not_price(self) -> None:
        """"订单123456到123457是什么" → 不抽价格区间。"""
        entities = extract_all("订单123456到123457是什么")
        assert "price_min" not in entities, "订单号范围不应被当作价格"
        assert "price_max" not in entities
        assert entities.get("order_ref") == "123456"

    def test_range_with_unit(self) -> None:
        """"500-1000元" → 有价格单位，正常抽取。"""
        entities = extract_all("500-1000元")
        assert entities.get("price_min") == 500
        assert entities.get("price_max") == 1000

    def test_range_with_context(self) -> None:
        """"预算1000-2000" → 价格语境，正常抽取。"""
        entities = extract_all("预算1000-2000")
        assert entities.get("price_min") == 1000
        assert entities.get("price_max") == 2000

    def test_category_stop_word(self) -> None:
        """"有什么区别" → 不抽分类提示。"""
        entities = extract_all("第1-2款有什么区别")
        assert "raw_category_text" not in entities

    def test_category_valid(self) -> None:
        """"有什么耳机" → 正常抽 raw_category_text="耳机"。"""
        entities = extract_all("有什么耳机")
        assert entities.get("raw_category_text") == "耳机"


# ══════════════════════════════════════════════
# 9. 调用约定
# ══════════════════════════════════════════════


class TestCallingConvention:
    """验证 recognize(message, context) 签名兼容多种调用方式。"""

    @pytest.mark.asyncio
    async def test_positional_args(self, pipeline: RecognitionPipeline) -> None:
        """位置参数调用 recognize(message, context)。"""
        result = await pipeline.recognize("转人工", {"dummy": True})
        assert result.scenario_id == "human.transfer"

    @pytest.mark.asyncio
    async def test_keyword_args(self, pipeline: RecognitionPipeline) -> None:
        """关键字参数调用 recognize(message, context=xxx)。"""
        result = await pipeline.recognize(message="转人工", context={"dummy": True})
        assert result.scenario_id == "human.transfer"

    @pytest.mark.asyncio
    async def test_message_only(self, pipeline: RecognitionPipeline) -> None:
        """仅传 message，context 默认为 None。"""
        result = await pipeline.recognize("转人工")
        assert result.scenario_id == "human.transfer"
