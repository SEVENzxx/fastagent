"""LLM 参数兜底抽取：当规则引擎抽不到参数时，让 LLM 补填。

设计约束（刻意收窄 LLM 的决策范围）：
  - LLM 只能填一个已选中技能的 JSON 参数字段
  - 不能选择数据库字段、执行 SQL、或判断写操作是否允许
  - 幻觉产物会被下游的 Pydantic schema 校验拦截
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from app.ai.agent.skill_specs import get_skill_spec
from app.ai.llm.gateway import LLMClientError, LLMUseCase, complete

logger = logging.getLogger(__name__)


# ── LLM 参数合约提示词 ──
# 每个技能告诉 LLM 它需要哪些 JSON 字段，由 system prompt 约束其只返回这些字段。
SKILL_ARGUMENT_HINTS: dict[str, str] = {
    "create_order": (
        "Return fields: items: [{product_name: string, quantity: integer}], "
        "shipping_address, receiver_name, receiver_phone, remark."
    ),
    "confirm_order": "Return fields: order_id.",
    "manage_order": "Return fields: action ('query', 'update_address', 'add_note'), order_id.",
    "update_price_strategy": "Return fields: product_name, quoted_price.",
    "remember_info": "Return fields: customer_text.",
}


async def extract_arguments_with_llm(
    skill_name: str,
    customer_text: str,
    existing_args: dict[str, Any],
    *,
    tenant_id: int | None = None,
) -> dict[str, Any]:
    """用 LLM 补填技能参数的缺失字段。

    调用时机：规则抽取器（argument_extractor）抽完仍有 missing_arguments 时触发。
    LLM 返回的 JSON 会与已有参数合并，再走一遍 Pydantic 校验。

    失败场景全部静默返回 {}：LLM 不可用、返回非 JSON、校验不通过
    都不会阻断流程，而是由上游的 missing_arguments 追问用户。
    """
    spec = get_skill_spec(skill_name)
    if spec is None or skill_name not in SKILL_ARGUMENT_HINTS:
        return {}  # 无合约定义，LLM 无法准确补填

    messages = [
        {
            "role": "system",
            "content": (
                "You extract structured JSON arguments for one pre-selected "
                "customer-service skill. Return only one JSON object. Do not "
                "invent values. Use null or omit fields when unclear. Never "
                "return SQL, database field names, or explanations."
            ),
        },
        {
            "role": "user",
            "content": (
                f"skill_name: {skill_name}\n"
                f"argument_contract: {SKILL_ARGUMENT_HINTS[skill_name]}\n"
                f"existing_args: {json.dumps(existing_args, ensure_ascii=False)}\n"
                f"customer_text: {customer_text}\n"
                "Return JSON only."
            ),
        },
    ]
    try:
        raw = await complete(
            LLMUseCase.AGENT,
            messages,
            tenant_id=tenant_id,
            temperature=0.0,
            max_tokens=256,
        )
    except LLMClientError as exc:
        logger.info("LLM 参数抽取不可用: skill=%s error=%s", skill_name, exc)
        return {}

    parsed = _parse_json_object(raw)
    if not isinstance(parsed, dict):
        return {}

    # 用 Pydantic schema 再校验一遍，拦截 LLM 幻觉（多字段、类型错误等）
    try:
        model = spec.args_model.model_validate({**existing_args, **parsed})
    except Exception as exc:
        logger.info("LLM 参数校验失败: skill=%s error=%s", skill_name, exc)
        return {}
    return model.model_dump(exclude_none=True)


def _parse_json_object(raw: str) -> dict[str, Any] | None:
    """从 LLM 回复中提取 JSON 对象。

    容忍常见的格式变异：
      - 裸 JSON：       {"a": 1}
      - 代码块包裹：     ```json {"a":1} ```
      - 混有说明文字：   "结果是 {"a":1} 这样"
    解析失败返回 None。
    """
    raw = raw.strip()
    if not raw:
        return None
    if raw.startswith("```"):
        # 去除 markdown 代码块标记
        raw = re.sub(r"^```(?:json)?", "", raw).strip()
        raw = re.sub(r"```$", "", raw).strip()
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        # 尝试在文本中找出 JSON 对象（容忍前后有说明文字）
        match = re.search(r"\{.*}", raw, re.S)
        if not match:
            return None
        try:
            value = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    return value if isinstance(value, dict) else None
