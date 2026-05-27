"""Webhook 异步处理器。"""

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
    """
    started = time.perf_counter()
    logger.info(
        "开始后台处理企业微信消息：tenant_id=%s platform_id=%s external_userid=%s msg_id=%s",
        platform.tenant_id,
        platform.id,
        message.external_userid,
        message.msg_id,
    )
    await route_wecom_message(db, platform, message)
    logger.info(
        "后台处理企业微信消息完成：tenant_id=%s platform_id=%s msg_id=%s elapsed_ms=%.0f",
        platform.tenant_id,
        platform.id,
        message.msg_id,
        (time.perf_counter() - started) * 1000,
    )
