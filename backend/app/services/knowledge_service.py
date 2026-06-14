"""知识文档 CRUD 服务 — 上传 → 解析 → 分块 → 向量化 → 就绪"""

from __future__ import annotations

import logging
import os
import uuid
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.llm import gateway as llm_gateway
from app.ai.prompts.product_attribute_extraction import build_product_attr_extract_messages
from app.ai.rag.chunker import TextChunker
from app.ai.rag.parser import DocumentParser
from app.ai.rag.vector_search import VectorDomain, VectorSearchService
from app.integrations.llm_client import LLMUseCase
from app.models.knowledge_chunk import KnowledgeChunk
from app.models.knowledge_doc import KnowledgeDoc
from app.models.product import Product
from app.services.tenant_template import get_tenant_template, normalize_attrs_json

logger = logging.getLogger(__name__)

UPLOAD_DIR = Path(__file__).resolve().parents[2] / "uploads" / "knowledge"


def _clean_llm_tags(raw_tags: object, *, max_count: int = 20, max_length: int = 12) -> list[str]:
    if not isinstance(raw_tags, list):
        return []
    result: list[str] = []
    seen: set[str] = set()
    for raw in raw_tags:
        tag = str(raw).strip()
        if not tag or len(tag) > max_length or tag in seen:
            continue
        seen.add(tag)
        result.append(tag)
        if len(result) >= max_count:
            break
    return result


