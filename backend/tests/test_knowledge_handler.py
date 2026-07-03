"""KnowledgeHandler 单元测试。

覆盖 6 个知识场景路径：
  1. QA pair 直出（不调 LLM）
  2. 知识分块短内容直出
  3. 无命中返回"未查到"
  4. 追问精准续查（last_knowledge_refs）
  5. 长内容 LLM 摘要
  6. 上下文更新校验
"""
from __future__ import annotations

import re
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from app.ai.context.pending_state import PendingDirective
from app.ai.handlers.knowledge import (
    KnowledgeHandler,
    _build_knowledge_refs,
    _preview,
)
from app.ai.recognition.types import ScenarioDecision
from app.ai.reply_builders.knowledge import KnowledgeReplyBuilder
from app.ai.context.session_context import SessionContext
from app.ai.handlers.base import ToolResult


# ══════════════════════════════════════════════
# Fake KnowledgeSkill
# ══════════════════════════════════════════════


def _text_match(query: str, text: str) -> bool:
    """双向文本匹配：子串匹配 + 中文二元词组重叠。"""
    if query in text or text in query:
        return True
    # 中文二元词组重叠（滑动窗口提取相邻二字组合）
    q_words = _chinese_bigrams(query)
    t_words = _chinese_bigrams(text)
    return bool(q_words & t_words)


def _chinese_bigrams(text: str) -> set[str]:
    """提取中文文本中所有相邻二字组合。"""
    chars = re.findall(r'[一-鿿]', text.lower())
    return set(''.join(chars[i:i+2]) for i in range(len(chars) - 1))


class FakeKnowledgeSkill:
    """内存 KnowledgeSkill，不依赖数据库和向量检索。"""

    qa_pairs: list[dict[str, Any]] = []
    knowledge_chunks: list[dict[str, Any]] = []
    call_log: list[dict[str, Any]] = []

    @classmethod
    def reset(cls) -> None:
        cls.qa_pairs = []
        cls.knowledge_chunks = []
        cls.call_log = []

    @classmethod
    def add_qa(
        cls,
        qa_id: str,
        question: str,
        answer: str,
        *,
        keywords: list[str] | None = None,
    ) -> None:
        cls.qa_pairs.append({
            "id": qa_id,
            "question": question,
            "answer": answer,
            "keywords": keywords or [],
            "score": 0.95,
        })

    @classmethod
    def add_knowledge(
        cls,
        chunk_id: str,
        content: str,
        *,
        doc_id: str = "",
        title: str = "",
        token_count: int = 100,
        product_id: str = "",
    ) -> None:
        cls.knowledge_chunks.append({
            "id": chunk_id,
            "doc_id": doc_id,
            "content": content,
            "token_count": token_count,
            "title": title,
            "product_id": product_id,
            "score": 0.9,
        })

    @staticmethod
    async def search_qa(
        *,
        tenant_id: int,
        query: str,
        db: Any = None,
        **kwargs: Any,
    ) -> ToolResult:
        _ = db
        FakeKnowledgeSkill.call_log.append({
            "method": "search_qa",
            "tenant_id": tenant_id,
            "query": query,
        })

        query_lower = query.lower()
        items = []
        for qa in FakeKnowledgeSkill.qa_pairs:
            qa_q = qa["question"].lower()
            qa_a = qa["answer"].lower()
            # 双向匹配 + 关键词重叠
            if (qa_q and _text_match(query_lower, qa_q)) or _text_match(query_lower, qa_a):
                items.append(qa)

        return ToolResult(ok=True, skill_name="search_qa", result={"items": items})

    @staticmethod
    async def search_knowledge(
        *,
        tenant_id: int,
        query: str,
        doc_ids: list[str] | None = None,
        product_id: str | None = None,
        db: Any = None,
        **kwargs: Any,
    ) -> ToolResult:
        _ = db
        FakeKnowledgeSkill.call_log.append({
            "method": "search_knowledge",
            "tenant_id": tenant_id,
            "query": query,
            "doc_ids": doc_ids,
            "product_id": product_id,
        })

        query_lower = query.lower()
        items = []
        for chunk in FakeKnowledgeSkill.knowledge_chunks:
            content = chunk["content"].lower()
            if content and _text_match(query_lower, content):
                items.append(chunk)

        # doc_ids 过滤（追问场景）
        if doc_ids:
            items = [i for i in items if i["doc_id"] in doc_ids]
        if product_id:
            items = [i for i in items if str(i.get("product_id") or "") == str(product_id)]

        return ToolResult(ok=True, skill_name="search_knowledge", result={"items": items})

    @staticmethod
    async def search_product_knowledge(
        *,
        tenant_id: int,
        query: str,
        product_id: str | int,
        db: Any = None,
        **kwargs: Any,
    ) -> ToolResult:
        """按商品 ID 检索知识分块。"""
        result = await FakeKnowledgeSkill.search_knowledge(
            tenant_id=tenant_id,
            query=query,
            product_id=str(product_id),
            db=db,
            **kwargs,
        )
        return ToolResult(
            ok=result.ok,
            skill_name="search_product_knowledge",
            result=result.result,
            error=result.error,
        )

