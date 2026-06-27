"""测试 IdempotencyService — Redis 路径降级、setnx 原子语义。"""

from __future__ import annotations

from typing import Any
from unittest.mock import ANY, patch

import pytest

from app.ai.services.idempotency import IdempotencyService


class FakeRedis:
    """Fake Redis 客户端，记录所有调用。"""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.calls: list[tuple[str, ...]] = []

    async def get(self, key: str) -> str | None:
        self.calls.append(("get", key))
        return self.store.get(key)

    async def set(
        self,
        key: str,
        value: str,
        ex: int | None = None,
        nx: bool = False,
    ) -> str | None:
        self.calls.append(("set", key, value[:20], ex, nx))
        if nx and key in self.store:
            return None
        self.store[key] = value
        return "OK"

    async def delete(self, key: str) -> int:
        self.calls.append(("delete", key))
        return self.store.pop(key, None) is not None


@pytest.fixture
def fake_redis() -> FakeRedis:
    return FakeRedis()


@pytest.fixture
def service(fake_redis: FakeRedis) -> IdempotencyService:
    svc = IdempotencyService(prefix="test", default_ttl=3600)
    svc._redis = fake_redis
    svc._in_memory = False
    return svc


class TestIdempotencyServiceSetnx:
    """setnx 原子占位语义 + Redis 调用验证。"""

    async def test_setnx_first_call_claims(self, service: IdempotencyService, fake_redis: FakeRedis) -> None:
        """首次 setnx 应返回 True。"""
        claimed = await service.setnx("key1", {"status": "processing"})
        assert claimed is True

    async def test_setnx_second_call_returns_false(self, service: IdempotencyService, fake_redis: FakeRedis) -> None:
        """重复 setnx 应返回 False。"""
        c1 = await service.setnx("key1", {"status": "processing"})
        c2 = await service.setnx("key1", {"status": "processing"})
        assert c1 is True
        assert c2 is False

    async def test_setnx_calls_redis_set_nx_ex(self, service: IdempotencyService, fake_redis: FakeRedis) -> None:
        """setnx 应调用 Redis set() 带 nx=True 和 ex=default_ttl。"""
        await service.setnx("mykey", {"status": "processing"})
        matching = [
            c for c in fake_redis.calls
            if c[0] == "set" and "mykey" in str(c[1])
        ]
        assert len(matching) == 1
        _call = matching[0]
        assert _call[4] is True  # nx=True
        assert _call[3] == 3600  # ex=ttl

    async def test_setnx_calls_redis_delete(self, service: IdempotencyService, fake_redis: FakeRedis) -> None:
        """set 后 delete 应传递到 Redis。"""
        await service.setnx("delkey", {"status": "processing"})
        await service.delete("delkey")
        assert ("delete", service._make_key("delkey")) in fake_redis.calls


class TestIdempotencyServiceFallback:
    """Redis 不可用时的内存降级。"""

    async def test_fallback_setnx(self) -> None:
        """Redis 降级后 setnx 应仍正常工作。"""
        svc = IdempotencyService(prefix="test_fb", default_ttl=3600)
        svc._in_memory = True

        c1 = await svc.setnx("k", {"status": "processing"})
        assert c1 is True

        c2 = await svc.setnx("k", {"status": "processing"})
        assert c2 is False

    async def test_fallback_set_get(self) -> None:
        """Redis 降级后 set + get 应正常工作。"""
        svc = IdempotencyService(prefix="test_fb", default_ttl=3600)
        svc._in_memory = True

        await svc.set("k", {"status": "completed", "order_id": "123"})
        val = await svc.get("k")
        assert val is not None
        assert val["status"] == "completed"
        assert val["order_id"] == "123"

    async def test_fallback_delete(self) -> None:
        """Redis 降级后 delete 应正常工作。"""
        svc = IdempotencyService(prefix="test_fb", default_ttl=3600)
        svc._in_memory = True

        await svc.set("k", {"status": "completed"})
        assert await svc.get("k") is not None
        await svc.delete("k")
        assert await svc.get("k") is None

    async def test_fallback_ttl_expires_key(self) -> None:
        """Redis 降级后，内存 key 也应遵守 TTL。"""
        svc = IdempotencyService(prefix="test_fb", default_ttl=3600)
        svc._in_memory = True

        with patch("app.ai.services.idempotency.time.monotonic", side_effect=[100.0, 101.1]):
            await svc.set("ttl_key", {"status": "processing"}, ttl=1)
            assert await svc.get("ttl_key") is None

    async def test_fallback_clear(self) -> None:
        """clear_fallback 类方法应清空内存存储。"""
        svc = IdempotencyService(prefix="test_fb", default_ttl=3600)
        svc._in_memory = True

        await svc.set("a", {"v": 1})
        await svc.set("b", {"v": 2})
        IdempotencyService.clear_fallback()
        assert await svc.get("a") is None
        assert await svc.get("b") is None


class TestIdempotencyServiceKeyPrefix:
    """key 前缀隔离。"""

    async def test_diff_prefix_isolated(self) -> None:
        """不同 prefix 的 key 应隔离。"""
        svc1 = IdempotencyService(prefix="p1", default_ttl=3600)
        svc2 = IdempotencyService(prefix="p2", default_ttl=3600)
        svc1._in_memory = True
        svc2._in_memory = True

        c1 = await svc1.setnx("k", {"status": "processing"})
        c2 = await svc2.setnx("k", {"status": "processing"})
        assert c1 is True
        assert c2 is True  # 不同 prefix，不应冲突
