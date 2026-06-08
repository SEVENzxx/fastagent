"""多轮电商会话状态管理：记录用户在浏览、选品、下单各阶段的状态。

与 PendingIntentState 的区别：
  - PendingIntentState 记录"当前缺什么意图槽位"（如等待订单号）
  - ConversationCommerceState 记录"整个会话进行到哪一步"（如正在下单中）
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Protocol


# 会话状态默认过期时间：1 小时。超过此时间用户未活跃则重置状态。
DEFAULT_CONVERSATION_STATE_TTL_SECONDS = 3600


class ConversationStage(str, Enum):
    """电商会话的阶段枚举，标识用户在购物流程中的当前位置。"""
    IDLE = "IDLE"                       # 空闲/初始状态
    PRODUCT_BROWSING = "PRODUCT_BROWSING"   # 浏览商品
    PRODUCT_SELECTED = "PRODUCT_SELECTED"   # 已选定商品
    ORDER_DRAFTING = "ORDER_DRAFTING"       # 草拟订单
    ORDER_PENDING_INFO = "ORDER_PENDING_INFO"   # 等待补充收货信息
    ORDER_PENDING_CONFIRM = "ORDER_PENDING_CONFIRM"  # 等待用户确认下单


@dataclass
class ConversationCommerceState:
    """电商会话状态数据：包含当前阶段、选中商品、待补信息等。

    每次 Agent 执行结束后由 commerce_flow 更新并持久化到 Redis。
    """
    stage: ConversationStage = ConversationStage.IDLE               # 当前会话阶段
    last_intent: str | None = None                                  # 上一轮意图
    last_recommended_products: list[dict[str, Any]] = field(default_factory=list)  # 上次推荐的商品列表
    selected_product: dict[str, Any] | None = None                  # 用户选中的商品
    pending_order_id: str | None = None                             # 待确认的订单号
    missing_slots: list[str] = field(default_factory=list)          # 还缺哪些下单信息（地址/电话等）
    last_agent_action: str | None = None                            # 上一步 Agent 做了什么
    updated_at: str | None = None                                   # 最后更新时间

    def to_dict(self) -> dict[str, Any]:
        """序列化为 JSON 兼容字典，写入 Redis。"""
        payload = asdict(self)
        payload["stage"] = self.stage.value
        if not payload.get("updated_at"):
            payload["updated_at"] = datetime.now(timezone.utc).isoformat()
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ConversationCommerceState":
        """从 JSON 字典反序列化，读取 Redis。"""
        stage_value = str(data.get("stage") or ConversationStage.IDLE.value)
        try:
            stage = ConversationStage(stage_value)
        except ValueError:
            stage = ConversationStage.IDLE
        return cls(
            stage=stage,
            last_intent=str(data["last_intent"]) if data.get("last_intent") is not None else None,
            last_recommended_products=[
                dict(item) for item in data.get("last_recommended_products", []) if isinstance(item, dict)
            ],
            selected_product=dict(data["selected_product"]) if isinstance(data.get("selected_product"), dict) else None,
            pending_order_id=str(data["pending_order_id"]) if data.get("pending_order_id") is not None else None,
            missing_slots=[str(item) for item in data.get("missing_slots", [])],
            last_agent_action=str(data["last_agent_action"]) if data.get("last_agent_action") is not None else None,
            updated_at=str(data["updated_at"]) if data.get("updated_at") is not None else None,
        )


class RedisLike(Protocol):
    """Redis 客户端的最小接口协议，便于单元测试注入 fake redis。"""
    async def get(self, name: str) -> Any: ...
    async def set(self, name: str, value: str, ex: int | None = None) -> Any: ...
    async def delete(self, *names: str) -> Any: ...


class ConversationStateStore:
    """电商会话状态的 Redis 持久化存储。

    每条会话一个 key，格式：
      conversation:{tenant_id}:{conversation_id}:commerce_state

    应用场景：
      - 用户在浏览商品阶段，ASR 帮你记住上次推荐了什么
      - 换到下单阶段，不用重新从头来，直接继承之前选中的商品
    """

    def __init__(
        self,
        redis_client: RedisLike | None = None,
        *,
        ttl_seconds: int = DEFAULT_CONVERSATION_STATE_TTL_SECONDS,
    ) -> None:
        self.redis = redis_client or self._create_redis_client()
        self.ttl_seconds = int(ttl_seconds)
        if self.ttl_seconds <= 0:
            raise ValueError("TTL 必须大于 0")

    async def get(self, tenant_id: int, conversation_id: int) -> ConversationCommerceState:
        """读取会话状态；不存在或解析失败时返回默认状态（IDLE）。"""
        raw = await self.redis.get(self._key(tenant_id, conversation_id))
        if raw is None:
            return ConversationCommerceState()
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        try:
            data = json.loads(str(raw))
        except json.JSONDecodeError:
            return ConversationCommerceState()
        if not isinstance(data, dict):
            return ConversationCommerceState()
        return ConversationCommerceState.from_dict(data)

    async def set(
        self,
        tenant_id: int,
        conversation_id: int,
        state: ConversationCommerceState,
    ) -> None:
        """保存会话状态到 Redis，同时刷新 TTL。"""
        state.updated_at = datetime.now(timezone.utc).isoformat()
        await self.redis.set(
            self._key(tenant_id, conversation_id),
            json.dumps(state.to_dict(), ensure_ascii=False, separators=(",", ":")),
            ex=self.ttl_seconds,
        )

    async def delete(self, tenant_id: int, conversation_id: int) -> None:
        """删除会话状态（会话结束或重置时调用）。"""
        await self.redis.delete(self._key(tenant_id, conversation_id))

    def _key(self, tenant_id: int, conversation_id: int) -> str:
        """生成租户隔离的 Redis key。"""
        return f"conversation:{tenant_id}:{conversation_id}:commerce_state"

    def _create_redis_client(self) -> RedisLike:
        """懒加载真实 Redis 客户端（避免测试环境 import 报错）。"""
        from app.redis_client import get_redis_client
        return get_redis_client()
