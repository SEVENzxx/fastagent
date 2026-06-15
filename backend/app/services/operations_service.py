"""运营支撑服务 — 审计日志、登录历史、站内通知、敏感词过滤。"""

from datetime import datetime, timezone

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.operations import AuditLog, LoginHistory, SensitiveWord, SystemNotification
from app.schemas.operations import SensitiveWordCreate, SensitiveWordUpdate

# 敏感词动作优先级映射：数字越大风险越高
ACTION_RANK = {"warn": 1, "transfer": 2, "block": 3}


async def record_audit(
    db: AsyncSession,
    *,
    action: str,
    resource_type: str,
    tenant_id: int | None = None,
    employee_id: int | None = None,
    resource_id: int | None = None,
    details: dict | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    commit: bool = True,
) -> AuditLog:
    """追加一条审计日志。"""
    item = AuditLog(
        tenant_id=tenant_id,
        employee_id=employee_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        details=details or {},
        ip_address=ip_address,
        user_agent=user_agent,
    )
    db.add(item)
    if commit:
        await db.commit()
        await db.refresh(item)
    else:
        await db.flush()
    return item


async def record_login(
    db: AsyncSession,
    *,
    email: str,
    success: bool,
    tenant_id: int | None = None,
    employee_id: int | None = None,
    failure_reason: str | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> LoginHistory:
    """记录一次登录尝试（成功或失败）。"""
    item = LoginHistory(
        tenant_id=tenant_id,
        employee_id=employee_id,
        email=email,
        success=success,
        failure_reason=failure_reason,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return item


async def create_notification(
    db: AsyncSession,
    *,
    type: str,
    title: str,
    tenant_id: int | None = None,
    employee_id: int | None = None,
    level: str = "info",
    content: str | None = None,
    resource_type: str | None = None,
    resource_id: int | None = None,
    metadata: dict | None = None,
    commit: bool = True,
) -> SystemNotification:
    """创建一条站内通知。"""
    item = SystemNotification(
        tenant_id=tenant_id,
        employee_id=employee_id,
        type=type,
        level=level,
        title=title,
        content=content,
        resource_type=resource_type,
        resource_id=resource_id,
        metadata_=metadata or {},
    )
    db.add(item)
    if commit:
        await db.commit()
        await db.refresh(item)
    else:
        await db.flush()
    return item


async def list_notifications(
    db: AsyncSession,
    tenant_id: int,
    employee_id: int,
    *,
    unread_only: bool = False,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[SystemNotification], int]:
    """查询当前坐席的通知列表（定向通知 + 租户广播通知）。"""
    conditions = [
        SystemNotification.tenant_id == tenant_id,
        or_(SystemNotification.employee_id.is_(None), SystemNotification.employee_id == employee_id),
    ]
    if unread_only:
        conditions.append(SystemNotification.is_read.is_(False))
    base = select(SystemNotification).where(and_(*conditions))
    total = int(await db.scalar(select(func.count()).select_from(base.subquery())) or 0)
    rows = await db.execute(
        base.order_by(SystemNotification.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return list(rows.scalars().all()), total


async def mark_notification_read(
    db: AsyncSession,
    tenant_id: int,
    employee_id: int,
    notification_id: int,
) -> SystemNotification | None:
    """将通知标记为已读。"""
    item = await db.scalar(
        select(SystemNotification).where(
            SystemNotification.id == notification_id,
            SystemNotification.tenant_id == tenant_id,
            or_(SystemNotification.employee_id.is_(None), SystemNotification.employee_id == employee_id),
        )
    )
    if item is None:
        return None
    item.is_read = True
    item.read_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(item)
    return item


async def list_sensitive_words(db: AsyncSession, tenant_id: int | None) -> list[SensitiveWord]:
    """列出租户级或系统级的敏感词规则。"""
    rows = await db.execute(
        select(SensitiveWord)
        .where(SensitiveWord.tenant_id.is_(None) if tenant_id is None else SensitiveWord.tenant_id == tenant_id)
        .order_by(SensitiveWord.created_at.desc())
    )
    return list(rows.scalars().all())


async def create_sensitive_word(db: AsyncSession, tenant_id: int | None, body: SensitiveWordCreate) -> SensitiveWord:
    """创建敏感词规则。"""
    exists = await db.scalar(
        select(SensitiveWord.id).where(
            SensitiveWord.tenant_id.is_(None) if tenant_id is None else SensitiveWord.tenant_id == tenant_id,
            SensitiveWord.word == body.word,
        )
    )
    if exists is not None:
        raise ValueError("敏感词已存在")
    item = SensitiveWord(tenant_id=tenant_id, **body.model_dump())
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return item


async def update_sensitive_word(
    db: AsyncSession,
    tenant_id: int | None,
    item_id: int,
    body: SensitiveWordUpdate,
) -> SensitiveWord | None:
    """部分更新敏感词规则（仅修改传入的非空字段）。"""
    item = await db.scalar(
        select(SensitiveWord).where(
            SensitiveWord.id == item_id,
            SensitiveWord.tenant_id.is_(None) if tenant_id is None else SensitiveWord.tenant_id == tenant_id,
        )
    )
    if item is None:
        return None
    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(item, key, value)
    await db.commit()
    await db.refresh(item)
    return item


async def evaluate_sensitive_text(db: AsyncSession, tenant_id: int, content: str) -> dict:
    """检测文本是否命中敏感词，返回最高风险动作和命中列表。"""
    clean_content = str(content or "")
    if not clean_content:
        return {"action": None, "matches": []}

    rows = await db.execute(
        select(SensitiveWord).where(
            SensitiveWord.is_active.is_(True),
            or_(SensitiveWord.tenant_id.is_(None), SensitiveWord.tenant_id == tenant_id),
        )
    )
    matches = [
        {"id": str(item.id), "word": item.word, "action": item.action}
        for item in rows.scalars().all()
        if item.word and item.word in clean_content
    ]
    action = max((item["action"] for item in matches), key=lambda value: ACTION_RANK[value], default=None)
    return {"action": action, "matches": matches}


async def list_audit_logs(
    db: AsyncSession,
    *,
    tenant_id: int | None = None,
    action: str | None = None,
    page: int = 1,
    page_size: int = 50,
) -> tuple[list[AuditLog], int]:
    """查询审计日志，支持按租户和操作类型过滤，分页返回。"""
    conditions = []
    if tenant_id is not None:
        conditions.append(AuditLog.tenant_id == tenant_id)
    if action:
        conditions.append(AuditLog.action == action)
    base = select(AuditLog).where(*conditions)
    total = int(await db.scalar(select(func.count()).select_from(base.subquery())) or 0)
    rows = await db.execute(base.order_by(AuditLog.created_at.desc()).offset((page - 1) * page_size).limit(page_size))
    return list(rows.scalars().all()), total


async def list_login_histories(
    db: AsyncSession,
    *,
    email: str = "",
    page: int = 1,
    page_size: int = 50,
) -> tuple[list[LoginHistory], int]:
    """查询登录历史，支持按邮箱模糊匹配。"""
    conditions = [LoginHistory.email.ilike(f"%{email.strip()}%")] if email.strip() else []
    base = select(LoginHistory).where(*conditions)
    total = int(await db.scalar(select(func.count()).select_from(base.subquery())) or 0)
    rows = await db.execute(base.order_by(LoginHistory.created_at.desc()).offset((page - 1) * page_size).limit(page_size))
    return list(rows.scalars().all()), total
