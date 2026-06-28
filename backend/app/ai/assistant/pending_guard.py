"""PendingGuard — LangGraph Pending 状态守卫。

检查顺序（优先级降序）：
  1. HUMAN: 转人工请求
  2. CANCEL: 退出信号（"算了""取消""不要了"）
  3. RESUME: 恢复 Pending Handler
"""

from __future__ import annotations

import logging
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
    "退出",
    "退出了",
    "不选了",
})


class PendingGuard:
    """LangGraph Pending 状态守卫。

    顶层不再尝试识别新意图；图中流程只能通过明确取消、转人工或正常恢复退出。
    """

    async def check(
        self,
        message: str,
        context: Any | None,
        pending: PendingState,
    ) -> PendingAction:
        """检查用户消息，返回对应的 Pending 动作。"""
        _ = context
        text = message.strip()

        if self._is_human_request(text):
            logger.info(
                "PendingGuard=HUMAN scenario=%s step=%s msg=%.30s",
                pending.scenario_id, pending.step, text,
            )
            return PendingAction.HUMAN

        if self._is_cancel_signal(text):
            logger.info(
                "PendingGuard=CANCEL scenario=%s step=%s msg=%.30s",
                pending.scenario_id, pending.step, text,
            )
            return PendingAction.CANCEL

        logger.info(
            "PendingGuard=RESUME scenario=%s step=%s msg=%.30s",
            pending.scenario_id, pending.step, text,
        )
        return PendingAction.RESUME

    @staticmethod
    def _is_human_request(text: str) -> bool:
        """检查是否为转人工请求。"""
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