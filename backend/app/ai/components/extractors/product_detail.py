"""ProductDetailExtractor — 商品详情场景的参数抽取器。

修复核心 bug：用户追问"这款产品适合带着跑步吗？"时，
_handle_detail 会把整句当 product_name 去搜索导致无结果。

解决方式：
  1. 检测指代引用（这个/它/那款）→ 直接取上下文焦点商品
  2. 尝试 LLM 提取商品名
  3. 上下文回填缺失字段
  4. 分离出用户真正的问题（question）和商品引用
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.ai.components.extractors.base import ExtractionResult, ScenarioExtractor
from app.ai.context.session_context import SessionContext
from app.ai.llm.gateway import LLMUseCase, complete
from app.ai.prompts.product_extract import PRODUCT_DETAIL_EXTRACT_PROMPT

logger = logging.getLogger(__name__)

# 指代检测前缀（与 ProductReferenceResolver 保持一致）
_DEIXIS_PREFIXES: tuple[str, ...] = (
    "这个", "这款", "它", "它们", "那个", "那款",
    "刚才那个", "刚刚那个", "刚才那款", "刚刚那款",
)


def _is_deixis(text: str) -> bool:
    """判断是否包含指代引用。"""
    stripped = text.strip()
    if not stripped:
        return False
    return any(stripped.startswith(p) for p in _DEIXIS_PREFIXES)


class ProductDetailExtractor(ScenarioExtractor):
    """商品详情参数抽取器。

    从用户原文 + SessionContext 中解析出 product_id，
    用于 _handle_detail / _detail_by_id。
    """

    async def extract(
        self,
        text: str,
        context: SessionContext,
        tenant_id: int,
        **kwargs: Any,
    ) -> ExtractionResult:
        """解析用户消息中的商品引用。

        优先级：
          1. 指代引用 + 上下文焦点 → product_id
          2. LLM 提取显式商品名 → 搜索确认
          3. 上下文回填 last_focus_product_id
        """
        stripped = text.strip()
        if not stripped:
            return ExtractionResult(need_clarification=True, reason="消息为空")

        # ── 1: 指代引用 → 直接走上下文 ──
        if _is_deixis(stripped):
            pid = context.last_focus_product_id or context.last_product_id
            if pid is not None:
                return ExtractionResult(
                    entities={
                        "product_id": int(pid),
                        "product_name": context.last_product_name or "",
                        "query": stripped,
                    },
                    reason=f"指代解析：{stripped[:20]}",
                )
            return ExtractionResult(
                missing_fields=["product_id"],
                need_clarification=True,
                reason="指代引用但无上下文焦点商品",
            )

        # ── 2: LLM 抽取 ──
        llm_entities = await self._llm_extract(stripped, context)

        product_name = (llm_entities.get("product_name") or "").strip()
        is_follow_up = llm_entities.get("is_follow_up", False)
        question = (llm_entities.get("question") or "").strip()

        # 构建最终 entities
        entities: dict[str, Any] = {}
        if question:
            entities["query"] = question
        else:
            entities["query"] = stripped

        # ── 3: 上下文回填 ──
        if product_name:
            entities["product_name_hint"] = product_name

        if is_follow_up or not product_name:
            pid = context.last_focus_product_id or context.last_product_id
            if pid is not None:
                entities["product_id"] = int(pid)
                entities["product_name"] = context.last_product_name or ""
                return ExtractionResult(
                    entities=entities,
                    reason=f"LLM 判断为追问，回填上下文商品 {pid}",
                )

        # ── 4: 无商品引用，标记缺失 ──
        if not product_name:
            entities["product_name_hint"] = stripped[:100]
            return ExtractionResult(
                entities=entities,
                missing_fields=["product_id"],
                need_clarification=True,
                reason="LLM 未提取到显式商品名",
                candidates=[{"name": stripped, "source": "text"}],
            )

        return ExtractionResult(
            entities=entities,
            missing_fields=["product_id"],
            reason=f"LLM 提取商品名：{product_name}，需搜索确认",
        )

    # ── 内部方法 ──

    @staticmethod
    async def _llm_extract(text: str, context: SessionContext) -> dict[str, Any]:
        """调用 LLM 抽取商品引用参数。"""
        messages = [
            {"role": "system", "content": PRODUCT_DETAIL_EXTRACT_PROMPT},
            {
                "role": "user",
                "content": (
                    f"用户消息：{text}\n"
                    f"上下文焦点商品：{context.last_product_name or '无'}"
                ),
            },
        ]
        for attempt in (1, 2):
            try:
                raw = await complete(
                    LLMUseCase.PRODUCT_EXTRACT,
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
                return json.loads(content)
            except json.JSONDecodeError:
                logger.debug("LLM 商品详情抽取格式异常: %s", (raw or "")[:80])
                return {}
            except Exception as exc:
                if attempt == 1:
                    logger.debug("LLM 商品详情抽取异常，重试一次: %s", exc)
                    continue
                logger.warning("LLM 商品详情抽取最终失败: %s", exc)
                return {}
