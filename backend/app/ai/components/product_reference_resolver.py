"""ProductReferenceResolver — 产品引用解析组件。

纯规则 + 上下文实现，不调用 LLM。产品校验和搜索通过注入的 ProductLookup 完成，
避免组件绕过 SkillGateway 直接访问数据库。
"""

from __future__ import annotations

import logging
import re
from typing import Any, Protocol

from pydantic import BaseModel, Field

from app.ai.context.session_context import SessionContext

logger = logging.getLogger(__name__)


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


class ProductLookup(Protocol):
    """产品查询端口，由 Handler 注入基于 SkillGateway 的实现。"""

    async def get_detail(self, product_id: int, tenant_id: int) -> dict[str, Any] | None:
        """查询并校验产品详情。"""
        ...

    async def search(
        self,
        name: str,
        tenant_id: int,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """按名称搜索产品候选。"""
        ...

# ── 正则与解析辅助 ──

_CN_NUM_MAP: dict[str, int] = {
    "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
    "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
}
_RE_ORDINAL_CN = re.compile(r"第\s*([一二两三四五六七八九十\d]+)\s*[款个]")
_RE_BARE_NUMBER = re.compile(r"^\s*(\d+)\s*$")
_RE_DEIXIS_FULL = re.compile(
    r"^\s*(这个|这款|这个呢|它|它们|那个|那款|刚才那个|刚刚那个|刚才那款|刚刚那款)\s*$"
)
_DEIXIS_PREFIXES: tuple[str, ...] = (
    "这个", "这款", "它", "它们", "那个", "那款",
    "刚才那个", "刚刚那个", "刚才那款", "刚刚那款",
)
_RE_COMPARE = re.compile(
    r"(?:和|与|跟)\s*第?\s*([一二两三四五六七八九十\d]+)\s*款?\s*(?:比|对比|比较|有什么区别|有何区别|有什么不同|有啥区别)"
)


def _parse_cn_ordinal(text: str) -> int | None:
    m = _RE_ORDINAL_CN.search(text)
    if not m:
        return None
    raw = m.group(1).strip()
    return int(raw) if raw.isdigit() else _CN_NUM_MAP.get(raw)


def _parse_bare_number(text: str) -> int | None:
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
    return bool(stripped) and any(stripped.startswith(p) for p in _DEIXIS_PREFIXES)


def _parse_compare_ordinal(text: str) -> int | None:
    """从对比句中提取对比目标序号。"""
    m = _RE_COMPARE.search(text)
    if not m:
        return None
    raw = m.group(1).strip()
    return int(raw) if raw.isdigit() else _CN_NUM_MAP.get(raw)


def _is_compare_continuation(text: str) -> bool:
    """判断是否为对比延续语句。"""
    return bool(_RE_COMPARE.search(text))


def _int_to_cn(num: int) -> str:
    """将小数字（1-10）转为中文。"""
    rev = {v: k for k, v in _CN_NUM_MAP.items()}
    return rev.get(num, str(num))


def _extract_candidate_id_name(item: Any) -> tuple[Any, str] | None:
    """从候选条目中提取 (id, name)，兼容多种格式。"""
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


def _get_candidates_from_context(context: SessionContext) -> list[dict[str, Any]]:
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
    return ordinal if ordinal is not None else _parse_bare_number(text)


# ── 主解析器 ──


class ProductReferenceResolver:
    """产品引用解析器。"""

    def __init__(self, lookup: ProductLookup | None = None) -> None:
        self._lookup = lookup

    async def resolve(
        self, text: str, entities: dict[str, Any],
        context: SessionContext, tenant_id: int,
    ) -> ProductReferenceResult:
        """解析产品引用。"""
        # 步骤 1: 实体中显式 product_id
        pid = entities.get("product_id")
        if pid is not None:
            return await self._resolve_by_id(int(pid), tenant_id)

        stripped = text.strip()
        if not stripped:
            return ProductReferenceResult(need_clarification=True, reason="用户消息为空")

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

    # ── 内部查询（通过注入端口，避免组件直接开 DB session） ──

    async def _validate(self, pid: int, tenant_id: int) -> dict[str, Any] | None:
        if self._lookup is None:
            logger.debug("产品校验缺少 lookup: pid=%s tenant_id=%s", pid, tenant_id)
            return None
        try:
            return await self._lookup.get_detail(pid, tenant_id)
        except Exception:
            logger.debug("产品校验失败: pid=%s tenant_id=%s", pid, tenant_id)
            return None

    async def _search(self, name: str, tenant_id: int, limit: int = 10) -> list[dict[str, Any]]:
        if self._lookup is None:
            logger.debug("产品搜索缺少 lookup: name=%s tenant_id=%s", name[:80], tenant_id)
            return []
        try:
            return await self._lookup.search(name, tenant_id, limit)
        except Exception:
            logger.debug("产品搜索失败: name=%s tenant_id=%s", name[:80], tenant_id)
            return []

    # ── 子解析方法 ──

    async def _resolve_by_id(self, pid: int, tenant_id: int) -> ProductReferenceResult:
        info = await self._validate(pid, tenant_id)
        if info is None:
            return ProductReferenceResult(resolved=False, need_clarification=True, reason=f"产品 {pid} 不存在或已下架")
        name = info.get("name", "")
        return ProductReferenceResult(
            resolved=True, product_id=pid, product_name=name,
            candidates=[ProductCandidate(index=1, product_id=pid, product_name=name)],
            reason="按 product_id 解析",
        )

    async def _try_resolve_compare(
        self, text: str, context: SessionContext, tenant_id: int,
    ) -> ProductReferenceResult | None:
        """尝试从对比语句解析目标产品。"""
        if not _is_compare_continuation(text):
            return None
        ordinal = _parse_compare_ordinal(text)
        if ordinal is None:
            return await self._try_resolve_deixis(text, context, tenant_id)
        candidates = _get_candidates_from_context(context)
        if not candidates:
            return ProductReferenceResult(need_clarification=True, reason="没有商品候选列表")
        if ordinal < 1 or ordinal > len(candidates):
            return ProductReferenceResult(need_clarification=True,
                reason=f"序号 {ordinal} 超出候选范围（共 {len(candidates)} 个）")
        target = candidates[ordinal - 1]
        pid = int(target["id"])
        info = await self._validate(pid, tenant_id)
        if info is None:
            return ProductReferenceResult(need_clarification=True, reason="对比目标产品已下架或不可见")
        return ProductReferenceResult(
            resolved=True, product_id=pid, product_name=target["name"],
            candidates=[ProductCandidate(index=ordinal, product_id=pid, product_name=target["name"])],
            reason=f"对比延续解析：第{_int_to_cn(ordinal) if ordinal <= 10 else str(ordinal)}款",
        )

    async def _try_resolve_ordinal(
        self, text: str, context: SessionContext, tenant_id: int,
    ) -> ProductReferenceResult | None:
        """尝试从序号解析产品。"""
        ordinal = _parse_ordinal_from_text(text)
        if ordinal is None:
            return None
        candidates = _get_candidates_from_context(context)
        if not candidates:
            return None
        if ordinal < 1 or ordinal > len(candidates):
            return ProductReferenceResult(need_clarification=True,
                reason=f"序号 {ordinal} 超出候选范围（共 {len(candidates)} 个）")
        target = candidates[ordinal - 1]
        pid = int(target["id"])
        info = await self._validate(pid, tenant_id)
        if info is None:
            return ProductReferenceResult(need_clarification=True, reason="所选产品已下架或不可见")
        return ProductReferenceResult(
            resolved=True, product_id=pid, product_name=target["name"],
            candidates=[ProductCandidate(index=ordinal, product_id=pid, product_name=target["name"])],
            reason=f"序号解析：第{_int_to_cn(ordinal) if ordinal <= 10 else str(ordinal)}款",
        )

    async def _try_resolve_deixis(
        self, text: str, context: SessionContext, tenant_id: int,
    ) -> ProductReferenceResult | None:
        """尝试从指代引用解析产品。"""
        if not _is_deixis(text):
            return None

        # 优先读取 last_focus_product_id（架构文档命名），fallback 到 last_product_id
        last_pid_str = context.last_focus_product_id or context.last_product_id
        if not last_pid_str:
            return ProductReferenceResult(need_clarification=True, reason="没有最近浏览的商品")
        pid = int(last_pid_str)
        info = await self._validate(pid, tenant_id)
        if info is None:
            return ProductReferenceResult(need_clarification=True, reason="最近浏览的商品已下架或不可见")
        name = info.get("name", "")
        return ProductReferenceResult(
            resolved=True, product_id=pid, product_name=name,
            candidates=[ProductCandidate(index=1, product_id=pid, product_name=name)],
            reason=f"指代解析：{text}",
        )

    async def _try_resolve_by_name(self, text: str, tenant_id: int) -> ProductReferenceResult:
        products = await self._search(text, tenant_id)
        if not products:
            return ProductReferenceResult(need_clarification=True, reason=f"未找到匹配「{text}」的产品")
        candidates = [
            ProductCandidate(index=i + 1, product_id=int(p["id"]), product_name=p.get("name", ""))
            for i, p in enumerate(products)
        ]
        if len(products) == 1:
            p = products[0]
            return ProductReferenceResult(
                resolved=True, product_id=int(p["id"]), product_name=p.get("name", ""),
                candidates=candidates, reason="精确/模糊名称匹配",
            )
        return ProductReferenceResult(need_clarification=True, candidates=candidates,
            reason=f"模糊名称匹配到 {len(products)} 个候选，需用户确认")
