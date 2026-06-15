"""持久化幂等服务 — Redis SET NX 原子占位 + 内存降级。

写入顺序：
  1. setnx(key, placeholder) —— 原子占位，成功则当前请求获得执行权
  2. 执行写操作
  3. set(key, result) —— 覆盖为完整结果

读顺序：
  1. get(key) —— 读取已有结果（占位阶段或已完成）
  2. setnx 失败 → 读已有结果，不再走写路径
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.common.constants.config import IDEMPOTENCY_TTL

logger = logging.getLogger(__name__)

_fallback_store: dict[str, dict[str, Any]] = {}
_fallback_locks: set[str] = set()

# 内存占位值（setnx 用）
_PLACEHOLDER: dict[str, Any] = {}


class IdempotencyService:
    """幂等服务，Redis → 内存 dict 降级。"""

    def __init__(self, prefix: str = "idempotency", default_ttl: int = IDEMPOTENCY_TTL) -> None:
        self._prefix = prefix
        self._default_ttl = default_ttl
        self._redis: Any = None
        self._in_memory = False

    async def _get_redis(self) -> Any:
        if self._redis is None and not self._in_memory:
            try:
                from app.integrations.redis_client import get_redis_client

                self._redis = get_redis_client()
            except Exception:
                logger.warning("Idempotency: Redis 不可用，降级到内存")
                self._in_memory = True
        return self._redis if not self._in_memory else None

    def _make_key(self, key: str) -> str:
        return f"{self._prefix}:{key}"

    async def get(self, key: str) -> dict[str, Any] | None:
        redis = await self._get_redis()
        if redis is not None:
            try:
                raw = await redis.get(self._make_key(key))
                if raw:
                    return json.loads(raw)
                return None
            except Exception:
                logger.warning("Idempotency: Redis get 失败，降级到内存: key=%s", key[:16])
                self._in_memory = True
        return _fallback_store.get(self._make_key(key))

    async def set(
        self,
        key: str,
        value: dict[str, Any],
        ttl: int | None = None,
    ) -> None:
        redis = await self._get_redis()
        if redis is not None:
            try:
                await redis.set(
                    self._make_key(key),
                    json.dumps(value, default=str),
                    ex=ttl or self._default_ttl,
                )
                return
            except Exception:
                logger.warning("Idempotency: Redis set 失败，降级到内存: key=%s", key[:16])
                self._in_memory = True
        _fallback_store[self._make_key(key)] = value

    async def setnx(
        self,
        key: str,
        value: dict[str, Any],
        ttl: int | None = None,
    ) -> bool:
        """原子占位：key 不存在时设置并返回 True，已存在时返回 False。"""
        redis = await self._get_redis()
        if redis is not None:
            try:
                ok = await redis.set(
                    self._make_key(key),
                    json.dumps(value, default=str),
                    ex=ttl or self._default_ttl,
                    nx=True,  # Only set if not exists
                )
                return ok is not None
            except Exception:
                logger.warning("Idempotency: Redis setnx 失败，降级到内存: key=%s", key[:16])
                self._in_memory = True

        # 内存降级：无锁 setdefault 语义
        mk = self._make_key(key)
        if mk in _fallback_store:
            return False
        _fallback_store[mk] = value
        return True

    async def delete(self, key: str) -> None:
        redis = await self._get_redis()
        if redis is not None:
            try:
                await redis.delete(self._make_key(key))
                return
            except Exception:
                logger.warning("Idempotency: Redis delete 失败: key=%s", key[:16])
        _fallback_store.pop(self._make_key(key), None)

    @classmethod
    def clear_fallback(cls) -> None:
        _fallback_store.clear()


# 模块级单例
order_idempotency = IdempotencyService(prefix="idempotency:order", default_ttl=IDEMPOTENCY_TTL)
