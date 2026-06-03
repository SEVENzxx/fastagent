"""带 Qdrant 索引同步的标准问答 CRUD 服务。"""

from __future__ import annotations

import logging

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.qa_pair import QAPair
from app.ai.rag.vector_search import VectorDomain, VectorSearchService

logger = logging.getLogger(__name__)


class QAService:
    """管理标准问答对，并保持 Qdrant payload 与业务数据同步。"""

    def __init__(self) -> None:
        self.vector_search = VectorSearchService()

    async def list_pairs(
        self,
        db: AsyncSession,
        tenant_id: int,
        skip: int = 0,
        limit: int = 20,
        is_active: bool | None = None,
    ) -> tuple[list[QAPair], int]:
        stmt = select(QAPair).where(QAPair.tenant_id == tenant_id)
        if is_active is not None:
            stmt = stmt.where(QAPair.is_active == is_active)
        stmt = stmt.order_by(QAPair.created_at.desc()).offset(skip).limit(limit)
        result = await db.execute(stmt)
        items = list(result.scalars().all())

        count_stmt = select(func.count(QAPair.id)).where(QAPair.tenant_id == tenant_id)
        if is_active is not None:
            count_stmt = count_stmt.where(QAPair.is_active == is_active)
        total = (await db.execute(count_stmt)).scalar() or 0
        return items, total

    async def get_pair(self, db: AsyncSession, pair_id: int, tenant_id: int) -> QAPair | None:
        stmt = select(QAPair).where(QAPair.id == pair_id, QAPair.tenant_id == tenant_id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def create_pair(
        self,
        db: AsyncSession,
        tenant_id: int,
        question: str,
        answer: str,
        keywords: list[str] | None = None,
        employee_id: int | None = None,
    ) -> QAPair:
        pair = QAPair(
            tenant_id=tenant_id,
            question=question,
            answer=answer,
            keywords=keywords,
            created_by_employee_id=employee_id,
        )
        db.add(pair)
        await db.flush()
        await self._index_pair(pair)
        await db.commit()
        await db.refresh(pair)
        logger.info("QA pair created and indexed: id=%s tenant_id=%s", pair.id, tenant_id)
        return pair

    async def update_pair(
        self,
        db: AsyncSession,
        pair_id: int,
        tenant_id: int,
        question: str | None = None,
        answer: str | None = None,
        keywords: list[str] | None = None,
        is_active: bool | None = None,
    ) -> QAPair | None:
        pair = await self.get_pair(db, pair_id, tenant_id)
        if not pair:
            return None

        if question is not None:
            pair.question = question
        if answer is not None:
            pair.answer = answer
        if keywords is not None:
            pair.keywords = keywords
        if is_active is not None:
            pair.is_active = is_active

        await self._index_pair(pair)
        await db.commit()
        await db.refresh(pair)
        logger.info("QA pair updated and re-indexed: id=%s tenant_id=%s active=%s", pair.id, tenant_id, pair.is_active)
        return pair

    async def delete_pair(self, db: AsyncSession, pair_id: int, tenant_id: int) -> bool:
        pair = await self.get_pair(db, pair_id, tenant_id)
        if not pair:
            return False
        point_id = pair.qdrant_point_id
        await db.delete(pair)
        await db.commit()
        if point_id:
            await self.vector_search.delete_points(
                domain=VectorDomain.QA_PAIR,
                tenant_id=tenant_id,
                point_ids=[point_id],
            )
        return True

    async def _index_pair(self, pair: QAPair) -> None:
        point_id = await self.vector_search.upsert_text(
            domain=VectorDomain.QA_PAIR,
            tenant_id=pair.tenant_id,
            business_id=pair.id,
            text=pair.question,
            payload={
                "qa_id": str(pair.id),
                "question": pair.question,
                "answer": pair.answer,
                "keywords": pair.keywords or [],
                "is_active": pair.is_active,
            },
            point_id=pair.qdrant_point_id,
        )
        if point_id:
            pair.qdrant_point_id = point_id
