"""用量计量服务 — ContextVar 隔离 + Token 估算 + 成本计算 + Redis 缓冲写入。"""

from __future__ import annotations

import asyncio
import json
import logging
from contextvars import ContextVar
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.conversation import Conversation, Message
from app.models.image import Image
from app.models.knowledge_doc import KnowledgeDoc
from app.models.llm_config import LLMConfig
from app.models.order import Order
from app.models.tenant import Tenant
from app.models.usage import LLMUsageLog

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class UsageContext:
    """LLM 调用计量上下文，由 ContextVar 按 asyncio Task 隔离。"""
    tenant_id: int
    conversation_id: int | None = None
    message_id: int | None = None
    source: str = "ai_pipeline"


_usage_context: ContextVar[UsageContext | None] = ContextVar("llm_usage_context", default=None)

# Redis 缓冲队列 key
_USAGE_QUEUE_KEY = "fastagent:usage:queue"

# 后台 flush worker
_flush_task: asyncio.Task | None = None
_flush_interval = 3  # 秒


def bind_usage_context(
    *,
    tenant_id: int,
    conversation_id: int | None = None,
    message_id: int | None = None,
    source: str = "ai_pipeline",
) -> None:
    """绑定当前 asyncio Task 的用量上下文，后续 LLM 调用自动记账到该租户。"""
    _usage_context.set(UsageContext(
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        message_id=message_id,
        source=source,
    ))


# ═══════════════════════════════════════════════════════════════════════
# Redis 缓冲队列 → 后台批量写 DB
# ═══════════════════════════════════════════════════════════════════════

_redis = None


async def _get_redis():
    global _redis
    if _redis is not None:
        return _redis
    try:
        import redis.asyncio as aioredis
        from app.config import settings as app_settings
        redis_url = app_settings.REDIS_URL or "redis://localhost:6379/0"
        _redis = aioredis.from_url(redis_url, decode_responses=True)
        await _redis.ping()
        logger.info("Usage Redis buffer connected: %s", redis_url)
    except Exception:
        logger.warning("Usage Redis 不可用，用量日志降级为同步写 DB")
        _redis = None
    return _redis


async def start_usage_flush_worker() -> None:
    """启动后台 worker，定期消费 Redis 队列并批量写 DB。"""
    global _flush_task
    if _flush_task is not None and not _flush_task.done():
        return

    _flush_task = asyncio.create_task(_flush_loop())
    logger.info("Usage flush worker started (interval=%ss)", _flush_interval)


async def _flush_loop() -> None:
    """后台循环：批量拉取 Redis 队列，解析 JSON，批量 insert 到 DB。"""
    from app.integrations.database import AsyncSessionLocal

    while True:
        await asyncio.sleep(_flush_interval)
        redis = await _get_redis()
        if redis is None:
            continue

        # 批量拉取（最多 100 条/次）
        items: list[str] = []
        try:
            for _ in range(100):
                raw = await redis.rpop(_USAGE_QUEUE_KEY)
                if raw is None:
                    break
                items.append(raw)
        except Exception:
            logger.exception("Usage Redis 拉取失败")
            continue

        if not items:
            continue

        try:
            async with AsyncSessionLocal() as db:
                for raw in items:
                    await _insert_from_json(db, json.loads(raw))
                await db.commit()
            logger.debug("Usage flush: %s 条批量写入完成", len(items))
        except Exception:
            logger.exception("Usage 批量写 DB 失败，%s 条丢失", len(items))


async def _insert_from_json(db: AsyncSession, data: dict) -> None:
    """从 JSON 构造 LLMUsageLog，补充定价信息和成本计算后 add 到 session。"""
    # 查 LLM 配置和定价
    config = await db.scalar(
        select(LLMConfig).join(
            Tenant, Tenant.selected_llm_config_id == LLMConfig.id
        ).where(Tenant.id == data["tenant_id"])
    )
    pricing = config.pricing if config and isinstance(config.pricing, dict) else {}
    input_rate = Decimal(str(pricing.get("prompt_per_1k", 0)))
    output_rate = Decimal(str(pricing.get("completion_per_1k", 0)))

    prompt_tokens = data["prompt_tokens"]
    completion_tokens = data["completion_tokens"]
    cost = (Decimal(prompt_tokens) * input_rate + Decimal(completion_tokens) * output_rate) / Decimal(1000)

    item = LLMUsageLog(
        tenant_id=data["tenant_id"],
        llm_config_id=config.id if config else None,
        conversation_id=data.get("conversation_id"),
        message_id=data.get("message_id"),
        source=data.get("source", "ai_pipeline"),
        model=data["model"],
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=data["total_tokens"],
        cost=cost,
        latency_ms=data.get("latency_ms", 0),
        success=data.get("success", True),
        error_message=data.get("error_message"),
    )
    db.add(item)


