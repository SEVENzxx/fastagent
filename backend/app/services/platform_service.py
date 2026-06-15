"""渠道配置服务。"""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.platform import Platform
from app.schemas.platform import PlatformCreate, PlatformUpdate


def sanitize_config(config: dict | None) -> dict:
    """清理渠道配置。

    当前版本不做真实密钥加密，只保留结构；后续接入 encryption.py 时可在这里统一加解密 corpsecret。
    """
    raw = dict(config or {})
    return {
        "corpid": str(raw.get("corpid") or "").strip(),
        "corpsecret": str(raw.get("corpsecret") or "").strip(),
        "token": str(raw.get("token") or "").strip(),
        "encoding_aes_key": str(raw.get("encoding_aes_key") or "").strip(),
        "agentid": str(raw.get("agentid") or "").strip(),
    }


async def list_platforms(db: AsyncSession, tenant_id: int) -> tuple[list[Platform], int]:
    """查询租户的所有渠道配置。"""
    base = select(Platform).where(Platform.tenant_id == tenant_id)
    total = await db.scalar(select(func.count()).select_from(base.subquery()))
    result = await db.execute(base.order_by(Platform.created_at.desc()))
    return list(result.scalars().all()), total or 0


async def get_platform(db: AsyncSession, platform_id: int, tenant_id: int) -> Platform | None:
    """按 ID 获取租户下的单个渠道配置。"""
    return await db.scalar(
        select(Platform).where(Platform.id == platform_id, Platform.tenant_id == tenant_id)
    )


async def get_active_wecom_by_guid(db: AsyncSession, guid: int) -> Platform | None:
    """按平台 ID 获取启用的企业微信渠道。"""
    return await db.scalar(
        select(Platform).where(
            Platform.id == guid,
            Platform.type == "wecom",
            Platform.is_active.is_(True),
        )
    )


async def create_platform(db: AsyncSession, tenant_id: int, body: PlatformCreate) -> Platform:
    """在租户下创建渠道配置。"""
    exists = await db.scalar(
        select(Platform.id).where(Platform.tenant_id == tenant_id, Platform.type == body.type)
    )
    if exists is not None:
        raise ValueError("该类型渠道已存在")

    platform = Platform(
        tenant_id=tenant_id,
        type=body.type,
        name=body.name,
        config=sanitize_config(body.config),
        webhook_url=body.webhook_url,
        is_active=body.is_active,
    )
    db.add(platform)
    await db.commit()
    await db.refresh(platform)
    return platform


async def update_platform(
    db: AsyncSession,
    platform_id: int,
    tenant_id: int,
    body: PlatformUpdate,
) -> Platform | None:
    """部分更新渠道配置。"""
    platform = await get_platform(db, platform_id, tenant_id)
    if platform is None:
        return None

    data = body.model_dump(exclude_unset=True)
    if "config" in data and data["config"] is not None:
        data["config"] = sanitize_config(data["config"])
    for key, value in data.items():
        setattr(platform, key, value)

    await db.commit()
    await db.refresh(platform)
    return platform


async def delete_platform(db: AsyncSession, platform_id: int, tenant_id: int) -> bool:
    """删除渠道配置。"""
    platform = await get_platform(db, platform_id, tenant_id)
    if platform is None:
        return False
    await db.delete(platform)
    await db.commit()
    return True
