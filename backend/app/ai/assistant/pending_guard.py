"""PendingGuard — Pending 状态守卫。

检查顺序（优先级降序）：
  1. HUMAN: 转人工请求
  2. CANCEL: 退出信号（"算了""取消""不要了"）
  3. NEW_INTENT: 通过场景识别判断意图转换
  4. RESUME: 都不是，恢复 Pending Handler
"""

from __future__ import annotations

import logging
from typing import Any

from app.ai.context.pending_state import PendingAction, PendingState
from app.ai.recognition.pipeline import RecognitionPipeline

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
    """Pending 状态守卫。

    根据用户消息判断 Pending 状态下如何处理。
    严格按 HUMAN → CANCEL → NEW_INTENT → RESUME 顺序检查。
    """

    async def check(
        self,
        message: str,
        context: Any | None,
        pending: PendingState,
        recognition: RecognitionPipeline | None = None,
    ) -> PendingAction:
        """检查用户消息，返回对应的 Pending 动作。

        Args:
            message: 用户消息原文
            context: 当前会话上下文
            pending: 当前 Pending 状态
            recognition: 场景识别管线，传入时通过场景识别判断 NEW_INTENT

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

        # 2.5 Graph 模式保护：流输入（地址/数量/确认）不进入 NEW_INTENT 检测
        if pending.mode == "graph":
            logger.info(
                "PendingGuard=graph_mode scenario=%s step=%s msg=%.30s → RESUME",
                pending.scenario_id, pending.step, text,
            )
            return PendingAction.RESUME

        # 3. NEW_INTENT: 通过场景识别判断意图转换
        if recognition is not None:
            is_new = await self._is_new_intent(text, pending, recognition, context)
            if is_new:
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
    async def _is_new_intent(
        text: str,
        pending: PendingState,
        recognition: RecognitionPipeline,
        context: Any | None = None,
    ) -> bool:
        """通过场景识别判断用户消息是否为当前 Pending 之外的新意图。"""
        try:
            decision = await recognition.recognize(text, context)
            return decision.scenario_id != pending.scenario_id
        except Exception:
            logger.warning(
                "PendingGuard 场景识别失败，降级为 RESUME scenario=%s",
                pending.scenario_id,
            )
            return False
