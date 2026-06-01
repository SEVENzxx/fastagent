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

    真实 webhook 先快速返回 200，再通过 BackgroundTasks 异步调用这里。
    异常会被捕获并创建系统通知，确保渠道故障不会被静默忽略。
    """
    started = time.perf_counter()
    logger.info(
        "开始后台处理企业微信消息：tenant_id=%s platform_id=%s external_userid=%s msg_id=%s",
        platform.tenant_id,
        platform.id,
        message.external_userid,
        message.msg_id,
    )
    try:
        await route_wecom_message(db, platform, message)
        logger.info(
            "后台处理企业微信消息完成：tenant_id=%s platform_id=%s msg_id=%s elapsed_ms=%.0f",
            platform.tenant_id,
            platform.id,
            message.msg_id,
            (time.perf_counter() - started) * 1000,
        )
    except Exception:
        logger.exception(
            "后台处理企业微信消息失败：tenant_id=%s platform_id=%s msg_id=%s",
            platform.tenant_id,
            platform.id,
            message.msg_id,
        )
        # 创建渠道异常通知，提醒管理员排查
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
