"""ContextResolver — 上下文连贯解析器。

在 RecognitionPipeline 之前执行，处理三类上下文依赖的输入：
  1. 裸序号（"1"/"第一个"）→ last_visible_products → product.detail
  2. 指代引用（"这款"/"它"/"那个"）→ last_focus_product_id → 意图分类
  3. 省略型（"适合跑步吗"）→ last_focus_product_id + 关键词 → product.usage

输出 ContextResolution(scenario_id, entities, confidence) 或 None。

与 RecognitionPipeline 的职责边界：
  - ContextResolver 只处理上下文延续，不做新意图识别
  - ContextResolver 不解析 pending 状态（那是 PendingGuard 的事）
  - ContextResolver 只做规则匹配（正则/关键词），不调 LLM 或向量
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from app.ai.context.session_context import SessionContext

logger = logging.getLogger(__name__)

# ── 序号解析 ──

_CN_NUM_MAP: dict[str, int] = {
    "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
    "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
}
_RE_ORDINAL_CN = re.compile(r"第\s*([一二两三四五六七八九十\d]+)\s*[款个]")
_RE_BARE_NUMBER = re.compile(r"^\s*(\d+)\s*$")

# ── 指代检测 ──

_DEIXIS_PREFIXES: tuple[str, ...] = (
    "这个", "这款", "它", "它们", "那个", "那款",
    "刚才那个", "刚刚那个", "刚才那款", "刚刚那款",
)

# ── 用法/适用性意图关键词（触发 product.usage）──

_USAGE_KEYWORDS: frozenset[str] = frozenset({"适合", "用来", "用于"})

# ── 购买意图关键词（含有这些词时不走序号解析，让 RecognitionPipeline 处理）──

_ORDER_KEYWORDS: frozenset[str] = frozenset({"下单", "买", "订", "购买"})


def _parse_ordinal(text: str) -> int | None:
    """从文本中解析序号，支持中文和裸数字。"""
    stripped = text.strip()
    # 裸数字
    m = _RE_BARE_NUMBER.fullmatch(stripped)
    if m:
        return int(m.group(1))
    # 第N款/个
    m = _RE_ORDINAL_CN.search(text)
    if m:
        raw = m.group(1).strip()
        return int(raw) if raw.isdigit() else _CN_NUM_MAP.get(raw)
    return None


def _is_deixis(text: str) -> bool:
    """判断是否以指代词开头。"""
    stripped = text.strip()
    if not stripped:
        return False
    return any(stripped.startswith(p) for p in _DEIXIS_PREFIXES)


def _contains_deixis(text: str) -> bool:
    """判断文本中是否包含指代词（句中任意位置）。

    用于"详细介绍这款耳机"等句中指代场景。
    不含购买关键词时走 product.detail/usage 上下文解析。
    """
    stripped = text.strip()
    if not stripped:
        return False
    return any(p in stripped for p in _DEIXIS_PREFIXES)


def _is_usage_question(text: str) -> bool:
    """判断是否为用法/适用性提问。"""
    return any(kw in text for kw in _USAGE_KEYWORDS)


def _classify_context_intent(text: str) -> str:
    """对上下文消息做意图分类（规则关键词）。

    返回 scenario_id：product.detail / product.usage。
    """
    if _is_usage_question(text):
        return "product.usage"
    return "product.detail"


@dataclass
class ContextResolution:
    """上下文解析结果。"""
    scenario_id: str
    entities: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.92


class ContextResolver:
    """上下文连贯解析器。

    在 RecognitionPipeline 之前执行。如果解析成功，跳过场景识别直接路由 Handler。
    """

    async def resolve(
        self,
        text: str,
        context: SessionContext,
    ) -> ContextResolution | None:
        """解析用户消息中的上下文依赖。

        Args:
            text: 用户原始消息。
            context: 当前会话上下文。

        Returns:
            ContextResolution 或 None（无法解析，交给 RecognitionPipeline）。
        """
        stripped = text.strip()
        if not stripped:
            return None

        # ── 1: 裸序号（"1"/"第一个"）→ last_visible_products → product.detail / product.catalog ──
        ordinal = _parse_ordinal(stripped)
        if ordinal is not None and context.last_visible_products:
            # 含有购买意图关键词的序号引用（如"给我下单第一款"），不走上下文解析
            if any(kw in stripped for kw in _ORDER_KEYWORDS):
                logger.debug(
                    "【ContextResolver】序号文本含购买关键词，跳过上下文解析: %s", stripped[:30],
                )
                return None
            products = context.last_visible_products
            if 1 <= ordinal <= len(products):
                target = products[ordinal - 1]

                # 分类序号选择 → product.catalog（下钻）
                if target.get("is_category"):
                    logger.info(
                        "【ContextResolver】分类序号选择 ordinal=%s category_id=%s name=%s",
                        ordinal, target.get("product_id"), target.get("name"),
                    )
                    return ContextResolution(
                        scenario_id="product.catalog",
                        entities={
                            "category_id": int(target["product_id"]),
                            "category_name": target.get("name", ""),
                            "reason": "上下文分类序号选择",
                        },
                    )

                # 商品序号选择 → product.detail
                logger.info(
                    "【ContextResolver】裸序号解析 ordinal=%s target_id=%s target_name=%s",
                    ordinal, target.get("product_id"), target.get("name"),
                )
                return ContextResolution(
                    scenario_id="product.detail",
                    entities={
                        "product_id": int(target["product_id"]),
                        "product_name": target.get("name", ""),
                        "reason": "上下文序号解析",
                    },
                )
            # 超出范围不解析（让 RecognitionPipeline 处理）
            logger.debug(
                "【ContextResolver】序号 %s 超出 last_visible_products 范围（共 %s 个）",
                ordinal, len(products),
            )
            return None

        # ── 2: 指代引用（"这款"/"它"/"那个"）→ last_focus_product_id ──
        if _is_deixis(stripped):
            pid = context.last_focus_product_id
            if pid is not None:
                intent = _classify_context_intent(stripped)
                logger.info(
                    "【ContextResolver】指代解析 scenario=%s product_id=%s text=%s",
                    intent, pid, stripped[:20],
                )
                return ContextResolution(
                    scenario_id=intent,
                    entities={
                        "product_id": int(pid),
                        "product_name": context.last_product_name or "",
                        "reason": f"上下文指代解析：{stripped[:20]}",
                    },
                )
            # 指代但没有焦点商品 → 不解析
            return None

        # ── 2.5: 句中指代（"详细介绍这款耳机"）→ last_focus_product_id ──
        if (
            _contains_deixis(stripped)
            and context.last_focus_product_id is not None
            and not any(kw in stripped for kw in _ORDER_KEYWORDS)
        ):
            pid = int(context.last_focus_product_id)
            intent = _classify_context_intent(stripped)
            logger.info(
                "【ContextResolver】句中指代解析 scenario=%s product_id=%s text=%s",
                intent, pid, stripped[:20],
            )
            return ContextResolution(
                scenario_id=intent,
                entities={
                    "product_id": pid,
                    "product_name": context.last_product_name or "",
                    "reason": f"上下文句中指代解析：{stripped[:20]}",
                },
            )

        # ── 3: 省略型（"适合跑步吗"）→ last_focus_product_id + 关键词 ──
        if context.last_focus_product_id is not None and _is_usage_question(stripped):
            pid = int(context.last_focus_product_id)
            logger.info(
                "【ContextResolver】省略型用法解析 product_id=%s text=%s",
                pid, stripped[:20],
            )
            return ContextResolution(
                scenario_id="product.usage",
                entities={
                    "product_id": pid,
                    "product_name": context.last_product_name or "",
                    "reason": "上下文省略型用法解析",
                },
            )

        return None
