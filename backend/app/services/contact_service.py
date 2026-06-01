"""联系人管理服务"""

import csv
import io
import json
from datetime import datetime, timezone

from sqlalchemy import and_, func, select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.contact import Contact
from app.models.employee import Employee
from app.schemas.contact import (
    ContactAssign,
    ContactCreate,
    ContactImportError,
    ContactImportResponse,
    ContactUpdate,
)


CONTACT_IMPORT_TEMPLATE = (
    "联系人名称,电话,地址,标签,分配员工ID,企微外部联系人ID,头像地址,外部ID JSON\n"
    "杭州湖滨烟酒店,13800010001,杭州市上城区湖滨路88号,VIP;零售客户,,wm_contact_0001,,"
    "\"{\"\"wecom_external_userid\"\":\"\"wm_contact_0001\"\"}\"\n"
)

_COLUMN_ALIASES = {
    "联系人名称": "name",
    "客户名称": "name",
    "名称": "name",
    "name": "name",
    "电话": "phone",
    "手机号": "phone",
    "phone": "phone",
    "地址": "address",
    "address": "address",
    "标签": "tags",
    "tags": "tags",
    "分配员工ID": "assigned_employee_id",
    "assignedEmployeeId": "assigned_employee_id",
    "assigned_employee_id": "assigned_employee_id",
    "企微外部联系人ID": "wecom_external_userid",
    "wecom_external_userid": "wecom_external_userid",
    "头像地址": "avatar_url",
    "avatarUrl": "avatar_url",
    "avatar_url": "avatar_url",
    "外部ID JSON": "external_ids",
    "externalIds": "external_ids",
    "external_ids": "external_ids",
}


async def _ensure_employee(
    db: AsyncSession,
    tenant_id: int,
    employee_id: int | None,
) -> None:
    if employee_id is None:
        return
    exists = await db.scalar(
        select(Employee.id).where(
            Employee.id == employee_id,
            Employee.tenant_id == tenant_id,
            Employee.deleted_at.is_(None),
        )
    )
    if exists is None:
        raise ValueError("分配员工不存在")


async def attach_assigned_employee_names(
    db: AsyncSession,
    contacts: list[Contact],
) -> None:
    employee_ids = {
        contact.assigned_employee_id
        for contact in contacts
        if contact.assigned_employee_id is not None
    }
    if not employee_ids:
        for contact in contacts:
            contact._assigned_employee_name = None
        return

    result = await db.execute(
        select(Employee.id, Employee.display_name, Employee.email).where(
            Employee.id.in_(employee_ids)
        )
    )
    employee_map = {
        employee_id: display_name or email
        for employee_id, display_name, email in result.all()
    }
    for contact in contacts:
        contact._assigned_employee_name = employee_map.get(contact.assigned_employee_id)


async def list_contacts(
    db: AsyncSession,
    tenant_id: int,
    *,
    keyword: str = "",
    tag: str | None = None,
    assigned_employee_id: int | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[Contact], int]:
    conditions = [Contact.tenant_id == tenant_id]
    clean_keyword = keyword.strip()

    if clean_keyword:
        pattern = f"%{clean_keyword}%"
        conditions.append(
            or_(
                Contact.name.ilike(pattern),
                Contact.phone.ilike(pattern),
                Contact.address.ilike(pattern),
            )
        )
    if tag:
        conditions.append(Contact.tags.contains([tag]))
    if assigned_employee_id is not None:
        conditions.append(Contact.assigned_employee_id == assigned_employee_id)

    base_query = select(Contact).where(and_(*conditions))
    total = await db.scalar(select(func.count()).select_from(base_query.subquery()))

    offset = (page - 1) * page_size
    result = await db.execute(
        base_query.order_by(Contact.updated_at.desc(), Contact.created_at.desc())
        .offset(offset)
        .limit(page_size)
    )
    items = list(result.scalars().all())
    await attach_assigned_employee_names(db, items)
    return items, total or 0


async def search_contacts(
    db: AsyncSession,
    tenant_id: int,
    *,
    keyword: str = "",
    limit: int = 20,
) -> tuple[list[Contact], int]:
    """兼容服务层调用方的轻量联系人搜索入口。

    页面列表使用 ``list_contacts`` 的完整分页能力；订单服务测试、Agent Skill
    等内部调用方只需要取少量联系人，因此保留一个语义更直接的搜索函数。这里仍然
    委托给统一查询实现，确保 tenant_id 隔离、员工展示名加载和关键词规则不会分叉。
    """
    return await list_contacts(
        db,
        tenant_id,
        keyword=keyword,
        page=1,
        page_size=max(1, min(limit, 100)),
    )


async def get_contact(
    db: AsyncSession,
    contact_id: int,
    tenant_id: int,
) -> Contact | None:
    contact = await db.scalar(
        select(Contact).where(Contact.id == contact_id, Contact.tenant_id == tenant_id)
    )
    if contact is not None:
        await attach_assigned_employee_names(db, [contact])
    return contact


