"""联系人 Schema"""

from datetime import datetime

from pydantic import Field, field_serializer, field_validator

from app.schemas.base import CamelModel


class ContactCreate(CamelModel):
    """创建联系人"""

    name: str = Field(description="联系人名称")
    avatar_url: str | None = Field(None, description="头像 URL")
    phone: str | None = Field(None, description="联系电话")
    address: str | None = Field(None, description="地址")
    external_ids: dict | None = Field(None, description="外部平台 ID 映射")
    tags: list[str] = Field(default_factory=list, description="标签列表")
    assigned_employee_id: int | None = Field(None, description="分配坐席 ID")

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
    """更新联系人"""

    name: str | None = Field(None, description="联系人名称")
    avatar_url: str | None = Field(None, description="头像 URL")
    phone: str | None = Field(None, description="联系电话")
    address: str | None = Field(None, description="地址")
    external_ids: dict | None = Field(None, description="外部平台 ID 映射")
    tags: list[str] | None = Field(None, description="标签列表")
    assigned_employee_id: int | None = Field(None, description="分配坐席 ID")

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
    """分配联系人"""

    assigned_employee_id: int | None = Field(None, description="分配坐席 ID")


class ContactResponse(CamelModel):
    """联系人响应"""

    id: int = Field(description="联系人 ID")
    tenant_id: int = Field(description="租户 ID")
    name: str = Field(description="联系人名称")
    avatar_url: str | None = Field(None, description="头像 URL")
    phone: str | None = Field(None, description="联系电话")
    address: str | None = Field(None, description="地址")
    external_ids: dict | None = Field(None, description="外部平台 ID 映射")
    tags: list[str] = Field(default_factory=list, description="标签列表")
    merged_from: int | None = Field(None, description="合并来源联系人 ID")
    assigned_employee_id: int | None = Field(None, description="分配坐席 ID")
    assigned_employee_name: str | None = Field(None, description="分配坐席名称")
    created_at: datetime = Field(description="创建时间")
    updated_at: datetime = Field(description="更新时间")

    @field_serializer("id", "tenant_id", "merged_from", "assigned_employee_id")
    def serialize_bigint(self, value: int | None) -> str | None:
        if value is None:
            return None
        return str(value)


class ContactListResponse(CamelModel):
    """联系人列表响应"""

    items: list[ContactResponse] = Field(description="联系人列表")
    total: int = Field(description="总数")
    page: int = Field(description="当前页码")
    page_size: int = Field(description="每页条数")


class ContactTagAggregate(CamelModel):
    """标签聚合"""

    tag: str = Field(description="标签名称")
    count: int = Field(description="标签数量")


class ContactImportError(CamelModel):
    """联系人导入错误"""

    row: int = Field(description="出错行号")
    field: str | None = Field(None, description="出错字段名")
    message: str = Field(description="错误信息")


class ContactImportResponse(CamelModel):
    """联系人导入结果"""

    success: bool = Field(description="是否全部导入成功")
    total_rows: int = Field(description="总处理行数")
    created_count: int = Field(description="成功创建数")
    errors: list[ContactImportError] = Field(description="导入错误列表")