# ══════════════════════════════════════════════
# 辅助函数
# ══════════════════════════════════════════════


def make_decision(scenario_id: str, **extra: Any) -> ScenarioDecision:
    """构造 ScenarioDecision。"""
    entities: dict[str, Any] = {"raw_text": extra.pop("text", "")}
    entities.update(extra)
    return ScenarioDecision(
        scenario_id=scenario_id,
        confidence=1.0,
        entities=entities,
    )


def make_context(**overrides: Any) -> SessionContext:
    """构造 SessionContext。"""
    defaults: dict[str, Any] = {
        "tenant_id": 1,
        "conversation_id": 1,
    }
    defaults.update(overrides)
    return SessionContext(**defaults)


# ══════════════════════════════════════════════
# 1. QA pair 直出
# ══════════════════════════════════════════════


class TestKnowledgeQA:
    """QA pair 高置信直出，不调 LLM。"""

    @pytest.mark.asyncio
    async def test_qa_single_hit(self) -> None:
        """单一 QA 匹配 → 直接返回答案。"""
        FakeKnowledgeSkill.reset()
        FakeKnowledgeSkill.add_qa(
            "qa_1", "有什么优惠活动", "目前有满 200 减 50 活动，全场通用。",
        )

        handler = KnowledgeHandler(skill=FakeKnowledgeSkill)
        ctx = make_context()
        decision = make_decision("knowledge.qa", text="有什么优惠")

        result = await handler.execute(decision, ctx)

        assert result.scenario_id == "knowledge.qa"
        assert result.pending_directive == PendingDirective.CLEAR
        assert "满 200 减 50" in result.reply
        # 上下文更新
        assert result.context_update.get("last_knowledge_scope") == "qa"
        assert "last_knowledge_refs" in result.context_update
        assert len(result.context_update["last_knowledge_refs"]) == 1

    @pytest.mark.asyncio
    async def test_qa_multi_hit(self) -> None:
        """多个 QA 匹配 → 编号列表渲染。"""
        FakeKnowledgeSkill.reset()
        FakeKnowledgeSkill.add_qa(
            "qa_1", "有什么优惠", "目前有满 200 减 50 活动。",
        )
        FakeKnowledgeSkill.add_qa(
            "qa_2", "保修多久", "保修期为 1 年。",
        )

        handler = KnowledgeHandler(skill=FakeKnowledgeSkill)
        ctx = make_context()
        decision = make_decision("knowledge.qa", text="有什么优惠和保修政策")

        result = await handler.execute(decision, ctx)

        assert result.scenario_id == "knowledge.qa"
        assert result.pending_directive == PendingDirective.CLEAR
        # 应该有多条（编号列表）
        assert "满 200 减 50" in result.reply
        assert result.context_update.get("last_knowledge_scope") == "qa"
        assert len(result.context_update["last_knowledge_refs"]) == 2

    @pytest.mark.asyncio
    async def test_qa_no_call_log_for_llm(self) -> None:
        """QA 直出不调 LLM（验证 call_log 无 LLM 调用）。"""
        FakeKnowledgeSkill.reset()
        FakeKnowledgeSkill.add_qa("qa_1", "优惠", "满减活动。")

        handler = KnowledgeHandler(skill=FakeKnowledgeSkill)
        ctx = make_context()
        decision = make_decision("knowledge.qa", text="优惠")

        await handler.execute(decision, ctx)

        # 只调了 search_qa，没调 search_knowledge
        methods = [c["method"] for c in FakeKnowledgeSkill.call_log]
        assert methods == ["search_qa"]


