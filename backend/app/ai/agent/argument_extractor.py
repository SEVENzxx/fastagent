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


# ── 正则抽取器 ──
# 15~20 位数字（Snowflake 订单号），避免误匹配手机号
ORDER_ID_PATTERN = re.compile(r"(?<!\d)(\d{15,20})(?!\d)")
# 中国大陆手机号（1 开头，3-9 号段）
PHONE_PATTERN = re.compile(r"(?<!\d)(1[3-9]\d{9})(?!\d)")
# 多种报价表达方式：报价/报/出价/给/便宜到/优惠到 + 金额，或 ¥ 符号 + 金额，或金额 + 元
PRICE_PATTERN = re.compile(
    r"(?:报价|报|出价|给|便宜到|优惠到|最低|降到|改成|价格)\s*[¥￥]?\s*(\d+(?:\.\d{1,2})?)\s*(?:元|块|rmb|RMB)?"
    r"|[¥￥]\s*(\d+(?:\.\d{1,2})?)"
    r"|(\d+(?:\.\d{1,2})?)\s*(?:元|块|rmb|RMB)"
)
# 数量 + 单位（件/个/盒/瓶/箱/包/袋/斤/克/份/套）
QUANTITY_PATTERN = re.compile(r"(\d+)\s*(?:件|个|盒|瓶|箱|包|袋|斤|克|kg|KG|份|套)")
CHINESE_QUANTITY_PATTERN = re.compile(r"(一|二|两|三|四|五|六|七|八|九|十)\s*(?:瓶|件|个|盒|箱|包|袋|斤|份|套)")
CHINESE_DIGITS = {
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}

# ── 中文语义常量 ──
# 地址提示词，用于定位客户文本中的收货地址
ADDRESS_HINTS = ("地址", "收货", "寄到", "送到", "发到")
# 下单意愿词，用于判断客户是否有下单意图
CREATE_ORDER_WORDS = ("下单", "买", "来", "要", "拍", "订")
# 订单操作词 → action 映射
ORDER_ACTION_WORDS = {
    "update_address": ("改地址", "修改地址", "换地址", "地址改", "地址换"),
    "add_note": ("备注", "加备注", "添加备注"),
}


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


def _extract_create_order_args(args: dict[str, Any], text: str) -> dict[str, Any]:
    """从客户文本中提取创建订单所需参数：商品、数量、收货电话、收货地址。"""
    extracted: dict[str, Any] = {}
    if not args.get("items"):
        product_name = _extract_product_phrase(text)
        if product_name:
            extracted["items"] = [{
                "product_name": product_name,
                "quantity": _extract_quantity(text),
                "quantity_explicit": _has_quantity(text),
            }]
    phone = args.get("receiver_phone") or _extract_phone(text)
    if phone:
        extracted["receiver_phone"] = phone
    address = args.get("shipping_address") or _extract_address(text)
    if address:
        extracted["shipping_address"] = address
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


def _extract_order_id(text: str) -> int | None:
    """正则匹配 15~20 位订单号。"""
    match = ORDER_ID_PATTERN.search(text)
    return int(match.group(1)) if match else None


def _extract_phone(text: str) -> str | None:
    """正则匹配中国大陆手机号。"""
    match = PHONE_PATTERN.search(text)
    return match.group(1) if match else None


def _extract_price(text: str) -> float | None:
    """从多种报价表达方式中抽取出金额。"""
    match = PRICE_PATTERN.search(text)
    if not match:
        return None
    value = next((group for group in match.groups() if group), None)
    return float(value) if value is not None else None


def _extract_quantity(text: str) -> int:
    """正则匹配商品数量，默认 1。"""
    match = QUANTITY_PATTERN.search(text)
    if match:
        try:
            return max(int(match.group(1)), 1)
        except ValueError:
            return 1
    chinese_match = CHINESE_QUANTITY_PATTERN.search(text)
    if chinese_match:
        return CHINESE_DIGITS.get(chinese_match.group(1), 1)
    return 1


