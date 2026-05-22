"""Redis 连接工具"""

import redis.asyncio as aioredis

from app.config import settings


def get_redis_client() -> aioredis.Redis:
    """创建异步 Redis 客户端。"""
    return aioredis.from_url(
        settings.REDIS_URL,
        password=settings.REDIS_PASSWORD or None,
        socket_connect_timeout=2,
        socket_timeout=2,
    )


async def check_redis_connection() -> bool:
    """通过 PING 命令检测 Redis 是否连通。"""
    try:
        r = get_redis_client()
        result = await r.ping()
        await r.aclose()  # type: ignore[attr-defined]
        return result is True
    except Exception:
        return False