# ══════════════════════════════════════════════
# 2. 知识分块短内容直出
# ══════════════════════════════════════════════


class TestKnowledgePolicy:
    """知识分块直接返回（短内容）。"""

    @pytest.mark.asyncio
    async def test_knowledge_single_chunk(self) -> None:
        """单条短知识分块 → 直接返回。"""
        FakeKnowledgeSkill.reset()
        FakeKnowledgeSkill.add_knowledge(
            "chunk_1",
            "保修政策说明：本产品保修期为 1 年，自签收之日起计算。",
            title="保修政策",
            token_count=50,
        )

        handler = KnowledgeHandler(skill=FakeKnowledgeSkill)
        ctx = make_context()
        decision = make_decision("knowledge.policy", text="保修政策")

        result = await handler.execute(decision, ctx)

        assert result.scenario_id == "knowledge.policy"
        assert result.pending_directive == PendingDirective.CLEAR
        assert "保修期" in result.reply
        assert "1 年" in result.reply
        assert result.context_update.get("last_knowledge_scope") == "knowledge"

    @pytest.mark.asyncio
    async def test_knowledge_no_qa_call_needed(self) -> None:
        """知识场景优先查 QA，无命中再查知识库。"""
        FakeKnowledgeSkill.reset()
        FakeKnowledgeSkill.add_knowledge(
            "chunk_1",
            "退换货政策：7 天无理由退换。",
            title="退换货",
            token_count=30,
        )

        handler = KnowledgeHandler(skill=FakeKnowledgeSkill)
        ctx = make_context()
        decision = make_decision("knowledge.policy", text="退换货")

        await handler.execute(decision, ctx)

        methods = [c["method"] for c in FakeKnowledgeSkill.call_log]
        assert methods == ["search_qa", "search_knowledge"]

    @pytest.mark.asyncio
    async def test_order_cancel_policy_builtin_reply(self) -> None:
        """取消订单规则属于系统订单状态机政策，不依赖租户知识库。"""
        FakeKnowledgeSkill.reset()

        handler = KnowledgeHandler(skill=FakeKnowledgeSkill)
        ctx = make_context()
        decision = make_decision("knowledge.policy", text="什么样的情况可以取消订单？")

        result = await handler.execute(decision, ctx)

        assert result.scenario_id == "knowledge.policy"
        assert result.pending_directive == PendingDirective.CLEAR
        assert "发货前" in result.reply
        assert "人工客服" in result.reply
        assert result.context_update.get("last_knowledge_scope") == "builtin_policy"
        assert FakeKnowledgeSkill.call_log == []


# ══════════════════════════════════════════════
# 3. 无命中
# ══════════════════════════════════════════════


class TestKnowledgeNoResult:
    """无任何知识命中时返回"未查到"，不调 LLM。"""

    @pytest.mark.asyncio
    async def test_no_knowledge_returned(self) -> None:
        """无命中 → "未查到相关信息"。"""
        FakeKnowledgeSkill.reset()

        handler = KnowledgeHandler(skill=FakeKnowledgeSkill)
        ctx = make_context()
        decision = make_decision("knowledge.qa", text="完全未知的问题xyz")

        result = await handler.execute(decision, ctx)

        assert result.scenario_id == "knowledge.qa"
        assert "未查到" in result.reply

    @pytest.mark.asyncio
    async def test_no_llm_fallback(self) -> None:
        """无命中时不应调用 LLM。"""
        FakeKnowledgeSkill.reset()

        handler = KnowledgeHandler(skill=FakeKnowledgeSkill)
        ctx = make_context()
        decision = make_decision("knowledge.qa", text="完全未知")

        await handler.execute(decision, ctx)

        # 只调了 search_qa 和 search_knowledge
        methods = [c["method"] for c in FakeKnowledgeSkill.call_log]
        assert methods == ["search_qa", "search_knowledge"]

