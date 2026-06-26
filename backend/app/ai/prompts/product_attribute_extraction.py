"""LLM 商品属性抽取 Prompt 构建器。

根据租户配置的属性 Schema 动态构建抽取 prompt。
输入为商品基本信息（名称、描述、规格参数），LLM 只能从租户候选 key 中选择，不能自由创造。
"""

from __future__ import annotations

import json
from typing import Any

from app.ai.types import Messages
from app.schemas.tenant import AttributeDef
from app.services.tenant_template import build_schema_for_prompt

PRODUCT_ATTR_EXTRACT_SYSTEM_PROMPT = """你是一个 SaaS 商品属性抽取器。

你的任务是：根据当前租户提供的属性配置 schema，从商品基本信息（名称、描述、规格参数）中抽取结构化属性。

严格规则：
1. 只能输出 schema 中存在的 key，禁止新增 key；不要根据常识或品牌印象推测。
   必须逐个检查 schema 中的每一个 key，为每个 key 给出抽取结果（即使无法判断也要返回 null，不能跳过或遗漏任何 key）。
2. boolean 类型：
   - 明确支持、具备、带有、可用、内置、拥有 → true
   - 明确不支持、没有、不具备、无、不带 → false
   - 未提到或无法判断 → null
3. number 类型：
   - 只抽取明确数值。
   - 如果 schema 配置了 unit，需要尽量换算为该 unit。
   - 无明确数值时返回 null。
4. enum 类型：
   - 只能从 schema 的 allowed_values 中选择。
   - 无法匹配时返回 null。
5. text 类型：
   - 只抽取商品信息中明确出现的短文本值，不要长篇总结。
   - 未提到时返回 null。
6. evidence 必须引用商品信息中的原始短句，不能编造。
7. confidence 范围为 0 到 1：
   - 明确直接表达：0.9-1.0
   - 间接但比较确定：0.7-0.89
   - 模糊或无法判断：0.0-0.5
8. 输出必须是合法 JSON 对象（不是数组），不要输出 Markdown，不要解释。
   顶层格式：{"attr": {"key1": value1, ...}, "evidence": {"key1": "原文", ...}, "confidence": {"key1": 0.9, ...}, "feature_tags": ["标签1", ...]}"""


def build_product_attr_extract_messages(
    content: str,
    product_name: str = "",
    attribute_defs: list[AttributeDef] | None = None,
) -> Messages:
    """构建属性抽取 prompt。"""
    schema_json = build_schema_for_prompt(attribute_defs or [])
    schema_text = json.dumps(schema_json, ensure_ascii=False, indent=2)

    user_prompt = (
        f"商品名称：{product_name or '未知'}\n"
        "\n"
        "【属性配置 schema】\n"
        f"{schema_text}\n"
        "\n"
        "【商品信息（截取前 4000 字符）】\n"
        f"{content[:4000] if content else '（无信息）'}\n"
        "\n"
        "请按属性配置 schema 抽取，输出 JSON 对象（不要数组），格式：\n"
        '{"attr": {"key1": value1, "key2": value2, ...}, '
        '"evidence": {"key1": "判断依据原文", ...}, '
        '"confidence": {"key1": 0.9, ...}, '
        '"feature_tags": ["标签1", "标签2"]}'
    )

    return [
        {"role": "system", "content": PRODUCT_ATTR_EXTRACT_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]
