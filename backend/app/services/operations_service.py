"""运营支撑服务 — 审计日志、登录历史、站内通知、敏感词过滤。

职责
----
本模块提供平台运营相关的核心支撑服务：
  - 审计日志（Audit Log）：记录关键操作（登录、创建、更新、删除等），独立提交不随业务事务回滚丢失。
  - 登录历史（Login History）：记录每次登录尝试（成功/失败），不保存密码等敏感凭据。
  - 站内通知（System Notification）：支持租户广播（employee_id=NULL）和定向通知。
  - 敏感词管理（Sensitive Word）：支持系统级（tenant_id IS NULL）和租户级规则，
    动作优先级 warn(1) < transfer(2) < block(3)。

设计要点
--------
- audit_log 使用独立数据库会话提交，确保即使业务操作失败回滚，审计记录也不会丢失。
- 敏感词同时匹配系统级通用规则和租户自定义规则，取最高风险动作执行。
- 通知的 is_read 标记只能由通知的接收者（或广播通知的租户内任意坐席）操作。
"""

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
    """追加一条审计日志。

    参数：
        db: 数据库会话（可以是独立会话，用于业务事务外的审计记录）
        action: 操作类型，如 "login"、"create_order"、"update_tenant" 等
        resource_type: 操作的资源类型，如 "order"、"tenant"、"employee" 等
        tenant_id: 所属租户 ID，平台级操作为 None
        employee_id: 执行操作的员工 ID，系统自动作为 None
        resource_id: 被操作资源的 ID
        details: 操作详情（JSON 对象），如 {"before": {...}, "after": {...}}
        ip_address: 操作者 IP 地址
        user_agent: 操作者 User-Agent
        commit: 是否独立提交（默认 True），设为 False 可跟随外部事务一起提交

    返回：
        创建的 AuditLog ORM 对象

    设计意图：
        默认 commit=True，审计日志使用独立事务提交，
        确保即使业务操作后续失败回滚，审计记录也不会丢失。
    """
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
    """记录一次登录尝试（成功或失败）。

    参数：
        db: 数据库会话
        email: 登录邮箱
        success: 是否登录成功
        tenant_id: 关联的租户 ID
        employee_id: 关联的员工 ID（登录成功时才有值）
        failure_reason: 失败原因（如 "密码错误"、"账号已禁用"、"租户已过期" 等）
        ip_address: 登录 IP 地址
        user_agent: 登录客户端 User-Agent

    返回：
        创建的 LoginHistory ORM 对象

    安全说明：
        不保存密码、Token 等敏感凭据，只记录邮箱和成功/失败状态。
    """
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
    """创建一条站内通知。

    参数：
        db: 数据库会话
        type: 通知类型，如 "transfer"（转人工）、"channel_error"（渠道异常）、"token_low"（Token 不足）
        title: 通知标题（前端展示用）
        tenant_id: 所属租户 ID
        employee_id: 接收通知的员工 ID，为 None 时表示向整个租户广播
        level: 通知级别，可选 "info"、"warning"、"error"
        content: 通知正文（支持 Markdown 或纯文本）
        resource_type: 关联的资源类型（如 "conversation"、"order"）
        resource_id: 关联的资源 ID
        metadata: 附加元数据（JSON 对象）
        commit: 是否独立提交

    返回：
        创建的 SystemNotification ORM 对象

    使用场景：
        - employee_id 有值时：向特定坐席发送定向通知（如分配给 Ta 的会话转人工）
        - employee_id 为 None 时：向整个租户广播（如系统维护公告）
    """
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
    """查询当前坐席的通知列表（定向通知 + 租户广播通知）。

    参数：
        db: 数据库会话
        tenant_id: 租户 ID（用于租户隔离）
        employee_id: 当前坐席的员工 ID
        unread_only: 是否仅查询未读通知
        page: 页码（从 1 开始）
        page_size: 每页条数

    返回：
        (通知列表, 总数) 元组

    查询逻辑：
        条件 = 本租户 AND (定向给该坐席 OR 租户内广播)
        即同时返回：1) 专门发给该坐席的通知  2) 发给整个租户的广播通知
    """
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
    """将通知标记为已读。

    参数：
        db: 数据库会话
        tenant_id: 租户 ID
        employee_id: 当前坐席的员工 ID
        notification_id: 要标记的通知 ID

    返回：
        更新后的通知对象，若通知不存在或不属于该坐席则返回 None

    权限校验：
        只能标记「自己的定向通知」或「租户内广播通知」，
        不能标记其他坐席的定向通知。
    """
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
    """列出租户级或系统级的敏感词规则。

    参数：
        db: 数据库会话
        tenant_id: 租户 ID，传入 None 表示查询系统级规则（tenant_id IS NULL）

    返回：
        敏感词规则列表（按创建时间倒序）
    """
    rows = await db.execute(
        select(SensitiveWord)
        .where(SensitiveWord.tenant_id.is_(None) if tenant_id is None else SensitiveWord.tenant_id == tenant_id)
        .order_by(SensitiveWord.created_at.desc())
    )
    return list(rows.scalars().all())


