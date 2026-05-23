"""Product management service."""

import csv
import io
import json
from datetime import datetime, timezone

from sqlalchemy import and_, func, select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.category import Category
from app.models.product import Product
from app.schemas.product import ProductCreate, ProductImportError, ProductImportResponse, ProductUpdate


PRODUCT_IMPORT_TEMPLATE = (
    "商品名称,SKU,分类路径,售价,底价,库存,是否样品,状态,商品描述,规格JSON\n"
    "西湖龙井 500g,LJ-500,茶叶/绿茶/龙井,168.00,120.00,100,否,上架,明前龙井,"
    "\"{\"\"规格\"\":\"\"500g\"\",\"\"产地\"\":\"\"杭州\"\"}\"\n"
)

_COLUMN_ALIASES = {
    "商品名称": "name",
    "name": "name",
    "名称": "name",
    "SKU": "sku",
    "sku": "sku",
    "分类ID": "category_id",
    "categoryId": "category_id",
    "category_id": "category_id",
    "分类路径": "category_path",
    "categoryPath": "category_path",
    "category_path": "category_path",
    "售价": "price",
    "价格": "price",
    "price": "price",
    "底价": "floor_price",
    "floorPrice": "floor_price",
    "floor_price": "floor_price",
    "库存": "stock",
    "stock": "stock",
    "是否样品": "is_sample",
    "isSample": "is_sample",
    "is_sample": "is_sample",
    "状态": "is_active",
    "isActive": "is_active",
    "is_active": "is_active",
    "商品描述": "description",
    "描述": "description",
    "description": "description",
    "规格JSON": "specs",
    "规格": "specs",
    "specs": "specs",
}


async def _ensure_category(
    db: AsyncSession,
    tenant_id: int,
    category_id: int | None,
) -> None:
    if category_id is None:
        return
    exists = await db.scalar(
        select(Category.id).where(
            Category.id == category_id,
            Category.tenant_id == tenant_id,
        )
    )
    if exists is None:
        raise ValueError("分类不存在")


async def _ensure_unique_sku(
    db: AsyncSession,
    tenant_id: int,
    sku: str | None,
    *,
    exclude_product_id: int | None = None,
) -> str | None:
    clean_sku = sku.strip() if sku else None
    if not clean_sku:
        return None

    conditions = [Product.tenant_id == tenant_id, Product.sku == clean_sku]
    if exclude_product_id is not None:
        conditions.append(Product.id != exclude_product_id)

    existing = await db.scalar(select(Product.id).where(and_(*conditions)))
    if existing is not None:
        raise ValueError("SKU 已存在")
    return clean_sku


async def _ensure_unique_name(
    db: AsyncSession,
    tenant_id: int,
    name: str,
    category_id: int | None,
    *,
    exclude_product_id: int | None = None,
) -> None:
    conditions = [
        Product.tenant_id == tenant_id,
        Product.name == name,
        Product.category_id.is_(None)
        if category_id is None
        else Product.category_id == category_id,
    ]
    if exclude_product_id is not None:
        conditions.append(Product.id != exclude_product_id)

    existing = await db.scalar(select(Product.id).where(and_(*conditions)))
    if existing is not None:
        raise ValueError("同一分类下商品名称已存在")


async def list_products(
    db: AsyncSession,
    tenant_id: int,
    *,
    keyword: str = "",
    category_id: int | None = None,
    is_active: bool | None = None,
    is_sample: bool | None = None,
    min_price: float | None = None,
    max_price: float | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[Product], int]:
    conditions = [Product.tenant_id == tenant_id]
    clean_keyword = keyword.strip()

    if clean_keyword:
        pattern = f"%{clean_keyword}%"
        conditions.append(
            or_(
                Product.name.ilike(pattern),
                Product.sku.ilike(pattern),
                Product.description.ilike(pattern),
            )
        )
    if category_id is not None:
        conditions.append(Product.category_id == category_id)
    if is_active is not None:
        conditions.append(Product.is_active == is_active)
    if is_sample is not None:
        conditions.append(Product.is_sample == is_sample)
    if min_price is not None:
        conditions.append(Product.price >= min_price)
    if max_price is not None:
        conditions.append(Product.price <= max_price)

    base_query = select(Product).where(and_(*conditions))
    total = await db.scalar(select(func.count()).select_from(base_query.subquery()))

    offset = (page - 1) * page_size
    result = await db.execute(
        base_query.order_by(Product.updated_at.desc(), Product.created_at.desc())
        .offset(offset)
        .limit(page_size)
    )
    items = list(result.scalars().all())
    await attach_category_names(db, items)
    return items, total or 0