# ══════════════════════════════════════════════
# 4. 追问精准续查
# ══════════════════════════════════════════════


class TestKnowledgeFollowUp:
    """追问场景：基于 last_knowledge_refs 精准续查。"""

    @pytest.mark.asyncio
    async def test_follow_up_with_refs(self) -> None:
        """"刚刚那个政策" → 使用 last_knowledge_refs 的 doc_id 过滤。"""
        FakeKnowledgeSkill.reset()
        FakeKnowledgeSkill.add_knowledge(
            "chunk_1",
            "标准保修：1 年免费保修。",
            doc_id="doc_warranty",
            title="标准保修",
            token_count=30,
        )
        FakeKnowledgeSkill.add_knowledge(
            "chunk_2",
            "延长保修：额外 2 年，需付费购买。",
            doc_id="doc_ext_warranty",
            title="延长保修",
            token_count=40,
        )

        handler = KnowledgeHandler(skill=FakeKnowledgeSkill)
        ctx = make_context(
            last_knowledge_refs=[
                {"source_type": "document", "source_id": "chunk_1", "doc_id": "doc_warranty", "title": "标准保修", "content_preview": "1 年免费保修"},
                {"source_type": "document", "source_id": "chunk_2", "doc_id": "doc_ext_warranty", "title": "延长保修", "content_preview": "额外 2 年"},
            ],
            last_knowledge_scope="knowledge",
        )
        decision = make_decision("knowledge.policy", text="刚刚那个政策还能延长吗")

        result = await handler.execute(decision, ctx)

        assert result.scenario_id == "knowledge.policy"
        assert result.pending_directive == PendingDirective.CLEAR
        # 应返回与 refs 相关的内容
        assert result.reply
        # 验证 call_log 中 doc_ids 被传递
        follow_up_calls = [
            c for c in FakeKnowledgeSkill.call_log
            if c["method"] == "search_knowledge" and c.get("doc_ids")
        ]
        assert len(follow_up_calls) >= 1
        # doc_ids 应包含两个文档的 doc_id
        assert "doc_warranty" in follow_up_calls[0]["doc_ids"]
        assert "doc_ext_warranty" in follow_up_calls[0]["doc_ids"]

    @pytest.mark.asyncio
    async def test_follow_up_falls_through_on_no_hits(self) -> None:
        """追问无命中时降级到 QA/知识库全局检索。"""
        FakeKnowledgeSkill.reset()
        FakeKnowledgeSkill.add_qa(
            "qa_1", "优惠活动", "满 200 减 50 全场通用。",
        )

        handler = KnowledgeHandler(skill=FakeKnowledgeSkill)
        ctx = make_context(
            last_knowledge_refs=[
                {"source_type": "document", "source_id": "chunk_99", "doc_id": "doc_nonexistent", "title": "无关"},
            ],
        )
        # 追问词但 refs 中的 doc 无匹配 → 降级到全局 QA
        decision = make_decision("knowledge.qa", text="刚刚那个优惠还能用吗")

        result = await handler.execute(decision, ctx)

        assert result.reply
        # 应先后调用 search_knowledge（追问）+ search_qa（降级）
        methods = [c["method"] for c in FakeKnowledgeSkill.call_log]
        assert "search_knowledge" in methods
        assert "search_qa" in methods

    @pytest.mark.asyncio
    async def test_follow_up_without_refs_is_normal(self) -> None:
        """last_knowledge_refs 为空时，追问按正常路径处理。"""
        FakeKnowledgeSkill.reset()
        FakeKnowledgeSkill.add_qa(
            "qa_1", "有什么优惠", "满 200 减 50。",
        )

        handler = KnowledgeHandler(skill=FakeKnowledgeSkill)
        ctx = make_context()  # no last_knowledge_refs
        decision = make_decision("knowledge.qa", text="这个优惠还能叠加吗")

        result = await handler.execute(decision, ctx)

        assert result.reply
        # 正常走 QA 路径
        assert result.context_update.get("last_knowledge_scope") == "qa"


