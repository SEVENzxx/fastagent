"""Webhook 异步处理器。"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.wecom import WeComInboundMessage
from app.models.platform import Platform
from app.services.channel_router import route_wecom_message


async def process_wecom_message(
    db: AsyncSession,
    platform: Platform,
    message: WeComInboundMessage,
) -> None:
    """处理企业微信入站消息。

    真实 webhook 先快速返回 200，再通过 BackgroundTasks 异步调用这里。
    """
    await route_wecom_message(db, platform, message)
