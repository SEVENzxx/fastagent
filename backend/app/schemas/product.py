"""商品 Schema"""

from datetime import datetime

from pydantic import Field, field_serializer, field_validator

from app.schemas.base import CamelModel


def _fixed_attrs_json(value: dict | None) -> dict:
    if not isinstance(value, dict):
        return {"attr": {}}
    attr = value.get("attr")
    if isinstance(attr, dict):
        return {"attr": attr}
    return {"attr": value}


class ProductCreate(CamelModel):
    """创建商品"""

    name: str = Field(description="商品名称")
    category_id: int | None = Field(None, description="分类 ID")
    category_path: str | None = Field(None, description='完整分类路径（如"电子产品/手机/智能手机"），用于向量索引')
    sku: str | None = Field(None, description="SKU 编码")
    description: str | None = Field(None, description="商品描述")
    price: float | None = Field(None, description="售价")
    floor_price: float | None = Field(None, description="底价")
    stock: int = Field(0, description="库存数量")
    is_sample: bool = Field(False, description="是否样品")
    specs: dict | None = Field(None, description="规格参数（JSON）")
    attrs_json: dict | None = Field(None, description="扩展属性（JSON）")
    feature_tags: list[str] | None = Field(None, description="功能标签列表")
    scenario_tags: list[str] | None = Field(None, description="适用场景标签列表")
    is_active: bool = Field(True, description="是否启用（软删除标记）")

    @field_validator("name")
    @classmethod
    def name_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("商品名称不能为空")
        return v.strip()

    @field_validator("attrs_json")
    @classmethod
    def attrs_json_fixed_shape(cls, value: dict | None) -> dict:
        return _fixed_attrs_json(value)


class ProductUpdate(CamelModel):
    """更新商品"""

    name: str | None = Field(None, description="商品名称")
    category_id: int | None = Field(None, description="分类 ID")
    category_path: str | None = Field(None, description="完整分类路径，用于向量索引")
    sku: str | None = Field(None, description="SKU 编码")
    description: str | None = Field(None, description="商品描述")
    price: float | None = Field(None, description="售价")
    floor_price: float | None = Field(None, description="底价")
    stock: int | None = Field(None, description="库存数量")
    is_sample: bool | None = Field(None, description="是否样品")
    specs: dict | None = Field(None, description="规格参数（JSON）")
    attrs_json: dict | None = Field(None, description="扩展属性（JSON）")
    feature_tags: list[str] | None = Field(None, description="功能标签列表")
    scenario_tags: list[str] | None = Field(None, description="适用场景标签列表")
    is_active: bool | None = Field(None, description="是否启用")

    @field_validator("attrs_json")
    @classmethod
    def attrs_json_fixed_shape(cls, value: dict | None) -> dict:
        return _fixed_attrs_json(value)


class ProductResponse(CamelModel):
    """商品响应"""

    id: int = Field(description="商品 ID")
    tenant_id: int = Field(description="租户 ID")
    category_id: int | None = Field(None, description="分类 ID")
    name: str = Field(description="商品名称")
    sku: str | None = Field(None, description="SKU 编码")
    description: str | None = Field(None, description="商品描述")
    price: float | None = Field(None, description="售价")
    floor_price: float | None = Field(None, description="底价")
    stock: int = Field(description="库存数量")
    is_sample: bool = Field(description="是否样品")
    specs: dict | None = Field(None, description="规格参数（JSON）")
    attrs_json: dict | None = Field(None, description="扩展属性（JSON）")
    feature_tags: list[str] | None = Field(None, description="功能标签列表")
    scenario_tags: list[str] | None = Field(None, description="适用场景标签列表")
    is_active: bool = Field(description="是否启用")
    created_at: datetime = Field(description="创建时间")
    updated_at: datetime = Field(description="更新时间")
    category_name: str | None = Field(None, description="分类名称")

    @field_serializer("id", "tenant_id", "category_id")
    def serialize_bigint(self, value: int | None) -> str | None:
        if value is None:
            return None
        return str(value)

    @field_serializer("price", "floor_price")
    def serialize_decimal(self, value: float | None) -> float | None:
        return value

    @field_validator("attrs_json")
    @classmethod
    def attrs_json_fixed_shape(cls, value: dict | None) -> dict:
        return _fixed_attrs_json(value)


class ProductSearchParams(CamelModel):
    """商品搜索参数"""

    keyword: str = Field(default="", description="搜索关键词")
    category_id: int | None = Field(None, description="分类 ID 过滤")
    is_active: bool | None = Field(None, description="是否启用过滤")
    is_sample: bool | None = Field(None, description="是否样品过滤")
    min_price: float | None = Field(None, description="最低价格")
    max_price: float | None = Field(None, description="最高价格")
    page: int = Field(1, description="当前页码")
    page_size: int = Field(20, description="每页条数")


class ProductListResponse(CamelModel):
    """商品列表响应"""

    items: list[ProductResponse] = Field(description="商品列表")
    total: int = Field(description="总数")
    page: int = Field(description="当前页码")
    page_size: int = Field(description="每页条数")


class ProductImportError(CamelModel):
    """商品导入错误"""

    row: int = Field(description="出错行号")
    field: str | None = Field(None, description="出错字段名")
    message: str = Field(description="错误信息")


class ProductImportResponse(CamelModel):
    """商品导入结果"""

    success: bool = Field(description="是否全部导入成功")
    total_rows: int = Field(description="总处理行数")
    created_count: int = Field(description="成功创建数")
    errors: list[ProductImportError] = Field(description="导入错误列表")