# ══════════════════════════════════════════════
# 5. 长内容 LLM 摘要
# ══════════════════════════════════════════════


class TestKnowledgeLLMSummary:
    """长内容/多条知识调用 LLM 摘要。"""

    @pytest.mark.asyncio
    async def test_long_content_triggers_llm(self) -> None:
        """token_count >= 300 → 调用 LLM 摘要。"""
        FakeKnowledgeSkill.reset()
        long_content = "保修政策详情。\n" * 100  # 远超 300 token
        FakeKnowledgeSkill.add_knowledge(
            "chunk_long",
            long_content,
            title="完整保修政策",
            token_count=500,
        )

        handler = KnowledgeHandler(skill=FakeKnowledgeSkill)

        with patch(
            "app.ai.reply_builders.knowledge.complete",
            new=AsyncMock(return_value="根据保修政策，本产品保修期为一年。"),
        ) as mock_complete:
            ctx = make_context()
            decision = make_decision("knowledge.policy", text="保修政策详情")

            result = await handler.execute(decision, ctx)

            assert result.reply
            assert "保修政策" in result.reply or "保修" in result.reply
            mock_complete.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_multiple_chunks_trigger_llm(self) -> None:
        """多条知识分块 → 调用 LLM 摘要。"""
        FakeKnowledgeSkill.reset()
        FakeKnowledgeSkill.add_knowledge(
            "chunk_1", "优惠 A：满 100 减 20。", title="优惠A", token_count=30,
        )
        FakeKnowledgeSkill.add_knowledge(
            "chunk_2", "优惠 B：满 200 减 50。", title="优惠B", token_count=30,
        )

        handler = KnowledgeHandler(skill=FakeKnowledgeSkill)

        with patch(
            "app.ai.reply_builders.knowledge.complete",
            new=AsyncMock(return_value="目前有满 100 减 20 和满 200 减 50 两种优惠。"),
        ) as mock_complete:
            ctx = make_context()
            decision = make_decision("knowledge.qa", text="有什么优惠")

            result = await handler.execute(decision, ctx)

            assert result.reply
            mock_complete.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_llm_fallback_to_knowledge(self) -> None:
        """LLM 调用失败 → 降级返回知识原文前 500 字。"""
        FakeKnowledgeSkill.reset()
        long_content = "A" * 600
        FakeKnowledgeSkill.add_knowledge(
            "chunk_1", long_content, title="长内容", token_count=500,
        )

        handler = KnowledgeHandler(skill=FakeKnowledgeSkill)

        with patch(
            "app.ai.reply_builders.knowledge.complete",
            new=AsyncMock(side_effect=RuntimeError("LLM 超时")),
        ):
            ctx = make_context()
            decision = make_decision("knowledge.policy", text="长内容")

            result = await handler.execute(decision, ctx)

            # 降级返回原文前 500 字
            assert result.reply
            assert "A" * 500 in result.reply or len(result.reply) <= 600


# ══════════════════════════════════════════════
# 6. 上下文更新校验
# ══════════════════════════════════════════════


