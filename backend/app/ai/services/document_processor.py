"""DocumentProcessor — 文档 AI 管道：解析 → 分块 → 向量化。

纯 AI 管道操作，不处理文件 I/O 和业务 CRUD。
由 KnowledgeService 调用，将 AI 依赖集中在 AI 层。
"""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.rag.chunker import TextChunker
from app.ai.rag.parser import DocumentParser
from app.ai.rag.vector_search import VectorDomain, VectorSearchService
from app.models.knowledge_chunk import KnowledgeChunk

logger = logging.getLogger(__name__)


class DocumentProcessor:
    """文档 AI 管道处理器。

    封装文档解析、分块、向量化写入、向量删除。
    KnowledgeService 调用此类完成 AI 相关操作，自身只做文件 I/O 和 DB CRUD。
    """

    def __init__(self) -> None:
        self.parser = DocumentParser()
        self.chunker = TextChunker()
        self.vector_search = VectorSearchService()

    async def parse_and_chunk(
        self,
        storage_path: str,
        file_type: str,
        doc_title: str = "",
    ) -> tuple[str, list[dict]]:
        """解析文档并分块。

        返回 (content, chunks_data)，chunks_data 可直接传给 save_chunks_and_vectorize。
        """
        content = await self.parser.parse(storage_path, file_type)
        chunks = self.chunker.chunk(content, doc_title=doc_title)
        return content, chunks

    async def save_chunks_and_vectorize(
        self,
        db: AsyncSession,
        tenant_id: int,
        doc_id: int,
        chunks_data: list[dict],
        product_id: int | None = None,
    ) -> list[KnowledgeChunk]:
        """保存分块到 DB 并逐块写入 Qdrant 向量索引。"""
        chunks: list[KnowledgeChunk] = []
        for chunk_data in chunks_data:
            chunk = KnowledgeChunk(
                tenant_id=tenant_id,
                doc_id=doc_id,
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
                "doc_id": str(doc_id),
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

        return chunks

    async def delete_doc_vectors(self, tenant_id: int, doc_id: int) -> None:
        """删除指定文档的所有 Qdrant 向量。"""
        await self.vector_search.delete_points(
            domain=VectorDomain.KNOWLEDGE_CHUNK,
            tenant_id=tenant_id,
            filters={"doc_id": str(doc_id)},
        )
