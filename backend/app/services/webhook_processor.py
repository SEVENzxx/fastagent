"""Webhook 异步处理器。

负责在 webhook 快速返回 200 后，异步完成消息路由。如果处理过程中出现异常，
会记录错误并创建系统通知，避免静默丢失客户消息。
"""

import logging
import time

from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.wecom import WeComInboundMessage
from app.models.platform import Platform
from app.services.channel_router import route_wecom_message

logger = logging.getLogger(__name__)


async def process_wecom_message(
    db: AsyncSession,
    platform: Platform,
    message: WeComInboundMessage,
) -> None:
    """处理企业微信入站消息。

    ── 处理步骤 ──
      1. 将已解密的 WeComInboundMessage 交给 channel_router
         → 联系人匹配/创建 → 会话复用/新建 → 消息落库
         → WebSocket 广播到坐席工作台 → AI 意图识别 + 回复
      2. 成功 → 记录耗时日志
      3. 失败 → 记录异常 + 创建系统通知（避免渠道故障被静默忽略）
    """
    started = time.perf_counter()
    logger.info(
        "开始后台处理企业微信消息：tenant_id=%s platform_id=%s external_userid=%s msg_id=%s",
        platform.tenant_id,
        platform.id,
        message.external_userid,
        message.msg_id,
    )

    # ── 1: 全链路路由 + AI 处理 ──
    try:
        await route_wecom_message(db, platform, message)

    # ── 2: 成功 ──
        logger.info(
            "后台处理企业微信消息完成：tenant_id=%s platform_id=%s msg_id=%s elapsed_ms=%.0f",
            platform.tenant_id,
            platform.id,
            message.msg_id,
            (time.perf_counter() - started) * 1000,
        )

    # ── 3: 失败 → 日志 + 系统通知 ──
    except Exception:
        logger.exception(
            "后台处理企业微信消息失败：tenant_id=%s platform_id=%s msg_id=%s",
            platform.tenant_id,
            platform.id,
            message.msg_id,
        )
        from app.services.operations_service import create_notification
        await create_notification(
            db,
            type="channel_error",
            tenant_id=platform.tenant_id,
            level="error",
            title="企业微信渠道消息处理异常",
            content="webhook 消息处理失败，请检查渠道配置和回调日志。",
            resource_type="platform",
            resource_id=platform.id,
        )
