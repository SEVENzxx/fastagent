"""联系人 Schema"""

from datetime import datetime

from pydantic import Field, field_serializer, field_validator

from app.schemas.base import CamelModel


class ContactCreate(CamelModel):
    name: str
    avatar_url: str | None = None
    phone: str | None = None
    address: str | None = None
    external_ids: dict | None = None
    tags: list[str] = Field(default_factory=list)
    assigned_employee_id: int | None = None

    @field_validator("name")
    @classmethod
    def name_not_empty(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("联系人名称不能为空")
        return value

    @field_validator("tags")
    @classmethod
    def normalize_tags(cls, value: list[str]) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for tag in value:
            clean = tag.strip()
            if clean and clean not in seen:
                seen.add(clean)
                result.append(clean)
        return result


class ContactUpdate(CamelModel):
    name: str | None = None
    avatar_url: str | None = None
    phone: str | None = None
    address: str | None = None
    external_ids: dict | None = None
    tags: list[str] | None = None
    assigned_employee_id: int | None = None

    @field_validator("name")
    @classmethod
    def name_not_empty(cls, value: str | None) -> str | None:
        if value is None:
            return value
        value = value.strip()
        if not value:
            raise ValueError("联系人名称不能为空")
        return value

    @field_validator("tags")
    @classmethod
    def normalize_tags(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return value
        result: list[str] = []
        seen: set[str] = set()
        for tag in value:
            clean = tag.strip()
            if clean and clean not in seen:
                seen.add(clean)
                result.append(clean)
        return result


class ContactAssign(CamelModel):
    assigned_employee_id: int | None = None


class ContactResponse(CamelModel):
    id: int
    tenant_id: int
    name: str
    avatar_url: str | None = None
    phone: str | None = None
    address: str | None = None
    external_ids: dict | None = None
    tags: list[str] = Field(default_factory=list)
    merged_from: int | None = None
    assigned_employee_id: int | None = None
    assigned_employee_name: str | None = None
    created_at: datetime
    updated_at: datetime

    @field_serializer("id", "tenant_id", "merged_from", "assigned_employee_id")
    def serialize_bigint(self, value: int | None) -> str | None:
        if value is None:
            return None
        return str(value)


class ContactListResponse(CamelModel):
    items: list[ContactResponse]
    total: int
    page: int
    page_size: int


class ContactTagAggregate(CamelModel):
    tag: str
    count: int


class ContactImportError(CamelModel):
    row: int
    field: str | None = None
    message: str


class ContactImportResponse(CamelModel):
    success: bool
    total_rows: int
    created_count: int
    errors: list[ContactImportError]
