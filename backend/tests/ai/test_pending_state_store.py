"""PendingStateStore 测试。"""

import json

import pytest

from app.services.ai.intent.pending_state_store import PendingStateStore
from app.services.ai.intent.types import PendingIntentState


class FakeRedis:
    """测试用最小 Redis fake。"""

    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.expires: dict[str, int] = {}

    async def get(self, name: str):
        return self.values.get(name)

    async def set(self, name: str, value: str, ex: int | None = None):
        self.values[name] = value
        if ex is not None:
            self.expires[name] = ex
        return True

    async def delete(self, *names: str):
        count = 0
        for name in names:
            if name in self.values:
                count += 1
            self.values.pop(name, None)
            self.expires.pop(name, None)
        return count

    async def ttl(self, name: str):
        return self.expires.get(name, -2)


@pytest.mark.asyncio
async def test_pending_state_store_roundtrip_with_ttl():
    redis = FakeRedis()
    store = PendingStateStore(redis, ttl_seconds=600)

    state = PendingIntentState(
        intent="order_status",
        skill="order_status",
        required_entities=["order_no"],
        filled_entities={},
        last_prompt="麻烦提供你的订单号",
    )
    await store.set(tenant_id=1, conversation_id=2, state=state)

    loaded = await store.get(tenant_id=1, conversation_id=2)

    assert loaded is not None
    assert loaded.intent == "order_status"
    assert loaded.required_entities == ["order_no"]
    assert loaded.last_prompt == "麻烦提供你的订单号"
    assert loaded.created_at is not None
    assert await store.ttl(1, 2) == 600


@pytest.mark.asyncio
async def test_pending_state_store_uses_tenant_scoped_key():
    redis = FakeRedis()
    store = PendingStateStore(redis)
    state = PendingIntentState(intent="order_status", skill="order_status", required_entities=["order_no"])

    await store.set(tenant_id=1, conversation_id=2, state=state)

    assert await store.get(tenant_id=2, conversation_id=2) is None
    assert "conversation:1:2:pending_state" in redis.values


@pytest.mark.asyncio
async def test_pending_state_store_delete_removes_state():
    redis = FakeRedis()
    store = PendingStateStore(redis)
    state = PendingIntentState(intent="order_status", skill="order_status", required_entities=["order_no"])

    await store.set(tenant_id=1, conversation_id=2, state=state)
    await store.delete(tenant_id=1, conversation_id=2)

    assert await store.get(tenant_id=1, conversation_id=2) is None


@pytest.mark.asyncio
async def test_pending_state_store_bad_json_returns_none():
    redis = FakeRedis()
    store = PendingStateStore(redis)
    redis.values["conversation:1:2:pending_state"] = "{bad-json"

    assert await store.get(tenant_id=1, conversation_id=2) is None


@pytest.mark.asyncio
async def test_pending_state_store_rejects_missing_required_fields():
    redis = FakeRedis()
    store = PendingStateStore(redis)
    redis.values["conversation:1:2:pending_state"] = json.dumps({"skill": "order_status"})

    assert await store.get(tenant_id=1, conversation_id=2) is None
