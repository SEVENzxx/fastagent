"""知识文档 CRUD 服务 — 上传 → 解析 → 分块 → 向量化 → 就绪"""

from __future__ import annotations

import logging
import os
import uuid
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy import func, select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.knowledge_chunk import KnowledgeChunk
from app.models.knowledge_doc import KnowledgeDoc
from app.ai.rag.chunker import TextChunker
from app.ai.rag.parser import DocumentParser
from app.ai.rag.vector_search import VectorDomain, VectorSearchService

logger = logging.getLogger(__name__)

UPLOAD_DIR = Path(__file__).resolve().parents[2] / "uploads" / "knowledge"


class KnowledgeService:
    """知识文档管理：上传、解析、分块、向量化。"""

    def __init__(self) -> None:
        self.parser = DocumentParser()
        self.chunker = TextChunker()
        self.vector_search = VectorSearchService()

    async def list_docs(
        self, db: AsyncSession, tenant_id: int, skip: int = 0, limit: int = 20,
        product_id: int | None = None,
    ) -> tuple[list[KnowledgeDoc], int]:
        conditions = [KnowledgeDoc.tenant_id == tenant_id]
        if product_id is not None:
            conditions.append(KnowledgeDoc.product_id == product_id)
        stmt = (
            select(KnowledgeDoc)
            .where(*conditions)
            .order_by(KnowledgeDoc.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        result = await db.execute(stmt)
        docs = result.scalars().all()

        count_stmt = select(func.count(KnowledgeDoc.id)).where(*conditions)
        total = (await db.execute(count_stmt)).scalar() or 0
        return list(docs), total

    async def get_doc(
        self, db: AsyncSession, doc_id: int, tenant_id: int
    ) -> KnowledgeDoc | None:
        stmt = select(KnowledgeDoc).where(
            KnowledgeDoc.id == doc_id, KnowledgeDoc.tenant_id == tenant_id
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_doc_chunks(
        self, db: AsyncSession, doc_id: int, tenant_id: int
    ) -> list[KnowledgeChunk]:
        stmt = (
            select(KnowledgeChunk)
            .where(
                KnowledgeChunk.doc_id == doc_id,
                KnowledgeChunk.tenant_id == tenant_id,
            )
            .order_by(KnowledgeChunk.chunk_index)
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def upload_and_process(
        self,
        db: AsyncSession,
        file: UploadFile,
        tenant_id: int,
        employee_id: int | None = None,
        product_id: int | None = None,
    ) -> KnowledgeDoc:
        """上传文件 → 保存 → 解析 → 分块 → 向量化 → 更新状态为 ready。

        product_id 可选：传入时表示该知识文档关联到指定商品，分块写入 Qdrant 时附带 product_id。
        若同一 product 已有文档，先删除旧文档（含向量）再上传新文档。
        """
        # 0. 若关联商品，先删除旧文档（替换模式）
        if product_id is not None:
            await self._delete_product_docs(db, tenant_id, product_id)

        # 1. 保存上传文件
        file_type = self._detect_type(file.filename or "")
        storage_path = await self._save_upload(file, tenant_id)

        doc = KnowledgeDoc(
            tenant_id=tenant_id,
            title=file.filename or "未命名文档",
            file_type=file_type,
            storage_path=storage_path,
            status="processing",
            created_by_employee_id=employee_id,
            product_id=product_id,
        )
        db.add(doc)
        await db.flush()

        try:
            # 2. 解析文档正文
            content = await self.parser.parse(storage_path, file_type)
            doc.content = content

            # 3. 切分知识分块
            chunks_data = self.chunker.chunk(content, doc_title=doc.title)
            if not chunks_data:
                doc.status = "ready"
                doc.chunk_count = 0
                await db.commit()
                await db.refresh(doc)
                return doc

            # 4. 先写入分块业务数据，再逐块写入 Qdrant。
            chunks: list[KnowledgeChunk] = []
            for i, chunk_data in enumerate(chunks_data):
                chunk = KnowledgeChunk(
                    tenant_id=tenant_id,
                    doc_id=doc.id,
                    chunk_index=chunk_data["chunk_index"],
                    content=chunk_data["content"],
                    token_count=chunk_data["token_count"],
                    metadata_=chunk_data["metadata"],
                )
                db.add(chunk)
                chunks.append(chunk)

            await db.flush()
            for chunk in chunks:
                payload: dict = {
                    "chunk_id": str(chunk.id),
                    "doc_id": str(doc.id),
                    "chunk_index": chunk.chunk_index,
                    "token_count": chunk.token_count,
                    "metadata": chunk.metadata_ or {},
                }
                if product_id is not None:
                    payload["product_id"] = str(product_id)

                point_id = await self.vector_search.upsert_text(
                    domain=VectorDomain.KNOWLEDGE_CHUNK,
                    tenant_id=tenant_id,
                    business_id=chunk.id,
                    text=chunk.content,
                    payload=payload,
                )
                if point_id:
                    chunk.qdrant_point_id = point_id

            doc.chunk_count = len(chunks_data)
            doc.status = "ready"
            await db.commit()
            await db.refresh(doc)
            logger.info(
                "知识文档处理完成: id=%s title=%s chunks=%d",
                doc.id,
                doc.title,
                doc.chunk_count,
            )
        except Exception as exc:
            logger.error("知识文档处理失败: id=%s error=%s", doc.id, exc)
            doc.status = "failed"
            doc.error_message = str(exc)
            await db.commit()
            await db.refresh(doc)

        return doc

    async def delete_doc(
        self, db: AsyncSession, doc_id: int, tenant_id: int
    ) -> bool:
        """删除文档及其所有分块（CASCADE 自动处理分块删除）。

        先删 Qdrant 向量，再删 DB 记录。Qdrant 删除失败时 DB 记录保留，避免向量残留。
        """
        doc = await self.get_doc(db, doc_id, tenant_id)
        if not doc:
            return False

        await self.vector_search.delete_points(
            domain=VectorDomain.KNOWLEDGE_CHUNK,
            tenant_id=tenant_id,
            filters={"doc_id": str(doc_id)},
        )

        try:
            os.remove(doc.storage_path)
        except OSError:
            pass

        await db.delete(doc)
        await db.commit()
        return True

    async def _delete_product_docs(
        self, db: AsyncSession, tenant_id: int, product_id: int
    ) -> None:
        """删除指定商品关联的所有知识文档（含向量和本地文件）。

        先删 Qdrant 向量，再删本地文件和 DB 记录。
        """
        stmt = select(KnowledgeDoc).where(
            KnowledgeDoc.tenant_id == tenant_id,
            KnowledgeDoc.product_id == product_id,
        )
        result = await db.execute(stmt)
        existing = result.scalars().all()
        if not existing:
            return

        for doc in existing:
            await self.vector_search.delete_points(
                domain=VectorDomain.KNOWLEDGE_CHUNK,
                tenant_id=tenant_id,
                filters={"doc_id": str(doc.id)},
            )
            try:
                os.remove(doc.storage_path)
            except OSError:
                pass
            await db.delete(doc)

        await db.flush()
        logger.info("已替换商品关联知识文档：tenant=%s product=%s count=%s", tenant_id, product_id, len(existing))

    async def _save_upload(self, file: UploadFile, tenant_id: int) -> str:
        """保存上传文件到本地磁盘。"""
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        safe_name = f"{uuid.uuid4().hex}_{file.filename or 'doc'}"
        file_path = UPLOAD_DIR / safe_name
        content = await file.read()
        file_path.write_bytes(content)
        return str(file_path.absolute())

    def _detect_type(self, filename: str) -> str:
        ext = Path(filename).suffix.lower().lstrip(".")
        valid = {"pdf", "docx", "md", "txt", "html"}
        return ext if ext in valid else "txt"