async def create_contact(
    db: AsyncSession,
    tenant_id: int,
    body: ContactCreate,
) -> Contact:
    await _ensure_employee(db, tenant_id, body.assigned_employee_id)
    contact = Contact(
        tenant_id=tenant_id,
        name=body.name.strip(),
        avatar_url=body.avatar_url,
        phone=body.phone,
        address=body.address,
        external_ids=body.external_ids or {},
        tags=body.tags,
        assigned_employee_id=body.assigned_employee_id,
    )
    db.add(contact)
    await db.commit()
    await db.refresh(contact)
    await attach_assigned_employee_names(db, [contact])
    return contact


async def update_contact(
    db: AsyncSession,
    contact_id: int,
    tenant_id: int,
    body: ContactUpdate,
) -> Contact | None:
    contact = await get_contact(db, contact_id, tenant_id)
    if contact is None:
        return None

    data = body.model_dump(exclude_unset=True)
    if "assigned_employee_id" in data:
        await _ensure_employee(db, tenant_id, data["assigned_employee_id"])
    if "name" in data and data["name"] is not None:
        data["name"] = data["name"].strip()
    if "external_ids" in data and data["external_ids"] is None:
        data["external_ids"] = {}
    if "tags" in data and data["tags"] is None:
        data["tags"] = []

    for key, value in data.items():
        setattr(contact, key, value)

    contact.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(contact)
    await attach_assigned_employee_names(db, [contact])
    return contact


async def assign_contact(
    db: AsyncSession,
    contact_id: int,
    tenant_id: int,
    body: ContactAssign,
) -> Contact | None:
    contact = await get_contact(db, contact_id, tenant_id)
    if contact is None:
        return None

    await _ensure_employee(db, tenant_id, body.assigned_employee_id)
    contact.assigned_employee_id = body.assigned_employee_id
    contact.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(contact)
    await attach_assigned_employee_names(db, [contact])
    return contact


async def delete_contact(db: AsyncSession, contact_id: int, tenant_id: int) -> bool:
    contact = await get_contact(db, contact_id, tenant_id)
    if contact is None:
        return False
    await db.delete(contact)
    await db.commit()
    return True


async def aggregate_tags(db: AsyncSession, tenant_id: int) -> list[tuple[str, int]]:
    result = await db.execute(
        select(Contact.tags).where(Contact.tenant_id == tenant_id)
    )
    counts: dict[str, int] = {}
    for tags in result.scalars().all():
        if not isinstance(tags, list):
            continue
        for tag in tags:
            if isinstance(tag, str) and tag.strip():
                clean = tag.strip()
                counts[clean] = counts.get(clean, 0) + 1
    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))


def _normalize_header(header: str | None) -> str:
    return (header or "").strip().replace("\ufeff", "")


def _normalize_row(row: dict[str, str | None]) -> dict[str, str]:
    normalized: dict[str, str] = {}
    for key, value in row.items():
        alias = _COLUMN_ALIASES.get(_normalize_header(key))
        if alias:
            normalized[alias] = (value or "").strip()
    return normalized


def _parse_tags(value: str) -> list[str]:
    if not value:
        return []
    result: list[str] = []
    seen: set[str] = set()
    for raw_tag in value.replace("，", ";").replace(",", ";").split(";"):
        tag = raw_tag.strip()
        if tag and tag not in seen:
            seen.add(tag)
            result.append(tag)
    return result


def _parse_external_ids(row: dict[str, str]) -> dict:
    external_ids: dict = {}
    raw_json = row.get("external_ids", "")
    if raw_json:
        try:
            parsed = json.loads(raw_json)
        except json.JSONDecodeError:
            raise ValueError("外部ID JSON 格式不正确")
        if not isinstance(parsed, dict):
            raise ValueError("外部ID JSON 必须是对象")
        external_ids.update(parsed)

    wecom_external_userid = row.get("wecom_external_userid", "").strip()
    if wecom_external_userid:
        external_ids["wecom_external_userid"] = wecom_external_userid
    return external_ids


def _parse_assigned_employee_id(value: str) -> int | None:
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        raise ValueError("分配员工ID必须是数字")


async def _load_employee_ids(db: AsyncSession, tenant_id: int) -> set[int]:
    result = await db.execute(
        select(Employee.id).where(
            Employee.tenant_id == tenant_id,
            Employee.deleted_at.is_(None),
        )
    )
    return set(result.scalars().all())


async def _load_existing_identity_sets(
    db: AsyncSession,
    tenant_id: int,
) -> tuple[set[str], set[str], set[str]]:
    result = await db.execute(
        select(Contact.name, Contact.phone, Contact.external_ids).where(
            Contact.tenant_id == tenant_id
        )
    )
    names: set[str] = set()
    phones: set[str] = set()
    wecom_ids: set[str] = set()
    for name, phone, external_ids in result.all():
        if name:
            names.add(name)
        if phone:
            phones.add(phone)
        if isinstance(external_ids, dict):
            wecom_id = external_ids.get("wecom_external_userid")
            if isinstance(wecom_id, str) and wecom_id.strip():
                wecom_ids.add(wecom_id.strip())
    return names, phones, wecom_ids