def _has_quantity(text: str) -> bool:
    return QUANTITY_PATTERN.search(text) is not None or CHINESE_QUANTITY_PATTERN.search(text) is not None


def _extract_order_action(text: str) -> str:
    """通过关键词匹配订单操作类型：改地址 / 加备注 / 查询。"""
    for action, words in ORDER_ACTION_WORDS.items():
        if any(word in text for word in words):
            return action
    return "query"


def _extract_address(text: str) -> str | None:
    """从客户文本中提取收货地址。在地址提示词后截取尾部文本，自动去除手机号。"""
    for hint in ADDRESS_HINTS:
        if hint not in text:
            continue
        tail = text.split(hint, 1)[1].strip(" :：，,。")
        if tail:
            phone = _extract_phone(tail)
            if phone:
                tail = tail.replace(phone, "").strip(" :：，,。")
            return tail or None
    return None


def _extract_product_phrase(text: str) -> str | None:
    """从客户文本中识别商品名称片段。优先按下单词定位，否则整体清洗。

    策略：找到"下单/买/来/要/拍/订"后面的部分作为候选商品名，
    然后去掉电话、订单号、价格、数量、地址等非商品成分。
    """
    cleaned = text.strip()
    # 统一分隔符
    for token in ("，", ",", "。", "；", ";"):
        cleaned = cleaned.replace(token, " ")

    matched_order_word = False
    for word in CREATE_ORDER_WORDS:
        if word in cleaned:
            matched_order_word = True
            tail = cleaned.split(word, 1)[1].strip()
            phrase = _strip_non_product_parts(tail)
            if phrase:
                return phrase

    if matched_order_word:
        return None

    phrase = _strip_non_product_parts(cleaned)
    return phrase or None


def _strip_non_product_parts(text: str) -> str:
    """清洗非商品成分：电话号、订单号、价格、数量、地址等。"""
    text = PHONE_PATTERN.sub("", text)
    text = ORDER_ID_PATTERN.sub("", text)
    text = PRICE_PATTERN.sub("", text)
    text = re.sub(r"\d+\s*(?:件|个|盒|瓶|箱|包|袋|斤|克|kg|KG|份|套)", "", text)
    text = CHINESE_QUANTITY_PATTERN.sub("", text)
    for label in ("电话", "手机号", "手机", "联系方式", "联系"):
        if label in text:
            text = text.split(label, 1)[0]
    for hint in ADDRESS_HINTS:
        if hint in text:
            text = text.split(hint, 1)[0]
    for word in ("吧", "呀", "呢", "啊", "吗", "么", "多少钱", "有货", "库存", "发货", "今天能发", "确认订单"):
        text = text.replace(word, "")
    return text.strip(" :：，,。！？!?")


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
        # ── 简单字段抽取 ──
        "confirm_order": {
            "order_id": _extract_order_id,  # FieldExtractor
        },
        "manage_order": {
            "order_id": _extract_order_id,   # FieldExtractor
            "action": _extract_order_action,  # FieldExtractor
        },
        "update_price_strategy": {
            "quoted_price": _extract_price,         # FieldExtractor
            "product_name": _extract_product_phrase, # FieldExtractor
        },
        "remember_info": {
            "customer_text": lambda text: text,  # FieldExtractor: 直接取原文
        },
        # ── 复合抽取（字段间有依赖关系）──
        "create_order": {
            "__composite__": _extract_create_order_args,  # CompositeExtractor
        },
        "create_order_draft": {
            "__composite__": _extract_create_order_args,  # CompositeExtractor
        },
        "update_order_draft": {
            "order_id": _extract_order_id,  # FieldExtractor
            "receiver_phone": _extract_phone,
            "shipping_address": _extract_address,
            "quantity": _extract_quantity,
            "product_name": _extract_product_phrase,
        },
    })


# 模块加载时自动初始化注册表
_build_extractor_registry()