def _extract_final_json(raw: str) -> dict | None:
    """从 thinking 模型的输出中提取最后一个有效 JSON 对象。"""
    import json as _json
    import re
    last_brace = raw.rfind("{")
    if last_brace < 0:
        return None
    try:
        data = _json.loads(raw[last_brace:])
        if isinstance(data, dict):
            return data
    except _json.JSONDecodeError:
        pass
    match = re.search(r"\{[\s\S]*\}", raw)
    if match:
        try:
            data = _json.loads(match.group())
            if isinstance(data, dict):
                return data
        except _json.JSONDecodeError:
            pass
    return None


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
        """分页查询租户下的知识文档列表，支持按关联商品过滤。

        参数：
            db: 异步数据库会话。
            tenant_id: 租户 ID。
            skip: 跳过的记录数。
            limit: 最大返回数。
            product_id: 可选，按关联商品过滤。

        返回：
            (文档列表, 总数) 元组。
        """
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
        """按 ID 获取租户下单个知识文档。

        参数：
            db: 异步数据库会话。
            doc_id: 文档 ID。
            tenant_id: 租户 ID。

        返回：
            文档对象，不存在返回 None。
        """
        stmt = select(KnowledgeDoc).where(
            KnowledgeDoc.id == doc_id, KnowledgeDoc.tenant_id == tenant_id
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_doc_chunks(
        self, db: AsyncSession, doc_id: int, tenant_id: int
    ) -> list[KnowledgeChunk]:
        """获取文档的所有知识分块，按 chunk_index 升序排列。

        参数：
            db: 异步数据库会话。
            doc_id: 文档 ID。
            tenant_id: 租户 ID。

        返回：
            分块列表。
        """
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

            # 若关联商品，异步抽取结构化属性（失败不阻断文档上传）
            if product_id is not None and content:
                try:
                    await self._extract_product_attributes(db, tenant_id, product_id, content, doc.title or "")
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

        参数：
            db: 异步数据库会话。
            file: 上传文件对象。
            tenant_id: 租户 ID。
            employee_id: 上传者 ID。
            product_id: 关联商品 ID（可选）。

        返回：
            创建的 KnowledgeDoc（状态为 processing）。
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
        异常时状态自动标记为 failed 并记录 error_message。

        参数：
            db: 异步数据库会话。
            doc_id: 文档 ID。
            tenant_id: 租户 ID。

        返回：
            处理后的 KnowledgeDoc。

        异常：
            ValueError: 文档记录不存在。
        """
        doc = await self.get_doc(db, doc_id, tenant_id)
        if doc is None:
            raise ValueError(f"Knowledge doc not found: {doc_id}")

        product_id = doc.product_id
        try:
            doc.status = "processing"
            doc.error_message = None
            content = await self.parser.parse(doc.storage_path, doc.file_type)
            doc.content = content

            chunks_data = self.chunker.chunk(content, doc_title=doc.title)
            if not chunks_data:
                doc.status = "ready"
                doc.chunk_count = 0
                await db.commit()
                await db.refresh(doc)
                return doc

            chunks: list[KnowledgeChunk] = []
            for chunk_data in chunks_data:
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

            if product_id is not None and content:
                try:
                    await self._extract_product_attributes(
                        db, tenant_id, product_id, content, doc.title or ""
                    )
                except Exception as attr_err:
                    logger.warning(
                        "Product attribute extraction failed without blocking upload: product_id=%s error=%s",
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
            logger.exception("Knowledge doc processing failed: id=%s", doc_id)
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

    async def _extract_product_attributes(
        self,
        db: AsyncSession,
        tenant_id: int,
        product_id: int,
        content: str,
        product_name: str,
    ) -> None:
        """从知识文档内容中通过 LLM 抽取商品结构化属性，写入 Product 表。

        不预设行业/品类属性 — LLM 自行从文档中发现属性。
        低置信度（<0.7）的属性仅记录日志，不自动写入。
        """
        import json

        product = await db.get(Product, product_id)
        if product is None or product.tenant_id != tenant_id:
            return
        template_fields = await get_tenant_template(db, tenant_id)
        product.attrs_json = {"attr": {}}
        product.feature_tags = []
        product.scenario_tags = []
        if not template_fields:
            logger.info(
                "租户未配置商品属性模板，写入空 attrs_json: tenant_id=%s product_id=%s",
                tenant_id,
                product_id,
            )
            return

        messages = build_product_attr_extract_messages(content, product_name, template_fields)
        raw = await llm_gateway.complete(
            LLMUseCase.PRODUCT_ATTR_EXTRACT,
            messages,
            tenant_id=tenant_id,
            max_tokens=1024,
            temperature=0.2,
        )

        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            import re
            match = re.search(r"\{[\s\S]*\}", raw)
            if match:
                try:
                    data = json.loads(match.group())
                except json.JSONDecodeError:
                    logger.warning("LLM 属性抽取返回非 JSON: %s", raw[:200])
                    return
            else:
                logger.warning("LLM 属性抽取返回非 JSON: %s", raw[:200])
                return

        raw_attrs = data.get("attr") or data.get("attrs_json") or {}  # 兼容新旧 prompt 格式
        extracted_attrs = raw_attrs if isinstance(raw_attrs, dict) else {}
        feature_tags = _clean_llm_tags(data.get("feature_tags"))
        scenario_tags = _clean_llm_tags(data.get("scenario_tags"))
        details = [item for item in (data.get("attributes_detail") or []) if isinstance(item, dict)]

        # attrs_json：只保留高置信度（≥0.7）且可筛选的属性
        # feature_tags / scenario_tags：LLM 已独立总结，直接信任，不做交叉验证
        attrs_json: dict = {}
        for d in details:
            try:
                conf = float(d.get("confidence", 0))
            except (TypeError, ValueError):
                conf = 0.0
            if conf < 0.7:
                logger.info("商品属性低置信度跳过: product_id=%s attr=%s confidence=%s",
                            product_id, d.get("attr_key", ""), conf)
                continue
            if d.get("is_filterable") and d.get("attr_key"):
                key = str(d["attr_key"])
                attrs_json[key] = d.get("attr_value", extracted_attrs.get(key))

        product.attrs_json = normalize_attrs_json(data, template_fields)
        product.feature_tags = feature_tags
        product.scenario_tags = scenario_tags

        logger.info(
            "商品属性抽取完成: product_id=%s attrs=%s features=%s scenarios=%s",
            product_id,
            list((product.attrs_json or {}).get("attr", {}).keys()),
            product.feature_tags,
            product.scenario_tags,
        )

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
        """保存上传文件到本地磁盘，返回绝对路径。

        文件名以 UUID 前缀防止冲突。
        """
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
