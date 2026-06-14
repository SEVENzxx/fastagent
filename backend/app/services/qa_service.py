"""带 Qdrant 索引同步的标准问答 CRUD 服务。

提供知识库中标准问答对的增删改查，创建/更新时自动同步 Qdrant 向量索引，
删除时同步清理向量，保证 DB 与向量库数据一致。
"""

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
        """分页查询租户下的标准问答对列表。

        参数：
            db: 异步数据库会话。
            tenant_id: 租户 ID。
            skip: 跳过的记录数。
            limit: 最大返回数。
            is_active: 可选，按启用状态过滤。

        返回：
            (问答对列表, 总数) 元组。
        """
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
        """按 ID 获取租户下单个问答对。

        参数：
            db: 异步数据库会话。
            pair_id: 问答对 ID。
            tenant_id: 租户 ID。

        返回：
            问答对对象，不存在返回 None。
        """
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
        """创建标准问答对并同步索引到 Qdrant。

        创建后立即向量化问题文本并入库，确保 RAG 搜索立即可用。

        参数：
            db: 异步数据库会话。
            tenant_id: 租户 ID。
            question: 标准问题。
            answer: 标准答案。
            keywords: 辅助关键词（提高召回率）。
            employee_id: 创建者员工 ID。

        返回：
            新创建的 QAPair ORM 对象。
        """
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
        """部分更新问答对，更新后重新向量索引。

        参数：
            db: 异步数据库会话。
            pair_id: 问答对 ID。
            tenant_id: 租户 ID。
            question: 新问题（可选）。
            answer: 新答案（可选）。
            keywords: 新关键词（可选）。
            is_active: 新启用状态（可选）。

        返回：
            更新后的问答对，不存在返回 None。
        """
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
        """删除问答对并清理对应的 Qdrant 向量。

        参数：
            db: 异步数据库会话。
            pair_id: 问答对 ID。
            tenant_id: 租户 ID。

        返回：
            成功删除返回 True，不存在返回 False。
        """
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
        """将问答对的问题文本索引到 Qdrant。

        仅用 question 做向量化（用户输入更接近问题而非答案），payload 中包含完整问答数据。
        """
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
