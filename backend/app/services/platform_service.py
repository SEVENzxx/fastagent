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
    """查询租户的所有渠道配置。

    参数：
        db: 异步数据库会话。
        tenant_id: 租户 ID。

    返回：
        (渠道列表, 总数) 元组，按创建时间倒序。
    """
    base = select(Platform).where(Platform.tenant_id == tenant_id)
    total = await db.scalar(select(func.count()).select_from(base.subquery()))
    result = await db.execute(base.order_by(Platform.created_at.desc()))
    return list(result.scalars().all()), total or 0


async def get_platform(db: AsyncSession, platform_id: int, tenant_id: int) -> Platform | None:
    """按 ID 获取租户下的单个渠道配置。

    参数：
        db: 异步数据库会话。
        platform_id: 渠道 ID。
        tenant_id: 租户 ID。

    返回：
        渠道对象，不存在返回 None。
    """
    return await db.scalar(
        select(Platform).where(Platform.id == platform_id, Platform.tenant_id == tenant_id)
    )


async def get_active_wecom_by_guid(db: AsyncSession, guid: int) -> Platform | None:
    """按平台 ID 获取启用的企业微信渠道。

    用于 webhook 回调时验证签名来源，只返回 type=wecom 且 is_active=true 的渠道。

    参数：
        db: 异步数据库会话。
        guid: 平台 GUID（数据库中的 platform.id）。

    返回：
        匹配的渠道对象，不满足条件返回 None。
    """
    return await db.scalar(
        select(Platform).where(
            Platform.id == guid,
            Platform.type == "wecom",
            Platform.is_active.is_(True),
        )
    )


async def create_platform(db: AsyncSession, tenant_id: int, body: PlatformCreate) -> Platform:
    """在租户下创建渠道配置。

    每个租户每种渠道类型（如 wecom）只能有一个，重复创建会报错。
    配置中的敏感字段（如 corpsecret）由 sanitize_config 统一清理。

    参数：
        db: 异步数据库会话。
        tenant_id: 租户 ID。
        body: 渠道创建请求体。

    返回：
        新创建的 Platform ORM 对象。

    异常：
        ValueError: 该类型渠道已存在。
    """
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
    """部分更新渠道配置。

    config 字段会经过 sanitize_config 清理，只保留白名单字段并去空格。

    参数：
        db: 异步数据库会话。
        platform_id: 渠道 ID。
        tenant_id: 租户 ID。
        body: 渠道更新请求体（所有字段可选）。

    返回：
        更新后的渠道对象，不存在返回 None。
    """
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
    """删除渠道配置。

    软删除会保留历史会话中 platform_id 引用，但消息出站投递会校验 platform.is_active。

    参数：
        db: 异步数据库会话。
        platform_id: 渠道 ID。
        tenant_id: 租户 ID。

    返回：
        成功删除返回 True，不存在返回 False。
    """
    platform = await get_platform(db, platform_id, tenant_id)
    if platform is None:
        return False
    await db.delete(platform)
    await db.commit()
    return True