class TestKnowledgeContextUpdate:
    """验证 last_knowledge_topic / last_knowledge_scope / last_knowledge_refs。"""

    @pytest.mark.asyncio
    async def test_qa_context_update(self) -> None:
        """QA 路径 → 设置正确的上下文。"""
        FakeKnowledgeSkill.reset()
        FakeKnowledgeSkill.add_qa("qa_1", "优惠活动", "满减优惠说明。")

        handler = KnowledgeHandler(skill=FakeKnowledgeSkill)
        ctx = make_context()
        decision = make_decision("knowledge.qa", text="优惠活动")

        result = await handler.execute(decision, ctx)

        assert result.context_update.get("last_knowledge_scope") == "qa"
        assert "last_knowledge_topic" in result.context_update
        refs = result.context_update.get("last_knowledge_refs", [])
        assert len(refs) >= 1
        assert refs[0]["source_type"] == "qa"
        assert refs[0]["source_id"] == "qa_1"
        assert refs[0]["doc_id"] == ""
        assert "title" in refs[0]
        assert "content_preview" in refs[0]

    @pytest.mark.asyncio
    async def test_knowledge_context_update(self) -> None:
        """知识分块路径 → 设置正确的上下文。"""
        FakeKnowledgeSkill.reset()
        FakeKnowledgeSkill.add_knowledge(
            "chunk_1", "保修政策：1 年保修。",
            doc_id="doc_warranty", title="保修政策", token_count=30,
        )

        handler = KnowledgeHandler(skill=FakeKnowledgeSkill)
        ctx = make_context()
        decision = make_decision("knowledge.policy", text="保修政策")

        result = await handler.execute(decision, ctx)

        assert result.context_update.get("last_knowledge_scope") == "knowledge"
        refs = result.context_update.get("last_knowledge_refs", [])
        assert len(refs) >= 1
        assert refs[0]["source_type"] == "document"
        assert refs[0]["source_id"] == "chunk_1"
        assert refs[0]["doc_id"] == "doc_warranty"

    @pytest.mark.asyncio
    async def test_refs_max_five(self) -> None:
        """last_knowledge_refs 最多 5 条。"""
        FakeKnowledgeSkill.reset()
        for i in range(10):
            FakeKnowledgeSkill.add_knowledge(
                f"chunk_{i}", f"知识内容 {i}", title=f"知识{i}", token_count=20,
            )

        handler = KnowledgeHandler(skill=FakeKnowledgeSkill)
        ctx = make_context()
        decision = make_decision("knowledge.policy", text="知识")

        with patch(
            "app.ai.reply_builders.knowledge.complete",
            new=AsyncMock(return_value="摘要内容。"),
        ):
            result = await handler.execute(decision, ctx)

        refs = result.context_update.get("last_knowledge_refs", [])
        assert len(refs) <= 5


# ══════════════════════════════════════════════
# 7. 边界情况
# ══════════════════════════════════════════════


class TestKnowledgeEdgeCases:
    """边界情况。"""

    @pytest.mark.asyncio
    async def test_empty_text(self) -> None:
        """空文本 → 提示用户描述问题。"""
        handler = KnowledgeHandler(skill=FakeKnowledgeSkill)
        ctx = make_context()
        decision = make_decision("knowledge.qa", text="")

        result = await handler.execute(decision, ctx)

        assert "描述" in result.reply or "问题" in result.reply

    @pytest.mark.asyncio
    async def test_fallback_to_last_user_message(self) -> None:
        """raw_text 为空时使用 ctx.last_user_message。"""
        FakeKnowledgeSkill.reset()
        FakeKnowledgeSkill.add_qa("qa_1", "优惠", "满减优惠。")

        handler = KnowledgeHandler(skill=FakeKnowledgeSkill)
        ctx = make_context(last_user_message="有什么优惠")
        entities: dict[str, Any] = {}
        decision = ScenarioDecision(
            scenario_id="knowledge.qa", confidence=1.0, entities=entities,
        )

        result = await handler.execute(decision, ctx)

        assert result.reply
        assert "满减" in result.reply

    @pytest.mark.asyncio
    async def test_resume_returns_no_knowledge(self) -> None:
        """resume → 返回"未查到"。"""
        from app.ai.context.pending_state import PendingState

        handler = KnowledgeHandler(skill=FakeKnowledgeSkill)
        pending = PendingState(
            scenario_id="knowledge.qa",
            step="some_step",
            graph_thread_id="thread-knowledge",
        )
        result = await handler.resume(pending, "test", make_context())
        assert "未查到" in result.reply


# ══════════════════════════════════════════════
# 8. 工具函数 + ReplyBuilder 单元测试
# ══════════════════════════════════════════════