async def attach_category_names(db: AsyncSession, products: list[Product]) -> None:
    category_ids = {item.category_id for item in products if item.category_id is not None}
    if not category_ids:
        for product in products:
            product._category_name = None
        return

    result = await db.execute(
        select(Category.id, Category.name).where(Category.id.in_(category_ids))
    )
    category_map = {category_id: name for category_id, name in result.all()}
    for product in products:
        product._category_name = category_map.get(product.category_id)


async def get_product(
    db: AsyncSession, product_id: int, tenant_id: int
) -> Product | None:
    product = await db.scalar(
        select(Product).where(
            Product.id == product_id,
            Product.tenant_id == tenant_id,
        )
    )
    if product is not None:
        await attach_category_names(db, [product])
    return product


async def create_product(
    db: AsyncSession, tenant_id: int, body: ProductCreate
) -> Product:
    name = body.name.strip()
    if not name:
        raise ValueError("商品名称不能为空")

    await _ensure_category(db, tenant_id, body.category_id)
    sku = await _ensure_unique_sku(db, tenant_id, body.sku)
    await _ensure_unique_name(db, tenant_id, name, body.category_id)

    product = Product(
        tenant_id=tenant_id,
        category_id=body.category_id,
        name=name,
        sku=sku,
        description=body.description.strip() if body.description else None,
        price=body.price,
        floor_price=body.floor_price,
        stock=body.stock,
        is_sample=body.is_sample,
        sales_template_id=body.sales_template_id,
        specs=body.specs,
        is_active=body.is_active,
    )
    db.add(product)
    await db.commit()
    await db.refresh(product)
    await attach_category_names(db, [product])
    return product


async def update_product(
    db: AsyncSession,
    product_id: int,
    tenant_id: int,
    body: ProductUpdate,
) -> Product | None:
    product = await get_product(db, product_id, tenant_id)
    if product is None:
        return None

    data = body.model_dump(exclude_unset=True)
    if "name" in data and data["name"] is not None:
        data["name"] = data["name"].strip()
        if not data["name"]:
            raise ValueError("商品名称不能为空")
    if "sku" in data:
        data["sku"] = await _ensure_unique_sku(
            db,
            tenant_id,
            data["sku"],
            exclude_product_id=product_id,
        )
    if "category_id" in data:
        await _ensure_category(db, tenant_id, data["category_id"])
    if "description" in data and data["description"]:
        data["description"] = data["description"].strip()

    next_name = data.get("name", product.name)
    next_category_id = data.get("category_id", product.category_id)
    await _ensure_unique_name(
        db,
        tenant_id,
        next_name,
        next_category_id,
        exclude_product_id=product_id,
    )

    for key, value in data.items():
        setattr(product, key, value)

    product.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(product)
    await attach_category_names(db, [product])
    return product


async def delete_product(
    db: AsyncSession, product_id: int, tenant_id: int
) -> bool:
    product = await get_product(db, product_id, tenant_id)
    if product is None:
        return False

    await db.delete(product)
    await db.commit()
    return True


def _normalize_header(header: str | None) -> str:
    return (header or "").strip().replace("\ufeff", "")


def _normalize_row(row: dict[str, str | None]) -> dict[str, str]:
    normalized: dict[str, str] = {}
    for key, value in row.items():
        alias = _COLUMN_ALIASES.get(_normalize_header(key))
        if alias:
            normalized[alias] = (value or "").strip()
    return normalized


