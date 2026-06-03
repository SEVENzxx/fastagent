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
