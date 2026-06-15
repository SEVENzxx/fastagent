"""知识文档 CRUD 服务 — 上传 → 解析 → 分块 → 向量化 → 就绪"""

from __future__ import annotations

import logging
import os
import uuid
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.services.document_processor import DocumentProcessor
from app.models.knowledge_chunk import KnowledgeChunk
from app.models.knowledge_doc import KnowledgeDoc

logger = logging.getLogger(__name__)

UPLOAD_DIR = Path(__file__).resolve().parents[2] / "uploads" / "knowledge"


class KnowledgeService:
    """知识文档管理：上传、解析、分块、向量化。"""

    def __init__(self) -> None:
        self.doc_processor = DocumentProcessor()

    async def list_docs(
        self, db: AsyncSession, tenant_id: int, skip: int = 0, limit: int = 20,
        product_id: int | None = None,
    ) -> tuple[list[KnowledgeDoc], int]:
        """分页查询租户下的知识文档列表，支持按关联商品过滤。"""
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
        """按 ID 获取租户下单个知识文档。"""
        stmt = select(KnowledgeDoc).where(
            KnowledgeDoc.id == doc_id, KnowledgeDoc.tenant_id == tenant_id
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_doc_chunks(
        self, db: AsyncSession, doc_id: int, tenant_id: int
    ) -> list[KnowledgeChunk]:
        """获取文档的所有知识分块，按 chunk_index 升序排列。"""
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
            # 2. 解析文档正文 + 分块
            content, chunks_data = await self.doc_processor.parse_and_chunk(
                storage_path, file_type, doc.title or "",
            )
            doc.content = content

            # 3. 切分知识分块
            if not chunks_data:
                doc.status = "ready"
                doc.chunk_count = 0
                await db.commit()
                await db.refresh(doc)
                return doc

            await self.doc_processor.save_chunks_and_vectorize(
                db, tenant_id, doc.id, chunks_data, product_id,
            )
            doc.chunk_count = len(chunks_data)
            doc.status = "ready"

            # 4. 若关联商品，异步抽取结构化属性（失败不阻断文档上传）
            if product_id is not None and content:
                try:
                    await self.doc_processor.extract_product_attributes(
                        db, tenant_id, product_id, content, doc.title or "",
                    )
                except Exception as attr_err:
                    logger.warning(
                        "商品属性抽取失败（不影响文档上传）: product_id=%s error=%s",
                        product_id, attr_err,
                    )

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

    async def create_upload_doc(
        self,
        db: AsyncSession,
        file: UploadFile,
        tenant_id: int,
        employee_id: int | None = None,
        product_id: int | None = None,
    ) -> KnowledgeDoc:
        """保存上传文件并创建 processing 状态的文档记录（不执行解析）。

        用于异步处理场景：API 先创建空记录返回，后续通过后台任务调用 process_doc 解析。
        """
        if product_id is not None:
            await self._delete_product_docs(db, tenant_id, product_id)

        file_type = self._detect_type(file.filename or "")
        storage_path = await self._save_upload(file, tenant_id)

        doc = KnowledgeDoc(
            tenant_id=tenant_id,
            title=file.filename or "untitled",
            file_type=file_type,
            storage_path=storage_path,
            status="processing",
            created_by_employee_id=employee_id,
            product_id=product_id,
        )
        db.add(doc)
        await db.commit()
        await db.refresh(doc)
        return doc

    async def process_doc(
        self,
        db: AsyncSession,
        doc_id: int,
        tenant_id: int,
    ) -> KnowledgeDoc:
        """解析、分块、向量化已有的文档记录。

        通常由后台任务调用，将 create_upload_doc 创建的 processing 记录进一步处理。
        """
        doc = await self.get_doc(db, doc_id, tenant_id)
        if doc is None:
            raise ValueError(f"知识文档不存在: {doc_id}")

        product_id = doc.product_id
        try:
            doc.status = "processing"
            doc.error_message = None
            content, chunks_data = await self.doc_processor.parse_and_chunk(
                doc.storage_path, doc.file_type, doc.title or "",
            )
            doc.content = content

            if not chunks_data:
                doc.status = "ready"
                doc.chunk_count = 0
                await db.commit()
                await db.refresh(doc)
                return doc

            await self.doc_processor.save_chunks_and_vectorize(
                db, tenant_id, doc.id, chunks_data, product_id,
            )
            doc.chunk_count = len(chunks_data)
            doc.status = "ready"

            if product_id is not None and content:
                try:
                    await self.doc_processor.extract_product_attributes(
                        db, tenant_id, product_id, content, doc.title or "",
                    )
                except Exception as attr_err:
                    logger.warning(
                        "商品属性抽取失败（不阻断上传）: product_id=%s error=%s",
                        product_id,
                        attr_err,
                    )

            await db.commit()
            await db.refresh(doc)
            logger.info(
                "Knowledge doc processing finished: id=%s title=%s chunks=%d",
                doc.id,
                doc.title,
                doc.chunk_count,
            )
        except Exception as exc:
            logger.exception("知识文档处理失败: id=%s", doc_id)
            doc.status = "failed"
            doc.error_message = str(exc)
            try:
                await db.commit()
            except Exception:
                await db.rollback()
                doc = await self.get_doc(db, doc_id, tenant_id)
                if doc is None:
                    raise
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

        await self.doc_processor.delete_doc_vectors(tenant_id, doc_id)

        try:
            os.remove(doc.storage_path)
        except OSError:
            logger.warning("删除知识文档文件失败: path=%s", doc.storage_path)

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
            await self.doc_processor.delete_doc_vectors(tenant_id, doc.id)
            try:
                os.remove(doc.storage_path)
            except OSError:
                logger.warning("删除商品关联文档文件失败: doc_id=%s path=%s", doc.id, doc.storage_path)
            await db.delete(doc)

        await db.flush()
        logger.info("已替换商品关联知识文档：tenant=%s product=%s count=%s", tenant_id, product_id, len(existing))

    async def _save_upload(self, file: UploadFile, tenant_id: int) -> str:
        """保存上传文件到本地磁盘，返回绝对路径。"""
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        safe_name = f"{uuid.uuid4().hex}_{file.filename or 'doc'}"
        file_path = UPLOAD_DIR / safe_name
        content = await file.read()
        file_path.write_bytes(content)
        return str(file_path.absolute())

    def _detect_type(self, filename: str) -> str:
        """根据文件扩展名检测文档类型，未知类型默认返回 'txt'。"""
        ext = Path(filename).suffix.lower().lstrip(".")
        valid = {"pdf", "docx", "md", "txt", "html"}
        return ext if ext in valid else "txt"