async def import_contacts_csv(
    db: AsyncSession,
    tenant_id: int,
    content: bytes,
) -> ContactImportResponse:
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = content.decode("gbk")

    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise ValueError("CSV 文件为空或缺少表头")

    valid_employee_ids = await _load_employee_ids(db, tenant_id)
    existing_names, existing_phones, existing_wecom_ids = await _load_existing_identity_sets(
        db,
        tenant_id,
    )
    errors: list[ContactImportError] = []
    import_rows: list[tuple[int, dict]] = []
    seen_names: dict[str, int] = {}
    seen_phones: dict[str, int] = {}
    seen_wecom_ids: dict[str, int] = {}

    for row_number, raw_row in enumerate(reader, start=2):
        row = _normalize_row(raw_row)
        if not any(row.values()):
            continue

        row_errors: list[ContactImportError] = []
        name = row.get("name", "").strip()
        if not name:
            row_errors.append(ContactImportError(row=row_number, field="联系人名称", message="联系人名称不能为空"))
        elif len(name) > 200:
            row_errors.append(ContactImportError(row=row_number, field="联系人名称", message="联系人名称不能超过200个字符"))
        elif name in seen_names:
            row_errors.append(
                ContactImportError(
                    row=row_number,
                    field="联系人名称",
                    message=f"文件内联系人名称与第 {seen_names[name]} 行重复",
                )
            )
        elif name in existing_names:
            row_errors.append(ContactImportError(row=row_number, field="联系人名称", message="联系人名称已存在"))
        else:
            seen_names[name] = row_number

        phone = row.get("phone", "").strip() or None
        if phone and len(phone) > 20:
            row_errors.append(ContactImportError(row=row_number, field="电话", message="电话不能超过20个字符"))
        elif phone and phone in seen_phones:
            row_errors.append(
                ContactImportError(
                    row=row_number,
                    field="电话",
                    message=f"文件内电话与第 {seen_phones[phone]} 行重复",
                )
            )
        elif phone and phone in existing_phones:
            row_errors.append(ContactImportError(row=row_number, field="电话", message="电话已存在"))
        elif phone:
            seen_phones[phone] = row_number

        avatar_url = row.get("avatar_url", "").strip() or None
        if avatar_url and len(avatar_url) > 500:
            row_errors.append(ContactImportError(row=row_number, field="头像地址", message="头像地址不能超过500个字符"))

        try:
            external_ids = _parse_external_ids(row)
        except ValueError as exc:
            row_errors.append(ContactImportError(row=row_number, field="外部ID JSON", message=str(exc)))
            external_ids = {}

        wecom_id = external_ids.get("wecom_external_userid")
        if isinstance(wecom_id, str) and wecom_id.strip():
            clean_wecom_id = wecom_id.strip()
            external_ids["wecom_external_userid"] = clean_wecom_id
            if clean_wecom_id in seen_wecom_ids:
                row_errors.append(
                    ContactImportError(
                        row=row_number,
                        field="企微外部联系人ID",
                        message=f"文件内企微 ID 与第 {seen_wecom_ids[clean_wecom_id]} 行重复",
                    )
                )
            elif clean_wecom_id in existing_wecom_ids:
                row_errors.append(ContactImportError(row=row_number, field="企微外部联系人ID", message="企微 ID 已存在"))
            else:
                seen_wecom_ids[clean_wecom_id] = row_number

        try:
            assigned_employee_id = _parse_assigned_employee_id(row.get("assigned_employee_id", ""))
        except ValueError as exc:
            row_errors.append(ContactImportError(row=row_number, field="分配员工ID", message=str(exc)))
            assigned_employee_id = None
        if assigned_employee_id is not None and assigned_employee_id not in valid_employee_ids:
            row_errors.append(ContactImportError(row=row_number, field="分配员工ID", message="分配员工不存在"))

        errors.extend(row_errors)
        import_rows.append(
            (
                row_number,
                {
                    "tenant_id": tenant_id,
                    "name": name,
                    "avatar_url": avatar_url,
                    "phone": phone,
                    "address": row.get("address", "").strip() or None,
                    "external_ids": external_ids,
                    "tags": _parse_tags(row.get("tags", "")),
                    "assigned_employee_id": assigned_employee_id,
                },
            )
        )

    if not import_rows:
        return ContactImportResponse(
            success=False,
            total_rows=0,
            created_count=0,
            errors=[ContactImportError(row=1, field=None, message="没有可导入的数据行")],
        )

    if errors:
        errors.sort(key=lambda item: (item.row, item.field or ""))
        return ContactImportResponse(
            success=False,
            total_rows=len(import_rows),
            created_count=0,
            errors=errors,
        )

    db.add_all([Contact(**payload) for _, payload in import_rows])
    await db.commit()
    return ContactImportResponse(
        success=True,
        total_rows=len(import_rows),
        created_count=len(import_rows),
        errors=[],
    )
