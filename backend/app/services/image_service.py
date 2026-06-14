"""图片库 CRUD 服务。

当前只把文件名、标签、关联商品等文本元数据写入 Qdrant。
在多模态 embedding 服务接入前，不在这里引入 CLIP；后续图片向量接入时
可以复用同一个 qdrant_point_id。
"""

from __future__ import annotations

import logging
import os
import uuid
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.image import Image
from app.ai.rag.vector_search import VectorDomain, VectorSearchService

logger = logging.getLogger(__name__)

IMAGE_UPLOAD_DIR = Path(__file__).resolve().parents[2] / "uploads" / "images"


class ImageService:
    """管理图片，并将可搜索的文本元数据同步到 Qdrant。

    当前仅将文件名、标签、关联商品等元数据向量化入库；多模态视觉 embedding
    接入后可在同一 qdrant_point_id 上扩展。
    """

    def __init__(self) -> None:
        self.vector_search = VectorSearchService()

    async def list_images(
        self,
        db: AsyncSession,
        tenant_id: int,
        skip: int = 0,
        limit: int = 20,
        product_id: int | None = None,
    ) -> tuple[list[Image], int]:
        """分页查询租户下图片列表，支持按商品 ID 过滤。

        参数：
            db: 异步数据库会话。
            tenant_id: 租户 ID。
            skip: 跳过的记录数。
            limit: 最大返回数。
            product_id: 可选，按关联商品过滤。

        返回：
            (图片列表, 总数) 元组。
        """
        stmt = select(Image).where(Image.tenant_id == tenant_id)
        if product_id is not None:
            stmt = stmt.where(Image.product_id == product_id)
        stmt = stmt.order_by(Image.created_at.desc()).offset(skip).limit(limit)
        result = await db.execute(stmt)
        items = list(result.scalars().all())

        count_stmt = select(func.count(Image.id)).where(Image.tenant_id == tenant_id)
        if product_id is not None:
            count_stmt = count_stmt.where(Image.product_id == product_id)
        total = (await db.execute(count_stmt)).scalar() or 0
        return items, total

    async def search_images(
        self,
        db: AsyncSession,
        tenant_id: int,
        query: str,
        *,
        top_k: int = 5,
        product_id: int | None = None,
    ) -> list[Image]:
        """通过 Qdrant 语义搜索租户下的图片素材。

        参数：
            db: 异步数据库会话。
            tenant_id: 租户 ID。
            query: 搜索文本。
            top_k: 最大召回数量。
            product_id: 可选，限制仅搜索某商品关联图片。

        返回：
            按相似度排序的图片列表。
        """
        filters = {"product_id": str(product_id)} if product_id is not None else None
        hits = await self.vector_search.search_text(
            domain=VectorDomain.IMAGE,
            tenant_id=tenant_id,
            query=query,
            top_k=top_k,
            min_score=0.5,
            filters=filters,
        )
        ids = [int(hit.payload["image_id"]) for hit in hits if str(hit.payload.get("image_id", "")).isdigit()]
        if not ids:
            return []
        result = await db.execute(select(Image).where(Image.tenant_id == tenant_id, Image.id.in_(ids)))
        images = list(result.scalars().all())
        order = {image_id: idx for idx, image_id in enumerate(ids)}
        images.sort(key=lambda item: order.get(item.id, len(order)))
        return images

    async def get_image(self, db: AsyncSession, image_id: int, tenant_id: int) -> Image | None:
        """按 ID 获取租户下单张图片。

        参数：
            db: 异步数据库会话。
            image_id: 图片 ID。
            tenant_id: 租户 ID。

        返回：
            图片对象，不存在返回 None。
        """
        stmt = select(Image).where(Image.id == image_id, Image.tenant_id == tenant_id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def upload_image(
        self,
        db: AsyncSession,
        file: UploadFile,
        tenant_id: int,
        employee_id: int | None = None,
    ) -> Image:
        """上传图片文件并保存到本地磁盘，同步索引元数据到 Qdrant。

        文件以 UUID 前缀重命名避免冲突，上传后立即向量化索引。
        当前不含多模态 embedding，仅索引文件名等文本元数据。

        参数：
            db: 异步数据库会话。
            file: FastAPI UploadFile 对象。
            tenant_id: 租户 ID。
            employee_id: 上传者员工 ID。

        返回：
            新创建的 Image ORM 对象。
        """
        IMAGE_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        safe_name = f"{uuid.uuid4().hex}_{file.filename or 'image'}"
        file_path = IMAGE_UPLOAD_DIR / safe_name
        content = await file.read()
        file_path.write_bytes(content)

        image = Image(
            tenant_id=tenant_id,
            filename=file.filename or "image",
            storage_path=str(file_path.absolute()),
            file_url=f"/uploads/images/{safe_name}",
            file_size=len(content),
            mime_type=file.content_type or "application/octet-stream",
            created_by_employee_id=employee_id,
        )
        db.add(image)
        await db.flush()
        await self._index_image(image)
        await db.commit()
        await db.refresh(image)
        return image

    async def update_image(
        self,
        db: AsyncSession,
        image_id: int,
        tenant_id: int,
        tags: list[str] | None = None,
        product_id: int | None = None,
    ) -> Image | None:
        """更新图片的标签和关联商品，并重新同步 Qdrant 索引。

        参数：
            db: 异步数据库会话。
            image_id: 图片 ID。
            tenant_id: 租户 ID。
            tags: 新标签列表（可选）。
            product_id: 新关联商品 ID（可选）。

        返回：
            更新后的图片，不存在返回 None。
        """
        image = await self.get_image(db, image_id, tenant_id)
        if not image:
            return None
        if tags is not None:
            image.tags = tags
        if product_id is not None:
            image.product_id = product_id
        await self._index_image(image)
        await db.commit()
        await db.refresh(image)
        return image

    async def delete_image(self, db: AsyncSession, image_id: int, tenant_id: int) -> bool:
        """删除图片并清理磁盘文件和 Qdrant 向量。

        参数：
            db: 异步数据库会话。
            image_id: 图片 ID。
            tenant_id: 租户 ID。

        返回：
            成功删除返回 True，不存在返回 False。
        """
        image = await self.get_image(db, image_id, tenant_id)
        if not image:
            return False
        point_id = image.qdrant_point_id
        try:
            os.remove(image.storage_path)
        except OSError:
            pass
        await db.delete(image)
        await db.commit()
        if point_id:
            await self.vector_search.delete_points(
                domain=VectorDomain.IMAGE,
                tenant_id=tenant_id,
                point_ids=[point_id],
            )
        return True

    async def _index_image(self, image: Image) -> None:
        """将图片的文本元数据（文件名+标签+商品ID）索引到 Qdrant。

        tags 为列表时用空格拼接。后续多模态 embedding 接入后可以扩展此方法。
        """
        tags = image.tags or []
        tags_text = " ".join(str(item) for item in tags) if isinstance(tags, list) else str(tags)
        text = "\n".join(part for part in [image.filename, tags_text, str(image.product_id or "")] if part)
        point_id = await self.vector_search.upsert_text(
            domain=VectorDomain.IMAGE,
            tenant_id=image.tenant_id,
            business_id=image.id,
            text=text,
            payload={
                "image_id": str(image.id),
                "filename": image.filename,
                "file_url": image.file_url,
                "mime_type": image.mime_type,
                "tags": image.tags or [],
                "product_id": str(image.product_id) if image.product_id is not None else None,
            },
            point_id=image.qdrant_point_id,
        )
        if point_id:
            image.qdrant_point_id = point_id
