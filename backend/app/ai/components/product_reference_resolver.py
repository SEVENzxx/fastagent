"""ProductReferenceResolver — 产品引用解析组件。

纯规则 + 上下文 + ProductLookupGateway 实现，不调用 LLM。
将用户文本中的产品引用解析为具体 product_id 或候选列表。

支持引用方式：
  - 实体显式 product_id
  - 序号引用（第一款、第3个、1、2）
  - 指代引用（这个、这款、它）
  - 对比延续（和第三款比）
  - 精确/模糊产品名

解析到 product_id 后必须重新校验 tenant_id/is_active。
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, Field

from app.ai.context.session_context import SessionContext


# ── 结果类型 ──


class ProductCandidate(BaseModel):
    """产品候选（1-based 序号）。"""

    index: int = 0
    product_id: int
    product_name: str


class ProductReferenceResult(BaseModel):
    """产品引用解析结果。"""

    resolved: bool = False
    product_id: int | None = None
    product_name: str | None = None
    candidates: list[ProductCandidate] = Field(default_factory=list)
    need_clarification: bool = False
    reason: str = ""


# ── 产品查询网关（抽象层） ──


class ProductInfo(BaseModel):
    """产品基本信息（网关返回）。"""

    product_id: int
    name: str
    is_active: bool
    tenant_id: int


class ProductLookupGateway(ABC):
    """产品查询网关——ProductReferenceResolver 依赖的抽象层。

    解析到 product_id 后必须通过此网关重新校验 tenant_id/is_active。
    测试时注入 FakeProductLookupGateway 替代真实数据库或 ProductSkill。
    """

    @abstractmethod
    async def validate_product(
        self,
        product_id: int,
        tenant_id: int,
    ) -> ProductInfo | None:
        """校验 product_id 在当前租户下是否可见（存在且 is_active=True）。"""

    @abstractmethod
    async def search_by_name(
        self,
        name: str,
        tenant_id: int,
        *,
        limit: int = 10,
    ) -> list[ProductInfo]:
        """按产品名搜索（精确+模糊），仅返回当前租户下可见的产品。"""


# ── 正则与解析辅助 ──

_CN_NUM_MAP: dict[str, int] = {
    "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
    "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
}

# 第X款 / 第X个
_RE_ORDINAL_CN = re.compile(r"第\s*([一二两三四五六七八九十\d]+)\s*[款个]")

# 裸数字：^\d+$
_RE_BARE_NUMBER = re.compile(r"^\s*(\d+)\s*$")

# 指代整句匹配
_RE_DEIXIS_FULL = re.compile(
    r"^\s*(这个|这款|这个呢|它|它们|那个|那款|刚才那个|刚刚那个|刚才那款|刚刚那款)\s*$"
)
# 指代前缀：文本以指代词开头（后接其他内容）。覆盖真实追问句如"这个耳机是否防水""它适合小孩吗"
_DEIXIS_PREFIXES: tuple[str, ...] = (
    "这个", "这款", "它", "它们",
    "那个", "那款",
    "刚才那个", "刚刚那个", "刚才那款", "刚刚那款",
)

# 对比延续：和X比、和X有什么区别、与X相比
_RE_COMPARE = re.compile(
    r"(?:和|与|跟)\s*第?\s*([一二两三四五六七八九十\d]+)\s*款?\s*(?:比|对比|比较|有什么区别|有何区别|有什么不同|有啥区别)"
)


def _parse_cn_ordinal(text: str) -> int | None:
    """解析中文序数，返回 1-based 索引。"""
    m = _RE_ORDINAL_CN.search(text)
    if not m:
        return None
    raw = m.group(1).strip()
    if raw.isdigit():
        return int(raw)
    return _CN_NUM_MAP.get(raw)


def _parse_bare_number(text: str) -> int | None:
    """解析裸数字（仅在上下文有候选时使用）。"""
    m = _RE_BARE_NUMBER.fullmatch(text)
    return int(m.group(1)) if m else None


def _is_deixis(text: str) -> bool:
    """判断文本是否为指代引用（整句匹配或以指代词开头）。

    支持真实追问句：
      - "这个" → "这个耳机是否防水""这个怎么样"
      - "它" → "它适合小孩吗""它多少钱"
      - "刚才那个" → "刚才那个还有货吗"
    """
    stripped = text.strip()
    if _RE_DEIXIS_FULL.fullmatch(stripped):
        return True
    if not stripped:
        return False
    return any(stripped.startswith(prefix) for prefix in _DEIXIS_PREFIXES)


def _parse_compare_ordinal(text: str) -> int | None:
    """从对比句中提取对比目标序号。"""
    m = _RE_COMPARE.search(text)
    if not m:
        return None
    raw = m.group(1).strip()
    if raw.isdigit():
        return int(raw)
    return _CN_NUM_MAP.get(raw)


def _is_compare_continuation(text: str) -> bool:
    """判断是否为对比延续语句。"""
    return bool(_RE_COMPARE.search(text))


def _int_to_cn(num: int) -> str:
    """将小数字（1-10）转为中文。"""
    rev = {v: k for k, v in _CN_NUM_MAP.items()}
    return rev.get(num, str(num))


# ── 上下文候选提取 ──


def _extract_candidate_id_name(
    item: Any,
) -> tuple[Any, str] | None:
    """从候选条目中提取 (id, name)，兼容多种格式。

    支持：
      - dict with id/name keys
      - dict with product_id/product_name keys
      - ProductCandidate 对象
      - 任意有 .product_id/.product_name 或 .id/.name 属性的对象
    """
    if isinstance(item, dict):
        if "id" in item:
            return item["id"], str(item.get("name", "") or "")
        if "product_id" in item:
            return item["product_id"], str(item.get("product_name", "") or "")
        return None
    if hasattr(item, "product_id") and hasattr(item, "product_name"):
        return item.product_id, item.product_name or ""
    if hasattr(item, "id") and hasattr(item, "name"):
        return item.id, item.name or ""
    return None


def _get_candidates_from_context(
    context: SessionContext,
) -> list[dict[str, Any]]:
    """从 SessionContext 提取候选列表，返回 [{id, name}, ...]。

    优先级：product_candidates > active_product_ids + active_product_names。
    """
    if context.product_candidates:
        result: list[dict[str, Any]] = []
        for c in context.product_candidates:
            id_name = _extract_candidate_id_name(c)
            if id_name is not None:
                result.append({"id": id_name[0], "name": id_name[1]})
        if result:
            return result

    if context.active_product_ids and context.active_product_names:
        return [
            {"id": pid, "name": name}
            for pid, name in zip(context.active_product_ids, context.active_product_names)
        ]

    return []


def _parse_ordinal_from_text(text: str) -> int | None:
    """从文本中解析序号，支持中文和裸数字。"""
    ordinal = _parse_cn_ordinal(text)
    if ordinal is not None:
        return ordinal
    return _parse_bare_number(text)


# ── 主解析器 ──


class ProductReferenceResolver:
    """产品引用解析器。

    按优先级解析：
      1. 实体中显式 product_id
      2. 对比延续（和X比）
      3. 序号引用（候选列表）
      4. 指代引用（last_product_id）
      5. 产品名搜索
    """

    def __init__(self, gateway: ProductLookupGateway) -> None:
        self._gateway = gateway

    async def resolve(
        self,
        text: str,
        entities: dict[str, Any],
        context: SessionContext,
        tenant_id: int,
    ) -> ProductReferenceResult:
        """解析产品引用。"""
        # 步骤 1: 实体中显式 product_id
        pid = entities.get("product_id")
        if pid is not None:
            return await self._resolve_by_id(int(pid), tenant_id)

        stripped = text.strip()
        if not stripped:
            return ProductReferenceResult(
                need_clarification=True,
                reason="用户消息为空，无法解析产品引用",
            )

        # 步骤 2: 对比延续（优先于普通序号，因为"和第三款比"含序号但不走普通解析）
        result = await self._try_resolve_compare(stripped, context, tenant_id)
        if result is not None:
            return result

        # 步骤 3: 序号引用
        result = await self._try_resolve_ordinal(stripped, context, tenant_id)
        if result is not None:
            return result

        # 步骤 4: 指代引用
        result = await self._try_resolve_deixis(stripped, context, tenant_id)
        if result is not None:
            return result

        # 步骤 5: 产品名搜索
        return await self._try_resolve_by_name(stripped, tenant_id)

    # ── 子解析方法 ──

    async def _resolve_by_id(
        self,
        product_id: int,
        tenant_id: int,
    ) -> ProductReferenceResult:
        """按 product_id 解析并校验。"""
        info = await self._gateway.validate_product(product_id, tenant_id)
        if info is None:
            return ProductReferenceResult(
                resolved=False,
                need_clarification=True,
                reason=f"产品 {product_id} 不存在或已下架",
            )
        return ProductReferenceResult(
            resolved=True,
            product_id=info.product_id,
            product_name=info.name,
            candidates=[ProductCandidate(index=1, product_id=info.product_id, product_name=info.name)],
            reason="按 product_id 解析",
        )

    async def _try_resolve_compare(
        self,
        text: str,
        context: SessionContext,
        tenant_id: int,
    ) -> ProductReferenceResult | None:
        """尝试从对比语句解析目标产品。"""
        if not _is_compare_continuation(text):
            return None

        ordinal = _parse_compare_ordinal(text)
        if ordinal is None:
            # 有对比句式但未解析出序号，可能是"和这个比"
            return await self._try_resolve_deixis(text, context, tenant_id)

        candidates = _get_candidates_from_context(context)
        if not candidates:
            return ProductReferenceResult(
                resolved=False,
                need_clarification=True,
                reason="没有商品候选列表，无法解析对比引用",
            )

        if ordinal < 1 or ordinal > len(candidates):
            return ProductReferenceResult(
                resolved=False,
                need_clarification=True,
                reason=f"序号 {ordinal} 超出候选范围（共 {len(candidates)} 个）",
            )

        target = candidates[ordinal - 1]
        pid = int(target["id"])
        info = await self._gateway.validate_product(pid, tenant_id)
        if info is None:
            return ProductReferenceResult(
                resolved=False,
                need_clarification=True,
                reason="对比目标产品已下架或不可见",
            )
        return ProductReferenceResult(
            resolved=True,
            product_id=pid,
            product_name=target["name"],
            candidates=[
                ProductCandidate(index=ordinal, product_id=pid, product_name=target["name"]),
            ],
            reason=f"对比延续解析：第{_int_to_cn(ordinal) if ordinal <= 10 else str(ordinal)}款",
        )

    async def _try_resolve_ordinal(
        self,
        text: str,
        context: SessionContext,
        tenant_id: int,
    ) -> ProductReferenceResult | None:
        """尝试从序号解析产品。"""
        ordinal = _parse_ordinal_from_text(text)
        if ordinal is None:
            return None

        candidates = _get_candidates_from_context(context)
        if not candidates:
            # 有数字但无候选，不当作序号（可能是数量/价格等）
            return None

        if ordinal < 1 or ordinal > len(candidates):
            return ProductReferenceResult(
                resolved=False,
                need_clarification=True,
                reason=f"序号 {ordinal} 超出候选范围（共 {len(candidates)} 个）",
            )

        target = candidates[ordinal - 1]
        pid = int(target["id"])
        info = await self._gateway.validate_product(pid, tenant_id)
        if info is None:
            return ProductReferenceResult(
                resolved=False,
                need_clarification=True,
                reason="所选产品已下架或不可见",
            )
        return ProductReferenceResult(
            resolved=True,
            product_id=pid,
            product_name=target["name"],
            candidates=[
                ProductCandidate(index=ordinal, product_id=pid, product_name=target["name"]),
            ],
            reason=f"序号解析：第{_int_to_cn(ordinal) if ordinal <= 10 else str(ordinal)}款",
        )

    async def _try_resolve_deixis(
        self,
        text: str,
        context: SessionContext,
        tenant_id: int,
    ) -> ProductReferenceResult | None:
        """尝试从指代引用解析产品。"""
        if not _is_deixis(text):
            return None

        # 优先读取 last_focus_product_id（架构文档命名），fallback 到 last_product_id
        last_pid_str = context.last_focus_product_id or context.last_product_id
        if not last_pid_str:
            return ProductReferenceResult(
                resolved=False,
                need_clarification=True,
                reason="没有最近浏览的商品，无法解析指代引用",
            )

        pid = int(last_pid_str)
        info = await self._gateway.validate_product(pid, tenant_id)
        if info is None:
            return ProductReferenceResult(
                resolved=False,
                need_clarification=True,
                reason="最近浏览的商品已下架或不可见",
            )
        return ProductReferenceResult(
            resolved=True,
            product_id=pid,
            product_name=info.name,
            candidates=[
                ProductCandidate(index=1, product_id=pid, product_name=info.name),
            ],
            reason=f"指代解析：{text}",
        )

    async def _try_resolve_by_name(
        self,
        text: str,
        tenant_id: int,
    ) -> ProductReferenceResult:
        """按产品名搜索。"""
        products = await self._gateway.search_by_name(text, tenant_id)
        if not products:
            return ProductReferenceResult(
                resolved=False,
                need_clarification=True,
                reason=f"未找到匹配「{text}」的产品",
            )

        candidates = [
            ProductCandidate(index=i + 1, product_id=p.product_id, product_name=p.name)
            for i, p in enumerate(products)
        ]

        if len(products) == 1:
            p = products[0]
            return ProductReferenceResult(
                resolved=True,
                product_id=p.product_id,
                product_name=p.name,
                candidates=candidates,
                reason="精确/模糊名称匹配",
            )

        # 多候选
        return ProductReferenceResult(
            resolved=False,
            need_clarification=True,
            candidates=candidates,
            reason=f"模糊名称匹配到 {len(products)} 个候选，需用户确认",
        )