def _parse_bool(value: str, *, default: bool) -> bool:
    if not value:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "y", "是", "上架", "启用"}:
        return True
    if normalized in {"0", "false", "no", "n", "否", "下架", "停用"}:
        return False
    raise ValueError("只能填写 是/否、上架/下架 或 true/false")


def _parse_float(value: str, field_name: str) -> float | None:
    if not value:
        return None
    try:
        number = float(value)
    except ValueError:
        raise ValueError(f"{field_name}必须是数字")
    if number < 0:
        raise ValueError(f"{field_name}不能为负数")
    return number


def _parse_stock(value: str) -> int:
    if not value:
        return 0
    try:
        number = int(value)
    except ValueError:
        raise ValueError("库存必须是整数")
    if number < 0:
        raise ValueError("库存不能为负数")
    return number


def _parse_specs(value: str) -> dict | None:
    if not value:
        return None
    try:
        specs = json.loads(value)
    except json.JSONDecodeError:
        raise ValueError("规格JSON格式不正确")
    if not isinstance(specs, dict):
        raise ValueError("规格JSON必须是对象")
    return specs


async def _load_categories(db: AsyncSession, tenant_id: int) -> tuple[dict[int, Category], dict[str, int]]:
    result = await db.execute(
        select(Category).where(Category.tenant_id == tenant_id).order_by(Category.created_at)
    )
    categories = list(result.scalars().all())
    by_id = {category.id: category for category in categories}
    path_map: dict[str, int] = {}

    def build_path(category: Category) -> str:
        names = [category.name]
        parent_id = category.parent_id
        while parent_id is not None and parent_id in by_id:
            parent = by_id[parent_id]
            names.append(parent.name)
            parent_id = parent.parent_id
        return "/".join(reversed(names))

    for category in categories:
        path_map[build_path(category)] = category.id
    return by_id, path_map


async def _resolve_import_category(
    row: dict[str, str],
    categories_by_id: dict[int, Category],
    category_paths: dict[str, int],
) -> int | None:
    category_id_text = row.get("category_id", "")
    if category_id_text:
        try:
            category_id = int(category_id_text)
        except ValueError:
            raise ValueError("分类ID必须是数字")
        if category_id not in categories_by_id:
            raise ValueError("分类ID不存在")
        return category_id

    category_path = row.get("category_path", "")
    if not category_path:
        return None
    normalized_path = "/".join(part.strip() for part in category_path.split("/") if part.strip())
    if not normalized_path:
        return None
    category_id = category_paths.get(normalized_path)
    if category_id is None:
        raise ValueError("分类路径不存在，请使用如 白酒/酱香型 的完整路径")
    return category_id