async def create_sensitive_word(db: AsyncSession, tenant_id: int | None, body: SensitiveWordCreate) -> SensitiveWord:
    """创建敏感词规则。

    参数：
        db: 数据库会话
        tenant_id: 租户 ID（租户级规则）或 None（系统级规则）
        body: 敏感词创建请求体，包含 word（敏感词文本）、action（warn/transfer/block）、is_active 等

    返回：
        创建的 SensitiveWord ORM 对象

    异常：
        ValueError: 同一范围（租户级或系统级）内已存在相同的敏感词文本
    """
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
    """部分更新敏感词规则（仅修改传入的非空字段）。

    参数：
        db: 数据库会话
        tenant_id: 租户 ID 或 None
        item_id: 要更新的敏感词规则 ID
        body: 敏感词更新请求体（所有字段可选）

    返回：
        更新后的 SensitiveWord ORM 对象，若规则不存在或不属于该范围则返回 None
    """
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
    """检测文本是否命中敏感词，返回最高风险动作和命中列表。

    参数：
        db: 数据库会话
        tenant_id: 当前租户 ID
        content: 待检测的文本内容

    返回：
        {
            "action": str | None,   # 最高风险动作：None / "warn" / "transfer" / "block"
            "matches": [            # 命中的所有敏感词详情
                {"id": str, "word": str, "action": str},
                ...
            ]
        }

    检测逻辑：
        1. 同时加载系统级规则（tenant_id IS NULL）和当前租户级规则
        2. 对所有 is_active=True 的规则做子串匹配（content 包含敏感词即命中）
        3. 取所有命中规则中 action rank 最高的作为最终动作
        4. 优先级：warn(1) < transfer(2) < block(3)
    """
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
    """查询审计日志，支持按租户和操作类型过滤，分页返回。

    参数：
        db: 数据库会话
        tenant_id: 可选，按租户过滤；不传则返回全平台审计日志
        action: 可选，按操作类型过滤（如 "login"、"create_order"）
        page: 页码
        page_size: 每页条数

    返回：
        (审计日志列表, 总数) 元组，按创建时间倒序
    """
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
    """查询登录历史，支持按邮箱模糊匹配。

    参数：
        db: 数据库会话
        email: 可选，按邮箱模糊搜索（ILIKE %email%）
        page: 页码
        page_size: 每页条数

    返回：
        (登录历史列表, 总数) 元组，按创建时间倒序
    """
    conditions = [LoginHistory.email.ilike(f"%{email.strip()}%")] if email.strip() else []
    base = select(LoginHistory).where(*conditions)
    total = int(await db.scalar(select(func.count()).select_from(base.subquery())) or 0)
    rows = await db.execute(base.order_by(LoginHistory.created_at.desc()).offset((page - 1) * page_size).limit(page_size))
    return list(rows.scalars().all()), total
