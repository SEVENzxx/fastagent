"""DocumentProcessor — 文档 AI 管道：解析 → 分块 → 向量化 → 属性抽取。

纯 AI 管道操作，不处理文件 I/O 和业务 CRUD。
由 KnowledgeService 调用，将 AI 依赖集中在 AI 层。
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.llm import gateway as llm_gateway
from app.ai.prompts.product_attribute_extraction import build_product_attr_extract_messages
from app.ai.rag.chunker import TextChunker
from app.ai.rag.parser import DocumentParser
from app.ai.rag.vector_search import VectorDomain, VectorSearchService
from app.common.constants.config import PRODUCT_ATTR_EXTRACT_MAX_TOKENS
from app.integrations.llm_client import LLMUseCase
from app.models.knowledge_chunk import KnowledgeChunk
from app.models.product import Product
from app.services.tenant_template import get_tenant_template, normalize_attrs_json

logger = logging.getLogger(__name__)


def _clean_llm_tags(raw_tags: object, *, max_count: int = 20, max_length: int = 12) -> list[str]:
    """清洗 LLM 返回的标签列表。"""
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
    last_brace = raw.rfind("{")
    if last_brace < 0:
        return None
    try:
        data = json.loads(raw[last_brace:])
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        logger.debug("首次 JSON 解析失败，尝试正则提取: raw=%s", raw[:100])
    match = re.search(r"\{[\s\S]*\}", raw)
    if match:
        try:
            data = json.loads(match.group())
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            logger.debug("正则提取 JSON 解析失败: raw=%s", raw[:100])
    return None


class DocumentProcessor:
    """文档 AI 管道处理器。

    封装文档解析、分块、向量化写入、向量删除、LLM 商品属性抽取。
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

    async def extract_product_attributes(
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
            max_tokens=PRODUCT_ATTR_EXTRACT_MAX_TOKENS,
            temperature=0.2,
        )

        data = _extract_final_json(raw)
        if data is None:
            logger.warning("LLM 属性抽取返回非 JSON: %s", raw[:200])
            return

        raw_attrs = data.get("attr") or data.get("attrs_json") or {}
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
