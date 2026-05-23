"""商品 Schema"""

from datetime import datetime
from pydantic import field_serializer, field_validator

from app.schemas.base import CamelModel


class ProductCreate(CamelModel):
    """创建商品"""

    name: str
    category_id: int | None = None
    sku: str | None = None
    description: str | None = None
    price: float | None = None
    floor_price: float | None = None
    stock: int = 0
    is_sample: bool = False
    sales_template_id: int | None = None
    specs: dict | None = None
    is_active: bool = True

    @field_validator("name")
    @classmethod
    def name_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("商品名称不能为空")
        return v.strip()


class ProductUpdate(CamelModel):
    """更新商品"""

    name: str | None = None
    category_id: int | None = None
    sku: str | None = None
    description: str | None = None
    price: float | None = None
    floor_price: float | None = None
    stock: int | None = None
    is_sample: bool | None = None
    sales_template_id: int | None = None
    specs: dict | None = None
    is_active: bool | None = None


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
