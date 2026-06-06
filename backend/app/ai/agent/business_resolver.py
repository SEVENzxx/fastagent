"""业务数据解析：将自然语言抽取的商品名解析为具体的业务记录。

从参数抽取器得到的商品名（如"啤酒"、"乌苏啤酒"）只是文本片段，
在执行写操作（下单、改价）之前，必须把它解析到租户商品目录中的
具体记录（product_id），否则可能出现张冠李戴。

匹配策略偏保守：宁可让用户澄清，也不自动匹配到错误商品。

架构：通过 BUSINESS_RESOLVERS 注册表驱动，新增技能只需加一行注册。
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.agent.skill_specs import BUSINESS_RESOLVERS
from app.models.product import Product

logger = logging.getLogger(__name__)


# ── 匹配阈值常量（可根据运营需求调整）──
# SKU 或名称完全匹配，且唯一 → 自动接受
MATCH_SCORE_AUTO_ACCEPT = 0.99
# 短语包含在名称中，且是唯一候选 → 自动接受
MATCH_SCORE_CONTAIN_ACCEPT = 0.88
# 高分且有显著领先优势 → 自动接受（需与第二名差距 >= LEAD_THRESHOLD）
MATCH_SCORE_CLEAR_LEAD = 0.92
MATCH_SCORE_LEAD_THRESHOLD = 0.08
# 模糊匹配最低分，低于此分不加入候选
MATCH_SCORE_FUZZY_FLOOR = 0.72


# ── 商品缓存 ──
# key: tenant_id, value: (products, cached_at_timestamp)
_product_cache: dict[int, tuple[list[Product], float]] = {}
PRODUCT_CACHE_TTL_SECONDS = 30


@dataclass(frozen=True, slots=True)
class ProductMatch:
    """商品匹配结果：记录匹配到的商品信息和置信度。"""
    product_id: int
    name: str          # 商品名称（数据库中的标准名）
    sku: str | None    # 商品 SKU
    score: float       # 匹配得分（0~1，越高越精确）
    match_type: str    # 匹配方式：sku_exact / name_exact / phrase_in_name / fuzzy_name 等

    def to_dict(self) -> dict[str, Any]:
        return {
            "product_id": self.product_id,
            "name": self.name,
            "sku": self.sku,
            "score": self.score,
            "match_type": self.match_type,
        }


# ── 业务解析入口（注册表驱动）──

async def enrich_plan_with_business_context(
    plan: dict[str, Any],
    *,
    db: AsyncSession,
    tenant_id: int,
) -> dict[str, Any]:
    """用业务数据解析技能参数中的自然语言字段。

    通过 BUSINESS_RESOLVERS 注册表分派到各技能对应的解析函数。
    未注册的技能无需业务解析，直接跳过。
    """
    skill_name = str(plan.get("skill_name") or "")
    resolver = BUSINESS_RESOLVERS.get(skill_name)
    if resolver is None:
        return plan  # 非商品类技能，无需解析
    return await resolver(plan, db=db, tenant_id=tenant_id)


# ── 技能解析器注册 ──

async def _resolve_create_order(
    plan: dict[str, Any],
    *,
    db: AsyncSession,
    tenant_id: int,
) -> dict[str, Any]:
    """解析 create_order 的参数：逐项匹配商品名 → product_id。"""
    args = dict(plan.get("arguments") or {})
    items = list(args.get("items") or [])
    errors: list[str] = []
    resolved_items: list[dict[str, Any]] = []

    for item in items:
        if not isinstance(item, dict):
            resolved_items.append(item)
            continue
        item = dict(item)
        if item.get("product_id"):
            resolved_items.append(item)
            continue
        phrase = str(item.get("product_name") or "").strip()
        match, candidates = await resolve_product(db, tenant_id, phrase)
        if match is None:
            item["product_candidates"] = [candidate.to_dict() for candidate in candidates]
            errors.append(phrase or "unknown")
            logger.info("[resolve] 商品匹配失败: phrase=%s candidates=%s", phrase, len(candidates))
        else:
            item["product_id"] = match.product_id
            item["product_name"] = match.name
            item["product_match"] = match.to_dict()
            logger.info("[resolve] 商品匹配成功: phrase=%s → product_id=%s name=%s", phrase, match.product_id, match.name)
        resolved_items.append(item)

    updated = dict(plan)
    updated["arguments"] = {**args, "items": resolved_items}
    if errors:
        _add_missing(updated, "items.product_id", _product_missing_prompt(errors))
    return updated


async def _resolve_update_price(
    plan: dict[str, Any],
    *,
    db: AsyncSession,
    tenant_id: int,
) -> dict[str, Any]:
    """解析 update_price_strategy 的参数：匹配单个商品名 → product_id。"""
    args = dict(plan.get("arguments") or {})
    if args.get("product_id"):
        return plan  # 已有精确 ID，跳过

    phrase = str(args.get("product_name") or args.get("query") or args.get("customer_text") or "").strip()
    match, candidates = await resolve_product(db, tenant_id, phrase)
    updated = dict(plan)
    if match is None:
        args["product_candidates"] = [candidate.to_dict() for candidate in candidates]
        updated["arguments"] = args
        _add_missing(updated, "product_id", _product_missing_prompt([phrase or "unknown"]))
        logger.info("[resolve] 报价商品匹配失败: phrase=%s", phrase)
    else:
        args["product_id"] = match.product_id
        args["product_name"] = match.name
        args["product_match"] = match.to_dict()
        updated["arguments"] = args
        logger.info("[resolve] 报价商品匹配成功: phrase=%s → product_id=%s", phrase, match.product_id)
    return updated


# ── 商品匹配核心逻辑 ──

async def resolve_product(
    db: AsyncSession,
    tenant_id: int,
    phrase: str,
) -> tuple[ProductMatch | None, list[ProductMatch]]:
    """商品名模糊匹配：用保守策略找最可能的商品记录。

    匹配策略（故意保守，宁可问用户也不匹配错）：
      1. SKU 完全匹配 → 直接接受（分 >= MATCH_SCORE_AUTO_ACCEPT）
      2. 名称完全匹配 → 唯一时才接受
      3. 短语包含在名称中 → 唯一高分时接受
      4. 名称包含在短语中 → 唯一高分时接受
      5. 模糊相似度 >= MATCH_SCORE_FUZZY_FLOOR → 仅作候选，不自动匹配
      6. 以上都不满足 → 无匹配

    返回值：
      (ProductMatch, candidates) — 唯一确信的匹配，前 5 个候选
      (None, candidates)       — 无法自动匹配，由用户选择
    """
    phrase = phrase.strip()
    if not phrase:
        return None, []

    products = await _load_active_products(db, tenant_id)
    candidates = rank_product_candidates(products, phrase)
    if not candidates:
        return None, []

    # ── 自动匹配判定 ──
    top = candidates[0]
    same_top = [c for c in candidates if abs(c.score - top.score) < 0.001]

    # 规则 1：SKU 或名称完全匹配，且唯一
    if top.score >= MATCH_SCORE_AUTO_ACCEPT and len(same_top) == 1:
        logger.info("[match] 自动匹配(唯一完全匹配): phrase=%s → %s score=%.4f", phrase, top.name, top.score)
        return top, candidates[:5]

    # 规则 2：短语包含在名称中，且是唯一候选
    if top.score >= MATCH_SCORE_CONTAIN_ACCEPT and len(candidates) == 1:
        logger.info("[match] 自动匹配(唯一包含): phrase=%s → %s score=%.4f", phrase, top.name, top.score)
        return top, candidates

    # 规则 3：高分且有显著差距（与第二名差 >= MATCH_SCORE_LEAD_THRESHOLD）
    if top.score >= MATCH_SCORE_CLEAR_LEAD and len(candidates) > 1 and top.score - candidates[1].score >= MATCH_SCORE_LEAD_THRESHOLD:
        logger.info("[match] 自动匹配(显著领先): phrase=%s → %s score=%.4f lead=%.4f",
                     phrase, top.name, top.score, top.score - candidates[1].score)
        return top, candidates[:5]

    # 不满足自动匹配条件 → 返回候选，让用户澄清
    logger.info("[match] 无法自动匹配: phrase=%s top=%s score=%.4f candidates=%s",
                phrase, top.name, top.score, len(candidates))
    return None, candidates[:5]


def rank_product_candidates(products: list[Product], phrase: str) -> list[ProductMatch]:
    """对商品目录逐条打分，按匹配度从高到低排序。

    打分规则（逐级降分）：
      sku_exact       = 1.00  SKU 完全一致
      name_exact      = 0.99  商品名完全一致
      phrase_in_name  = 0.90  客户输入的短语是商品名的一部分
      name_in_phrase  = 0.88  商品名是客户输入短语的一部分
      sku_in_phrase   = 0.86  客户输入中包含 SKU 的子串
      fuzzy_name      = MATCH_SCORE_FUZZY_FLOOR+ 模糊文本相似度
    """
    normalized_phrase = _normalize(phrase)
    matches: list[ProductMatch] = []

    for product in products:
        name = str(product.name or "")
        sku = str(product.sku or "") if product.sku else None
        normalized_name = _normalize(name)
        normalized_sku = _normalize(sku or "")

        score = 0.0
        match_type = "none"
        if normalized_sku and normalized_phrase == normalized_sku:
            score = 1.0
            match_type = "sku_exact"
        elif normalized_phrase == normalized_name:
            score = MATCH_SCORE_AUTO_ACCEPT
            match_type = "name_exact"
        elif normalized_phrase and normalized_phrase in normalized_name:
            score = 0.9
            match_type = "phrase_in_name"
        elif normalized_name and normalized_name in normalized_phrase:
            score = MATCH_SCORE_CONTAIN_ACCEPT
            match_type = "name_in_phrase"
        elif normalized_sku and normalized_sku in normalized_phrase:
            score = 0.86
            match_type = "sku_in_phrase"
        else:
            # 兜底：文本模糊匹配（基于字符级别的差异度）
            ratio = SequenceMatcher(None, normalized_phrase, normalized_name).ratio()
            if ratio >= MATCH_SCORE_FUZZY_FLOOR:
                score = ratio
                match_type = "fuzzy_name"

        if score > 0:
            matches.append(
                ProductMatch(
                    product_id=int(product.id),
                    name=name,
                    sku=sku,
                    score=round(score, 4),
                    match_type=match_type,
                )
            )

    # 按得分降序，同分时短名优先（更精确）
    matches.sort(key=lambda item: (item.score, len(item.name)), reverse=True)
    return matches


async def _load_active_products(db: AsyncSession, tenant_id: int) -> list[Product]:
    """加载租户所有上架商品（带 30 秒本地缓存）。

    客服场景下同个租户的多次请求间隔很短，缓存可有效减少 DB 压力。
    """
    now = time.monotonic()
    cached = _product_cache.get(tenant_id)
    if cached is not None and (now - cached[1]) < PRODUCT_CACHE_TTL_SECONDS:
        return cached[0]

    result = await db.execute(
        select(Product)
        .where(Product.tenant_id == tenant_id, Product.is_active.is_(True))
        .order_by(Product.updated_at.desc(), Product.created_at.desc())
        .limit(300)
    )
    products = list(result.scalars().all())
    _product_cache[tenant_id] = (products, now)
    return products


# ── 缺参标记辅助函数 ──

def _add_missing(plan: dict[str, Any], argument: str, prompt: str) -> None:
    """向技能计划中添加缺失参数标记，记录追问话术。"""
    missing = list(plan.get("missing_arguments") or [])
    if argument not in missing:
        missing.append(argument)
    plan["missing_arguments"] = missing
    plan["missing_prompt"] = prompt


def _product_missing_prompt(values: list[str]) -> str:
    """生成商品匹配失败的追问话术。"""
    target = values[0] if values else "该商品"
    return f"请确认具体商品：{target}。"


def _normalize(value: str) -> str:
    """文本归一化：转小写 + 去空格，用于模糊匹配比较。"""
    return "".join(value.lower().split())


# ── 注册表初始化（模块加载时执行）──

def _build_business_resolvers() -> None:
    """构建业务数据解析函数注册表。

    将需要业务解析的技能注册到 BUSINESS_RESOLVERS。
    大多数技能不涉及商品匹配，无需注册。
    """
    BUSINESS_RESOLVERS.update({
        "create_order": _resolve_create_order,
        "update_price_strategy": _resolve_update_price,
    })


_build_business_resolvers()
