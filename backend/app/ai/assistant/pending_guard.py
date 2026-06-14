"""PendingGuard — Pending 状态守卫。

检查顺序（优先级降序）：
  1. HUMAN: 转人工请求
  2. CANCEL: 退出信号（"算了""取消""不要了"）
  3. NEW_INTENT: 明显的新意图
  4. RESUME: 都不是，恢复 Pending Handler

Pending 防死循环规则：
  转人工优先级最高，因为"转人工"是用户明确的新诉求，
  不能被"取消"类词误吞。
"""

from __future__ import annotations

import logging
import re
from typing import Any

from app.ai.context.pending_state import PendingAction, PendingState

logger = logging.getLogger(__name__)

# ══ 转人工关键词（最高优先级）══
_HUMAN_KEYWORDS: tuple[str, ...] = (
    "转人工",
    "人工客服",
    "真人客服",
    "找客服",
    "我要人工",
    "给我转人工",
)

# ══ 取消/退出信号 ══
# 精确短句匹配，不走 startswith，避免误吞"取消订单"
_CANCEL_EXACT: frozenset[str] = frozenset({
    "算了",
    "算了吧",
    "不要了",
    "不弄了",
    "不问了",
    "不用了",
    "不了",
    "取消一下",
    "取消这次操作",
    "取消当前操作",
})

# ══ 明显新意图关键词 ══
_NEW_INTENT_PATTERNS: list[re.Pattern] = [
    # 商品浏览/搜索
    re.compile(r"(?:有什么|有哪些|看看|推荐|介绍).*(?:商品|产品|东西)"),
    re.compile(r"搜索.*"),
    re.compile(r"找.*(?:商品|产品|东西)"),
    # 查订单
    re.compile(r"(?:查|看|查查).*订单"),
    re.compile(r"我的订单"),
    # 优惠/政策
    re.compile(r"(?:有什么|有.*吗).*(?:优惠|活动|促销|折扣|政策|福利)"),
    # 取消订单（显式订单操作，不是退出当前 Pending）
    re.compile(r"取消订单"),
    re.compile(r"订单取消"),
    re.compile(r"取消我的订单"),
]


class PendingGuard:
    """Pending 状态守卫。

    根据用户消息判断 Pending 状态下如何处理。
    严格按 HUMAN → CANCEL → NEW_INTENT → RESUME 顺序检查。
    """

    async def check(
        self,
        message: str,
        context: Any | None,
        pending: PendingState,
    ) -> PendingAction:
        """检查用户消息，返回对应的 Pending 动作。

        Args:
            message: 用户消息原文
            context: 当前会话上下文
            pending: 当前 Pending 状态

        Returns:
            PendingAction 枚举值
        """
        text = message.strip()

        # 1. HUMAN: 转人工请求（最高优先级）
        if self._is_human_request(text):
            logger.info(
                "PendingGuard=HUMAN scenario=%s step=%s msg=%.30s",
                pending.scenario_id, pending.step, text,
            )
            return PendingAction.HUMAN

        # 2. CANCEL: 退出/取消信号
        if self._is_cancel_signal(text):
            logger.info(
                "PendingGuard=CANCEL scenario=%s step=%s msg=%.30s",
                pending.scenario_id, pending.step, text,
            )
            return PendingAction.CANCEL

        # 3. NEW_INTENT: 明显的新意图
        if self._is_new_intent(text):
            logger.info(
                "PendingGuard=NEW_INTENT scenario=%s step=%s msg=%.30s",
                pending.scenario_id, pending.step, text,
            )
            return PendingAction.NEW_INTENT

        # 4. RESUME: 都不是，恢复 Pending Handler
        logger.info(
            "PendingGuard=RESUME scenario=%s step=%s msg=%.30s",
            pending.scenario_id, pending.step, text,
        )
        return PendingAction.RESUME

    # ──────────────────────────────────────
    # 内部检查方法
    # ──────────────────────────────────────

    @staticmethod
    def _is_human_request(text: str) -> bool:
        """检查是否为转人工请求。

        精确短语匹配，避免"人工智能"等误触发。
        单独"人工"也视为转人工请求（精确匹配）。
        """
        if text == "人工":
            return True
        return any(kw in text for kw in _HUMAN_KEYWORDS)

    @staticmethod
    def _is_cancel_signal(text: str) -> bool:
        """检查是否为取消/退出信号。

        精确短语匹配，不匹配"取消订单""订单取消"等显式订单操作。
        """
        if text in _CANCEL_EXACT:
            return True
        # 单独"取消"是退出当前 Pending 的信号
        if text == "取消":
            return True
        # "不买了""不想要了"明确放弃当前操作
        if text in ("不买了", "不想要了", "先不要了"):
            return True
        return False

    @staticmethod
    def _is_new_intent(text: str) -> bool:
        """检查是否为明显的新意图。"""
        for pattern in _NEW_INTENT_PATTERNS:
            if pattern.search(text):
                return True
        return False
