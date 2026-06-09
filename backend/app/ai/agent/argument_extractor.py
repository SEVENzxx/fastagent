"""确定性的技能参数提取模块。

本模块刻意不让 LLM 接触数据库字段选择，转而用保守的规则引擎
将客户文本转换为 schema 校验过的技能参数，避免 AI 幻觉。

架构说明：
  抽取函数通过 EXTRACTOR_REGISTRY 注册到各 SkillSpec 上，
  _extract_by_skill 是统一的注册表分发器，新增技能无需改分发逻辑。
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import ValidationError

from app.ai.agent.skill_specs import (
    EXTRACTOR_REGISTRY,
    SkillSpec,
    get_skill_spec,
)
from app.ai.extractors.order_extractor import ORDER_EXTRACTORS, extract_product_phrase


# ── 正则抽取器 ──
# 多种报价表达方式：报价/报/出价/给/便宜到/优惠到 + 金额，或 ¥ 符号 + 金额，或金额 + 元
PRICE_PATTERN = re.compile(
    r"(?:报价|报|出价|给|便宜到|优惠到|最低|降到|改成|价格)\s*[¥￥]?\s*(\d+(?:\.\d{1,2})?)\s*(?:元|块|rmb|RMB)?"
    r"|[¥￥]\s*(\d+(?:\.\d{1,2})?)"
    r"|(\d+(?:\.\d{1,2})?)\s*(?:元|块|rmb|RMB)"
)


def extract_arguments_for_plan(plan: dict[str, Any]) -> dict[str, Any]:
    """对技能调用计划执行参数抽取、schema 校验和必要参数检查。

    返回增强后的 plan 字典，额外包含 argument_errors、missing_arguments、
    risk_level 和 missing_prompt 字段，供后续节点使用。
    """

    skill_name = str(plan.get("skill_name") or "")
    spec = get_skill_spec(skill_name)
    if spec is None:
        # 无 spec 定义时不做参数增强，原样返回
        return plan

    raw_args = dict(plan.get("arguments") or {})
    text = _customer_text(raw_args)
    # 按技能类型抽取结构化参数
    extracted = _extract_by_skill(skill_name, raw_args, text)
    # 合并：原始参数优先，抽取值兜底（不为 None 才覆盖）
    merged = {**raw_args, **_drop_none(extracted)}

    # Pydantic 校验 + 缺失必填项检测
    validated_args, errors = _validate(spec, merged)
    missing = _missing_required(spec, validated_args)

    updated = dict(plan)
    updated["arguments"] = validated_args
    updated["argument_errors"] = errors
    updated["missing_arguments"] = missing
    updated["risk_level"] = spec.risk_level
    if missing:
        updated["missing_prompt"] = _missing_prompt(spec, missing)
    return updated


def _extract_by_skill(skill_name: str, args: dict[str, Any], text: str) -> dict[str, Any]:
    """注册表驱动的参数抽取分发器。

    流程：
      1. 查 EXTRACTOR_REGISTRY 获取该技能注册的抽取器
      2. 字段抽取器：先取已有参数值，缺失则从文本提取
      3. 复合抽取器：传递整个 args + text，返回一组字段值
      4. 无注册的技能直接返回空（不做强制抽取）

    新增技能只需在 EXTRACTOR_REGISTRY 加注册项，本函数无需修改。
    """
    extractors = EXTRACTOR_REGISTRY.get(skill_name, {})
    if not extractors:
        return {}

    extracted: dict[str, Any] = {}
    for key, extractor in extractors.items():
        if key == "__composite__":
            # 复合抽取器：接收完整 args + text，返回 dict
            result = extractor(args, text)
            if result:
                extracted.update(result)
        else:
            # 字段抽取器：先保留已有值，缺失则从文本抽取
            value = args.get(key)
            if value is None:
                value = extractor(text)
            if value is not None:
                extracted[key] = value

    return extracted


def _validate(spec: SkillSpec, args: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """用 Pydantic args_model 校验参数，返回 (有效参数, 错误列表)。"""
    try:
        model = spec.args_model.model_validate(args)
        return model.model_dump(exclude_none=True), []
    except ValidationError as exc:
        errors = [
            ".".join(str(part) for part in err["loc"]) + ": " + str(err["msg"])
            for err in exc.errors()
        ]
        return args, errors


def _missing_required(spec: SkillSpec, args: dict[str, Any]) -> list[str]:
    """检查哪些必填参数缺失（None / 空字符串 / 空列表都算缺失）。"""
    missing: list[str] = []
    for name in spec.required_args:
        value = args.get(name)
        if value is None or value == "" or value == []:
            missing.append(name)
    return missing


def _missing_prompt(spec: SkillSpec, missing: list[str]) -> str:
    """取第一个缺失参数对应的追问话术。"""
    return spec.missing_prompts.get(missing[0], f"请补充参数: {', '.join(missing)}")


def _customer_text(args: dict[str, Any]) -> str:
    """从参数中提取客户原始文本（优先 customer_text，其次 query）。"""
    return str(args.get("customer_text") or args.get("query") or "").strip()


def _extract_price(text: str) -> float | None:
    """从多种报价表达方式中抽取出金额。"""
    match = PRICE_PATTERN.search(text)
    if not match:
        return None
    value = next((group for group in match.groups() if group), None)
    return float(value) if value is not None else None


def _drop_none(values: dict[str, Any]) -> dict[str, Any]:
    """过滤掉值为 None 的键，避免覆盖已有参数。"""
    return {key: value for key, value in values.items() if value is not None}


# ── 注册表初始化（模块加载时执行）──

def _build_extractor_registry() -> None:
    """构建技能参数抽取器注册表。

    将各技能字段对应的抽取函数注册到 EXTRACTOR_REGISTRY，
    供 _extract_by_skill 统一调度。新增技能只需在此加一行。

    注册项类型：
      - FieldExtractor:     field_name → func(text) -> Any | None
      - "__composite__":    func(args, text) -> dict  （字段间有依赖时使用）
    """
    EXTRACTOR_REGISTRY.update({
        **ORDER_EXTRACTORS,
        # ── 简单字段抽取 ──
        "update_price_strategy": {
            "quoted_price": _extract_price,         # FieldExtractor
            "product_name": extract_product_phrase, # FieldExtractor
        },
        "remember_info": {
            "customer_text": lambda text: text,  # FieldExtractor: 直接取原文
        },
    })


# 模块加载时自动初始化注册表
_build_extractor_registry()
