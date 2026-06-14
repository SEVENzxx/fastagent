"""带 Qdrant 索引同步的营销资料 CRUD 服务。"""

from __future__ import annotations

import logging

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.marketing_document import MarketingDocument
from app.ai.rag.vector_search import VectorDomain, VectorSearchService

logger = logging.getLogger(__name__)


class MarketingService:
    """管理营销素材，并索引可搜索的文本元数据。"""

    def __init__(self) -> None:
        self.vector_search = VectorSearchService()

    async def list_docs(
        self,
        db: AsyncSession,
        tenant_id: int,
        skip: int = 0,
        limit: int = 20,
        is_active: bool | None = None,
    ) -> tuple[list[MarketingDocument], int]:
        """分页查询租户下营销素材列表。

        参数：
            db: 异步数据库会话。
            tenant_id: 租户 ID。
            skip: 跳过的记录数（偏移）。
            limit: 最大返回数。
            is_active: 可选，按启用状态过滤。

        返回：
            (素材列表, 总数) 元组。
        """
        stmt = select(MarketingDocument).where(MarketingDocument.tenant_id == tenant_id)
        if is_active is not None:
            stmt = stmt.where(MarketingDocument.is_active == is_active)
        stmt = stmt.order_by(MarketingDocument.created_at.desc()).offset(skip).limit(limit)
        result = await db.execute(stmt)
        items = list(result.scalars().all())

        count_stmt = select(func.count(MarketingDocument.id)).where(MarketingDocument.tenant_id == tenant_id)
        if is_active is not None:
            count_stmt = count_stmt.where(MarketingDocument.is_active == is_active)
        total = (await db.execute(count_stmt)).scalar() or 0
        return items, total

    async def search_docs(
        self,
        db: AsyncSession,
        tenant_id: int,
        query: str,
        *,
        top_k: int = 5,
        is_active: bool | None = True,
    ) -> list[MarketingDocument]:
        """通过 Qdrant 语义搜索租户下的营销素材。

        按向量相似度召回后，再查 DB 获取完整记录，按召回顺序排列。

        参数：
            db: 异步数据库会话。
            tenant_id: 租户 ID。
            query: 搜索查询文本。
            top_k: 最大召回数量。
            is_active: 过滤是否启用的素材（None 表示不过滤）。

        返回：
            匹配的营销素材列表。
        """
        hits = await self.vector_search.search_text(
            domain=VectorDomain.MARKETING_DOCUMENT,
            tenant_id=tenant_id,
            query=query,
            top_k=top_k,
            min_score=0.55,
            filters={"is_active": is_active} if is_active is not None else None,
        )
        ids = [int(hit.payload["document_id"]) for hit in hits if str(hit.payload.get("document_id", "")).isdigit()]
        if not ids:
            return []
        result = await db.execute(
            select(MarketingDocument).where(
                MarketingDocument.tenant_id == tenant_id,
                MarketingDocument.id.in_(ids),
            )
        )
        docs = list(result.scalars().all())
        order = {doc_id: idx for idx, doc_id in enumerate(ids)}
        docs.sort(key=lambda item: order.get(item.id, len(order)))
        return docs

    async def get_doc(self, db: AsyncSession, doc_id: int, tenant_id: int) -> MarketingDocument | None:
        """按 ID 获取租户下单个营销素材。

        参数：
            db: 异步数据库会话。
            doc_id: 素材 ID。
            tenant_id: 租户 ID。

        返回：
            素材对象，不存在返回 None。
        """
        stmt = select(MarketingDocument).where(
            MarketingDocument.id == doc_id,
            MarketingDocument.tenant_id == tenant_id,
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def create_doc(
        self,
        db: AsyncSession,
        tenant_id: int,
        title: str,
        file_url: str,
        file_type: str,
        question_associations: list[str] | None = None,
        employee_id: int | None = None,
    ) -> MarketingDocument:
        """创建营销素材并同步索引到 Qdrant。

        创建后立即进行向量索引，确保搜索立即可用。

        参数：
            db: 异步数据库会话。
            tenant_id: 租户 ID。
            title: 素材标题。
            file_url: 素材文件 URL。
            file_type: 文件类型。
            question_associations: 关联的常见问题列表（用于搜索召回）。
            employee_id: 创建者员工 ID。

        返回：
            新创建的素材对象。
        """
        doc = MarketingDocument(
            tenant_id=tenant_id,
            title=title,
            file_url=file_url,
            file_type=file_type,
            question_associations=question_associations,
            created_by_employee_id=employee_id,
        )
        db.add(doc)
        await db.flush()
        await self._index_doc(doc)
        await db.commit()
        await db.refresh(doc)
        return doc

    async def update_doc(
        self,
        db: AsyncSession,
        doc_id: int,
        tenant_id: int,
        title: str | None = None,
        file_url: str | None = None,
        file_type: str | None = None,
        question_associations: list[str] | None = None,
        is_active: bool | None = None,
    ) -> MarketingDocument | None:
        """部分更新营销素材，更新后重新索引到 Qdrant。

        参数：
            db: 异步数据库会话。
            doc_id: 素材 ID。
            tenant_id: 租户 ID。
            title: 新标题（可选）。
            file_url: 新文件 URL（可选）。
            file_type: 新文件类型（可选）。
            question_associations: 新关联问题列表（可选）。
            is_active: 新启用状态（可选）。

        返回：
            更新后的素材对象，不存在返回 None。
        """
        doc = await self.get_doc(db, doc_id, tenant_id)
        if not doc:
            return None
        if title is not None:
            doc.title = title
        if file_url is not None:
            doc.file_url = file_url
        if file_type is not None:
            doc.file_type = file_type
        if question_associations is not None:
            doc.question_associations = question_associations
        if is_active is not None:
            doc.is_active = is_active
        await self._index_doc(doc)
        await db.commit()
        await db.refresh(doc)
        return doc

    async def delete_doc(self, db: AsyncSession, doc_id: int, tenant_id: int) -> bool:
        """删除营销素材并清理对应的 Qdrant 向量。

        参数：
            db: 异步数据库会话。
            doc_id: 素材 ID。
            tenant_id: 租户 ID。

        返回：
            成功删除返回 True，不存在返回 False。
        """
        doc = await self.get_doc(db, doc_id, tenant_id)
        if not doc:
            return False
        point_id = doc.qdrant_point_id
        await db.delete(doc)
        await db.commit()
        if point_id:
            await self.vector_search.delete_points(
                domain=VectorDomain.MARKETING_DOCUMENT,
                tenant_id=tenant_id,
                point_ids=[point_id],
            )
        return True

    async def _index_doc(self, doc: MarketingDocument) -> None:
        """将营销素材的文本元数据同步索引到 Qdrant。

        索引内容：标题 + 文件类型 + 关联问题列表，合并为一段文本后向量化存储。
        更新后自动写入 qdrant_point_id 供后续增量更新或删除。
        """
        text = "\n".join([doc.title, doc.file_type, " ".join(doc.question_associations or [])])
        point_id = await self.vector_search.upsert_text(
            domain=VectorDomain.MARKETING_DOCUMENT,
            tenant_id=doc.tenant_id,
            business_id=doc.id,
            text=text,
            payload={
                "document_id": str(doc.id),
                "title": doc.title,
                "file_url": doc.file_url,
                "file_type": doc.file_type,
                "question_associations": doc.question_associations or [],
                "is_active": doc.is_active,
            },
            point_id=doc.qdrant_point_id,
        )
        if point_id:
            doc.qdrant_point_id = point_id