async def import_products_csv(
    db: AsyncSession,
    tenant_id: int,
    content: bytes,
) -> ProductImportResponse:
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = content.decode("gbk")

    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise ValueError("CSV 文件为空或缺少表头")

    categories_by_id, category_paths = await _load_categories(db, tenant_id)
    products_to_create: list[Product] = []
    errors: list[ProductImportError] = []
    seen_skus: dict[str, int] = {}
    seen_names: dict[tuple[int | None, str], int] = {}
    import_rows: list[tuple[int, dict, str | None, int | None]] = []

    for index, raw_row in enumerate(reader, start=2):
        row = _normalize_row(raw_row)
        if not any(row.values()):
            continue

        name = row.get("name", "").strip()
        row_errors: list[ProductImportError] = []
        if not name:
            row_errors.append(ProductImportError(row=index, field="商品名称", message="商品名称不能为空"))
        if len(name) > 300:
            row_errors.append(ProductImportError(row=index, field="商品名称", message="商品名称不能超过300个字符"))

        category_id: int | None = None
        try:
            category_id = await _resolve_import_category(row, categories_by_id, category_paths)
        except ValueError as exc:
            row_errors.append(ProductImportError(row=index, field="分类", message=str(exc)))

        sku = row.get("sku", "").strip() or None
        if sku and len(sku) > 100:
            row_errors.append(ProductImportError(row=index, field="SKU", message="SKU不能超过100个字符"))
        if sku:
            if sku in seen_skus:
                row_errors.append(
                    ProductImportError(
                        row=index,
                        field="SKU",
                        message=f"文件内 SKU 与第 {seen_skus[sku]} 行重复",
                    )
                )
            else:
                seen_skus[sku] = index

        name_key = (category_id, name)
        if name:
            if name_key in seen_names:
                row_errors.append(
                    ProductImportError(
                        row=index,
                        field="商品名称",
                        message=f"文件内同一分类商品名称与第 {seen_names[name_key]} 行重复",
                    )
                )
            else:
                seen_names[name_key] = index

        try:
            price = _parse_float(row.get("price", ""), "售价")
        except ValueError as exc:
            row_errors.append(ProductImportError(row=index, field="售价", message=str(exc)))
            price = None
        try:
            floor_price = _parse_float(row.get("floor_price", ""), "底价")
        except ValueError as exc:
            row_errors.append(ProductImportError(row=index, field="底价", message=str(exc)))
            floor_price = None
        if price is not None and floor_price is not None and floor_price > price:
            row_errors.append(ProductImportError(row=index, field="底价", message="底价不能高于售价"))
        try:
            stock = _parse_stock(row.get("stock", ""))
        except ValueError as exc:
            row_errors.append(ProductImportError(row=index, field="库存", message=str(exc)))
            stock = 0
        try:
            is_sample = _parse_bool(row.get("is_sample", ""), default=False)
        except ValueError as exc:
            row_errors.append(ProductImportError(row=index, field="是否样品", message=str(exc)))
            is_sample = False
        try:
            is_active = _parse_bool(row.get("is_active", ""), default=True)
        except ValueError as exc:
            row_errors.append(ProductImportError(row=index, field="状态", message=str(exc)))
            is_active = True
        try:
            specs = _parse_specs(row.get("specs", ""))
        except ValueError as exc:
            row_errors.append(ProductImportError(row=index, field="规格JSON", message=str(exc)))
            specs = None

        errors.extend(row_errors)
        import_rows.append(
            (
                index,
                {
                    "name": name,
                    "category_id": category_id,
                    "description": row.get("description", "").strip() or None,
                    "price": price,
                    "floor_price": floor_price,
                    "stock": stock,
                    "is_sample": is_sample,
                    "specs": specs,
                    "is_active": is_active,
                },
                sku,
                category_id,
            )
        )

    if not import_rows:
        return ProductImportResponse(
            success=False,
            total_rows=0,
            created_count=0,
            errors=[ProductImportError(row=1, field=None, message="没有可导入的数据行")],
        )

    skus = [sku for _, _, sku, _ in import_rows if sku]
    if skus:
        result = await db.execute(
            select(Product.sku).where(Product.tenant_id == tenant_id, Product.sku.in_(skus))
        )
        existing_skus = set(result.scalars().all())
        for row_number, _, sku, _ in import_rows:
            if sku in existing_skus:
                errors.append(ProductImportError(row=row_number, field="SKU", message="SKU 已存在"))

    names = [(payload["category_id"], payload["name"]) for _, payload, _, _ in import_rows]
    existing_name_rows = await db.execute(
        select(Product.category_id, Product.name).where(
            Product.tenant_id == tenant_id,
            Product.name.in_([name for _, name in names]),
        )
    )
    existing_names = set(existing_name_rows.all())
    for row_number, payload, _, _ in import_rows:
        if (payload["category_id"], payload["name"]) in existing_names:
            errors.append(
                ProductImportError(
                    row=row_number,
                    field="商品名称",
                    message="同一分类下商品名称已存在",
                )
            )

    if errors:
        errors.sort(key=lambda item: (item.row, item.field or ""))
        return ProductImportResponse(
            success=False,
            total_rows=len(import_rows),
            created_count=0,
            errors=errors,
        )

    for _, payload, sku, _ in import_rows:
        products_to_create.append(Product(tenant_id=tenant_id, sku=sku, **payload))

    db.add_all(products_to_create)
    await db.commit()
    return ProductImportResponse(
        success=True,
        total_rows=len(import_rows),
        created_count=len(products_to_create),
        errors=[],
    )
