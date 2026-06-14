"""意图样本服务 — 租户自定义意图样本的 CRUD 与 Qdrant 同步。

核心设计：
  1. 所有写操作先写入 DB，然后同步到 Qdrant。
  2. 新增 / 编辑 → upsert_text（幂等）
  3. 启用 → upsert（启用前可能已被逻辑删除）
  4. 停用 → 从 Qdrant 删除对应 point，或 payload is_active=false
  5. 删除 → 从 DB 删除 + 从 Qdrant 删除 point

多租户隔离：所有查询必须带 tenant_id 过滤。
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import Select, delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.recognition.examples import SCHEMA_VERSION
from app.ai.rag.vector_search import VectorDomain, VectorSearchService
from app.models.intent_sample import IntentSample
from app.schemas.intent_sample import IntentSampleBatchCreate, IntentSampleCreate, IntentSampleUpdate

logger = logging.getLogger(__name__)


class IntentSampleService:
    """意图样本 CRUD + Qdrant 同步。"""

    def __init__(self) -> None:
        self._vector = VectorSearchService()

    # ──────────────────────────── Qdrant 同步 ────────────────────────────

    async def _upsert_to_qdrant(self, sample: IntentSample) -> str | None:
        """将单条样本 upsert 到 Qdrant，返回 qdrant_point_id。"""
        point_id = await self._vector.upsert_text(
            domain=VectorDomain.INTENT_SAMPLE,
            tenant_id=sample.tenant_id,
            business_id=str(sample.id),
            text=sample.example_text,
            payload={
                "tenant_id": sample.tenant_id,
                "domain": VectorDomain.INTENT_SAMPLE.value,
                "intent": sample.intent,
                "label": sample.label,
                "skill": sample.skill,
                "risk_level": sample.risk_level,
                "example_text": sample.example_text,
                "schema_version": SCHEMA_VERSION,
                "is_active": sample.enabled,
                "source": sample.source,
            },
        )
        return point_id

    async def _delete_from_qdrant(self, sample: IntentSample) -> None:
        """从 Qdrant 删除对应 point。"""
        if sample.qdrant_point_id:
            await self._vector.delete_points(
                domain=VectorDomain.INTENT_SAMPLE,
                tenant_id=sample.tenant_id,
                point_ids=[sample.qdrant_point_id],
            )

    # ──────────────────────────── CRUD ────────────────────────────

    async def list_samples(
        self,
        db: AsyncSession,
        tenant_id: int,
        *,
        intent: str | None = None,
        skill: str | None = None,
        enabled: bool | None = None,
        skip: int = 0,
        limit: int = 20,
    ) -> tuple[list[IntentSample], int]:
        """列出租户下的自定义样本，支持 intent / skill / enabled 过滤。"""
        query = select(IntentSample).where(IntentSample.tenant_id == tenant_id)
        count_query = select(func.count(IntentSample.id)).where(IntentSample.tenant_id == tenant_id)

        if intent:
            query = query.where(IntentSample.intent == intent)
            count_query = count_query.where(IntentSample.intent == intent)
        if skill:
            query = query.where(IntentSample.skill == skill)
            count_query = count_query.where(IntentSample.skill == skill)
        if enabled is not None:
            query = query.where(IntentSample.enabled == enabled)
            count_query = count_query.where(IntentSample.enabled == enabled)

        total = await db.scalar(count_query) or 0
        query = query.order_by(IntentSample.created_at.desc()).offset(skip).limit(limit)
        result = await db.execute(query)
        items = list(result.scalars().all())
        return items, total

    async def get_sample(self, db: AsyncSession, sample_id: int, tenant_id: int) -> IntentSample | None:
        """按 ID 获取租户样本。"""
        result = await db.execute(
            select(IntentSample).where(
                IntentSample.id == sample_id,
                IntentSample.tenant_id == tenant_id,
            )
        )
        return result.scalar_one_or_none()

    async def create_sample(
        self,
        db: AsyncSession,
        tenant_id: int,
        data: IntentSampleCreate,
    ) -> IntentSample:
        """新增样本 → DB 写入 → Qdrant upsert。"""
        sample = IntentSample(
            tenant_id=tenant_id,
            intent=data.intent,
            label=data.label,
            skill=data.skill,
            risk_level=data.risk_level,
            example_text=data.example_text.strip(),
            enabled=data.enabled,
            source="tenant_custom",
            schema_version=SCHEMA_VERSION,
        )
        db.add(sample)
        await db.flush()

        # 同步到 Qdrant
        point_id = await self._upsert_to_qdrant(sample)
        if point_id:
            sample.qdrant_point_id = point_id
            await db.flush()

        await db.commit()
        await db.refresh(sample)
        logger.info(
            "意图样本已创建：id=%s tenant=%s intent=%s qdrant=%s",
            sample.id, tenant_id, data.intent, point_id,
        )
        return sample

    async def create_sample_batch(
        self,
        db: AsyncSession,
        tenant_id: int,
        data: IntentSampleBatchCreate,
    ) -> list[IntentSample]:
        """批量新增样本。"""
        created: list[IntentSample] = []
        for text in data.examples:
            text = text.strip()
            if not text:
                continue
            sample = IntentSample(
                tenant_id=tenant_id,
                intent=data.intent,
                label=data.label,
                skill=data.skill,
                risk_level=data.risk_level,
                example_text=text,
                enabled=data.enabled,
                source="tenant_custom",
                schema_version=SCHEMA_VERSION,
            )
            db.add(sample)
            await db.flush()

            point_id = await self._upsert_to_qdrant(sample)
            if point_id:
                sample.qdrant_point_id = point_id
                await db.flush()

            created.append(sample)

        await db.commit()
        for s in created:
            await db.refresh(s)
        logger.info(
            "批量创建意图样本：tenant=%s intent=%s count=%s",
            tenant_id, data.intent, len(created),
        )
        return created

    async def update_sample(
        self,
        db: AsyncSession,
        sample: IntentSample,
        data: IntentSampleUpdate,
    ) -> IntentSample:
        """编辑样本 → DB 更新 → Qdrant re-upsert。"""
        update_data: dict[str, Any] = {}
        for field in ("intent", "label", "skill", "risk_level", "enabled"):
            val = getattr(data, field, None)
            if val is not None:
                setattr(sample, field, val)
                update_data[field] = val

        if data.example_text is not None:
            clean = data.example_text.strip()
            sample.example_text = clean
            update_data["example_text"] = clean

        if update_data:
            # 更新 DB
            stmt = (
                update(IntentSample)
                .where(IntentSample.id == sample.id)
                .values(**update_data)
            )
            await db.execute(stmt)

            # 重新 upsert 到 Qdrant
            point_id = await self._upsert_to_qdrant(sample)
            if point_id:
                sample.qdrant_point_id = point_id
                if "qdrant_point_id" not in update_data:
                    stmt2 = (
                        update(IntentSample)
                        .where(IntentSample.id == sample.id)
                        .values(qdrant_point_id=point_id)
                    )
                    await db.execute(stmt2)

        await db.commit()
        await db.refresh(sample)
        logger.info(
            "意图样本已更新：id=%s tenant=%s intent=%s",
            sample.id, sample.tenant_id, sample.intent,
        )
        return sample

    async def set_enabled(
        self,
        db: AsyncSession,
        sample: IntentSample,
        enabled: bool,
    ) -> IntentSample:
        """启用 / 停用 → Qdrant 同步。

        启用：重新 upsert 到 Qdrant。
        停用：从 Qdrant 删除对应 point。
        """
        stmt = (
            update(IntentSample)
            .where(IntentSample.id == sample.id)
            .values(enabled=enabled)
        )
        await db.execute(stmt)

        if enabled:
            point_id = await self._upsert_to_qdrant(sample)
            if point_id:
                sample.qdrant_point_id = point_id
                await db.execute(
                    update(IntentSample)
                    .where(IntentSample.id == sample.id)
                    .values(qdrant_point_id=point_id)
                )
        else:
            await self._delete_from_qdrant(sample)

        await db.commit()
        await db.refresh(sample)
        logger.info(
            "意图样本已%s：id=%s tenant=%s",
            "启用" if enabled else "停用",
            sample.id, sample.tenant_id,
        )
        return sample

    async def delete_sample(
        self,
        db: AsyncSession,
        sample: IntentSample,
    ) -> None:
        """删除 DB 记录 + 同步删除 Qdrant point。"""
        await self._delete_from_qdrant(sample)

        stmt = delete(IntentSample).where(IntentSample.id == sample.id)
        await db.execute(stmt)
        await db.commit()
        logger.info(
            "意图样本已删除：id=%s tenant=%s intent=%s",
            sample.id, sample.tenant_id, sample.intent,
        )

    # ──────────────────────────── 测试召回 ────────────────────────────

    async def test_search(
        self,
        db: AsyncSession,
        query: str,
        tenant_id: int,
        top_k: int = 10,
    ) -> list[dict[str, Any]]:
        """测试向量召回 — 同时搜索租户样本和平台默认样本。

        返回合并排序后的结果（租户样本加载 +0.03）。
        """
        from app.ai.rag.vector_search import VectorSearchResult

        # 同时搜索两个 tenant_id
        tenant_hits = await self._vector.search_text(
            domain=VectorDomain.INTENT_SAMPLE,
            tenant_id=tenant_id,
            query=query,
            top_k=top_k,
            min_score=0.0,
            filters={"is_active": True},
        )
        platform_hits = await self._vector.search_text(
            domain=VectorDomain.INTENT_SAMPLE,
            tenant_id=0,
            query=query,
            top_k=top_k,
            min_score=0.0,
            filters={"is_active": True},
        )

        # 合并去重（按 intent + example_text）
        seen: set[str] = set()
        merged: list[VectorSearchResult] = []

        for hit in tenant_hits:
            key = f"{hit.payload.get('intent','')}:{hit.payload.get('example_text','')}"
            if key not in seen:
                # 租户样本加权重
                hit = VectorSearchResult(
                    point_id=hit.point_id,
                    score=min(1.0, hit.score + 0.03),
                    payload=hit.payload,
                )
                seen.add(key)
                merged.append(hit)

        for hit in platform_hits:
            key = f"{hit.payload.get('intent','')}:{hit.payload.get('example_text','')}"
            if key not in seen:
                seen.add(key)
                merged.append(hit)

        merged.sort(key=lambda x: x.score, reverse=True)

        return [
            {
                "intent": h.payload.get("intent", ""),
                "label": h.payload.get("label", ""),
                "skill": h.payload.get("skill", ""),
                "score": round(h.score, 4),
                "example_text": h.payload.get("example_text") or h.payload.get("text", ""),
                "source": h.payload.get("source", ""),
                "tenant_id": h.payload.get("tenant_id", 0),
            }
            for h in merged[:top_k]
        ]
