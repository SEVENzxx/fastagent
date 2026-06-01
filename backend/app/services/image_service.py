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
from app.services.vector_search_service import VectorDomain, VectorSearchService

logger = logging.getLogger(__name__)

IMAGE_UPLOAD_DIR = Path(__file__).resolve().parents[2] / "uploads" / "images"


class ImageService:
    """管理图片，并将可搜索的文本元数据同步到 Qdrant。"""

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
