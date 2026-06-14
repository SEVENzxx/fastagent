"""商品 Schema"""

from datetime import datetime
from pydantic import field_serializer, field_validator

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

    name: str
    category_id: int | None = None
    category_path: str | None = None  # 完整分类路径（如"电子产品/手机/智能手机"），用于向量索引
    sku: str | None = None
    description: str | None = None
    price: float | None = None
    floor_price: float | None = None
    stock: int = 0
    is_sample: bool = False
    sales_template_id: int | None = None
    specs: dict | None = None
    attrs_json: dict | None = None
    feature_tags: list[str] | None = None
    scenario_tags: list[str] | None = None
    is_active: bool = True

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

    name: str | None = None
    category_id: int | None = None
    category_path: str | None = None  # 完整分类路径，用于向量索引
    sku: str | None = None
    description: str | None = None
    price: float | None = None
    floor_price: float | None = None
    stock: int | None = None
    is_sample: bool | None = None
    sales_template_id: int | None = None
    specs: dict | None = None
    attrs_json: dict | None = None
    feature_tags: list[str] | None = None
    scenario_tags: list[str] | None = None
    is_active: bool | None = None

    @field_validator("attrs_json")
    @classmethod
    def attrs_json_fixed_shape(cls, value: dict | None) -> dict:
        return _fixed_attrs_json(value)


class ProductResponse(CamelModel):
    """商品响应"""

    id: int
    tenant_id: int
    category_id: int | None = None
    name: str
    sku: str | None = None
    description: str | None = None
    price: float | None = None
    floor_price: float | None = None
    stock: int
    is_sample: bool
    sales_template_id: int | None = None
    specs: dict | None = None
    attrs_json: dict | None = None
    feature_tags: list[str] | None = None
    scenario_tags: list[str] | None = None
    is_active: bool
    created_at: datetime
    updated_at: datetime
    category_name: str | None = None

    @field_serializer("id", "tenant_id", "category_id", "sales_template_id")
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

    keyword: str = ""
    category_id: int | None = None
    is_active: bool | None = None
    is_sample: bool | None = None
    min_price: float | None = None
    max_price: float | None = None
    page: int = 1
    page_size: int = 20


class ProductListResponse(CamelModel):
    """商品列表响应"""

    items: list[ProductResponse]
    total: int
    page: int
    page_size: int


class ProductImportError(CamelModel):
    """商品导入错误"""

    row: int
    field: str | None = None
    message: str


class ProductImportResponse(CamelModel):
    """商品导入结果"""

    success: bool
    total_rows: int
    created_count: int
    errors: list[ProductImportError]