class TestKnowledgeReplyBuilder:
    """KnowledgeReplyBuilder 回复格式。"""

    def test_qa_direct_single(self) -> None:
        items = [{"question": "有什么优惠", "answer": "满 200 减 50。"}]
        reply = KnowledgeReplyBuilder.qa_direct(items)
        assert reply == "满 200 减 50。"

    def test_qa_direct_multi(self) -> None:
        items = [
            {"question": "优惠", "answer": "满 200 减 50。"},
            {"question": "保修", "answer": "1 年保修。"},
        ]
        reply = KnowledgeReplyBuilder.qa_direct(items)
        assert "关于优惠" in reply
        assert "关于保修" in reply

    def test_qa_direct_empty(self) -> None:
        assert KnowledgeReplyBuilder.qa_direct([]) == ""

    def test_knowledge_direct(self) -> None:
        items = [{"content": "保修政策内容。"}]
        reply = KnowledgeReplyBuilder.knowledge_direct(items)
        assert "保修政策" in reply

    def test_knowledge_direct_empty(self) -> None:
        assert KnowledgeReplyBuilder.knowledge_direct([]) == ""

    def test_knowledge_summary_with_sources(self) -> None:
        items = [
            {"title": "标准保修", "content": "1 年保修。"},
            {"title": "延长保修", "content": "额外 2 年。"},
        ]
        reply = KnowledgeReplyBuilder.knowledge_summary(items, "保修政策摘要")
        assert "保修政策摘要" in reply
        assert "参考来源" in reply
        assert "标准保修" in reply
        assert "延长保修" in reply

    def test_knowledge_summary_no_duplicate_titles(self) -> None:
        items = [
            {"title": "保修", "content": "1 年。"},
            {"title": "保修", "content": "2 年。"},
        ]
        reply = KnowledgeReplyBuilder.knowledge_summary(items, "摘要")
        # 相同标题只出现一次（来源去重）
        assert reply.count("保修") == 1

    def test_no_knowledge(self) -> None:
        reply = KnowledgeReplyBuilder.no_knowledge()
        assert "未查到" in reply


class TestBuildKnowledgeRefs:
    """_build_knowledge_refs 工具函数。"""

    def test_qa_items(self) -> None:
        items = [{"id": "qa_1", "question": "优惠活动", "answer": "满减。"}]
        refs = _build_knowledge_refs(items, "qa")
        assert len(refs) == 1
        assert refs[0]["source_type"] == "qa"
        assert refs[0]["source_id"] == "qa_1"
        assert refs[0]["doc_id"] == ""
        assert "优惠活动" in refs[0]["title"]
        assert "满减" in refs[0]["content_preview"]

    def test_knowledge_items(self) -> None:
        items = [{"id": "chunk_1", "doc_id": "doc_abc", "title": "保修", "content": "保修期 1 年。"}]
        refs = _build_knowledge_refs(items, "knowledge")
        assert len(refs) == 1
        assert refs[0]["source_type"] == "document"
        assert refs[0]["source_id"] == "chunk_1"
        assert refs[0]["doc_id"] == "doc_abc"
        assert refs[0]["title"] == "保修"

    def test_empty_items(self) -> None:
        assert _build_knowledge_refs([], "qa") == []

    def test_max_five(self) -> None:
        items = [{"id": str(i), "title": f"t{i}", "content": f"c{i}"} for i in range(10)]
        refs = _build_knowledge_refs(items, "knowledge")
        assert len(refs) == 5

    def test_skip_empty_source_id(self) -> None:
        items = [{"id": "", "title": "no id"}, {"id": "valid", "title": "valid"}]
        refs = _build_knowledge_refs(items, "knowledge")
        assert len(refs) == 1
        assert refs[0]["source_id"] == "valid"


class TestPreview:
    """_preview 工具函数。"""

    def test_normal(self) -> None:
        result = _preview("Hello World", 5)
        assert result == "Hello"

    def test_shorter_than_max(self) -> None:
        result = _preview("Hi", 100)
        assert result == "Hi"

    def test_empty(self) -> None:
        assert _preview("", 10) == ""