def estimate_tokens(text: str) -> int:
    """保守 Token 估算：max(1, (字符数+3)//4)。
    """
    return max(1, (len(str(text or "")) + 3) // 4)


async def record_current_usage(
    *,
    model: str,
    source: str,
    prompt_text: str,
    completion_text: str,
    latency_ms: int,
    success: bool = True,
    error_message: str | None = None,
) -> None:
    """记录一条 LLM 用量日志 — Redis 缓冲优先，不可用时降级同步写 DB。"""
    context = _usage_context.get()
    if context is None:
        return

    prompt_tokens = estimate_tokens(prompt_text)
    completion_tokens = estimate_tokens(completion_text) if completion_text else 0

    payload = {
        "tenant_id": context.tenant_id,
        "conversation_id": context.conversation_id,
        "message_id": context.message_id,
        "source": source or context.source,
        "model": model,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
        "latency_ms": latency_ms,
        "success": success,
        "error_message": error_message,
    }

    redis = await _get_redis()
    if redis is not None:
        try:
            await redis.lpush(_USAGE_QUEUE_KEY, json.dumps(payload, default=str))
            return  # ✅ 不阻塞，立即返回
        except Exception:
            logger.warning("Usage Redis 写入失败，降级为同步写 DB")

    # 降级路径：同步写 DB
    await record_current_usage_sync(context, payload)


async def record_current_usage_sync(context: UsageContext, payload: dict) -> None:
    """同步写用量日志到 DB（Redis 不可用时的降级路径）。"""
    from app.integrations.database import AsyncSessionLocal

    prompt_tokens = payload["prompt_tokens"]
    completion_tokens = payload["completion_tokens"]

    async with AsyncSessionLocal() as db:
        # 查定价
        config = await db.scalar(
            select(LLMConfig).join(
                Tenant, Tenant.selected_llm_config_id == LLMConfig.id
            ).where(Tenant.id == context.tenant_id)
        )
        pricing = config.pricing if config and isinstance(config.pricing, dict) else {}
        input_rate = Decimal(str(pricing.get("prompt_per_1k", 0)))
        output_rate = Decimal(str(pricing.get("completion_per_1k", 0)))

        # 查 llm_config_id（后续 flush 时后台 worker 也会做同样的查询）
        llm_config_id = config.id if config else None

        cost = (Decimal(prompt_tokens) * input_rate + Decimal(completion_tokens) * output_rate) / Decimal(1000)

        item = LLMUsageLog(
            tenant_id=payload["tenant_id"],
            llm_config_id=llm_config_id,
            conversation_id=payload["conversation_id"],
            message_id=payload["message_id"],
            source=payload.get("source", "ai_pipeline"),
            model=payload["model"],
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=payload["total_tokens"],
            cost=cost,
            latency_ms=payload.get("latency_ms", 0),
            success=payload.get("success", True),
            error_message=payload.get("error_message"),
        )
        db.add(item)
        await db.commit()


async def tenant_dashboard(db: AsyncSession, tenant_id: int) -> dict[str, Any]:
    """获取租户仪表盘数据：业务指标 + LLM 累计消费 + 套餐限额。"""
    async def count(model, *conditions) -> int:
        return int(await db.scalar(select(func.count(model.id)).where(*conditions)) or 0)

    # LLM 消费聚合（SUM 可能为 NULL，用 coalesce 转为 0）
    usage = await db.execute(
        select(
            func.coalesce(func.sum(LLMUsageLog.total_tokens), 0),
            func.coalesce(func.sum(LLMUsageLog.cost), 0),
        ).where(LLMUsageLog.tenant_id == tenant_id)
    )
    total_tokens, total_cost = usage.one()

    # 获取租户关联的套餐限额信息，安全访问嵌套属性
    tenant = await db.get(Tenant, tenant_id)

    return {
        "conversation_count": await count(Conversation, Conversation.tenant_id == tenant_id),
        "message_count": await count(
            Message,
            Message.conversation_id.in_(
                select(Conversation.id).where(Conversation.tenant_id == tenant_id)
            ),
        ),
        "order_count": await count(Order, Order.tenant_id == tenant_id),
        "knowledge_doc_count": await count(KnowledgeDoc, KnowledgeDoc.tenant_id == tenant_id),
        "image_count": await count(Image, Image.tenant_id == tenant_id),
        "llm_total_tokens": int(total_tokens or 0),
        "llm_total_cost": float(total_cost or 0),
        "plan_limits": tenant.plan.limits if tenant and tenant.plan else {},
    }


async def list_usage_logs(
    db: AsyncSession,
    *,
    tenant_id: int | None = None,
    page: int = 1,
    page_size: int = 50,
) -> tuple[list[LLMUsageLog], int]:
    """查询 LLM 用量日志，支持按租户过滤和分页。"""
    conditions = [LLMUsageLog.tenant_id == tenant_id] if tenant_id is not None else []
    base = select(LLMUsageLog).where(*conditions)
    total = int(await db.scalar(select(func.count()).select_from(base.subquery())) or 0)
    rows = await db.execute(
        base.order_by(LLMUsageLog.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return list(rows.scalars().all()), total
