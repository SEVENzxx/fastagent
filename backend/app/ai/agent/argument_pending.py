"""跨轮对话的参数持久化：把上一轮已抽取到的部分参数存到 Redis，下一轮再合并。

多轮场景示例：
  用户第一轮：  "帮我下单两瓶啤酒"        → 抽到 {items: [{name: 啤酒, qty: 2}]}
  系统追问：    "请确认具体商品：啤酒。"
  用户第二轮：  "就下单乌苏啤酒吧"        → 加载上一轮的 {qty: 2} 合并 → {name: 乌苏啤酒, qty: 2}
"""

from __future__ import annotations

import json
from typing import Any

from app.ai.agent.skill_specs import MERGE_REGISTRY
from app.ai.classifier.types import PendingIntentState

# 持久化参数在 PendingIntentState.filled_entities 中的 key
PENDING_ARGUMENTS_KEY = "arguments"


def merge_pending_arguments(
    arguments: dict[str, Any],
    pending_state: PendingIntentState | None,
    *,
    skill_name: str,
) -> dict[str, Any]:
    """合并上一轮累积的部分参数到当前轮。

    流程：
      1. 无 pending state 或技能不匹配 → 直接返回当前参数
      2. 取出上一轮存的部分参数（JSON 反序列化）
      3. 查 MERGE_REGISTRY 获取该技能的合并函数，执行自定义合并
      4. 未注册的技能使用默认合并：shallow merge（本轮参数优先覆盖）

    返回合并后的参数字典，由上游继续做 Pydantic 校验和缺参检测。
    新增技能只需在 MERGE_REGISTRY 加注册项，本函数无需修改。
    """
    if pending_state is None or pending_state.skill != skill_name:
        return arguments
    pending_args = _pending_arguments(pending_state)
    if not pending_args:
        return arguments
    merge_func = MERGE_REGISTRY.get(skill_name)
    if merge_func is not None:
        return merge_func(arguments, pending_args)
    # 默认合并：上一轮值做兜底，本轮值优先覆盖
    return {**pending_args, **arguments}


def build_pending_state_from_tool_result(
    tool_result: dict[str, Any],
    *,
    intent: str | None,
    skill_name: str,
) -> PendingIntentState | None:
    """从缺参的工具执行结果构建持久化的 pending state。

    调用时机：技能因 missing_arguments 未执行时，将已抽到的部分参数
    （pending_arguments）序列化后存入 Redis，供下一轮对话加载合并。
    如果参数齐全则返回 None（不存 state）。
    """
    missing = [str(item) for item in tool_result.get("missing_arguments") or []]
    if not missing:
        return None  # 无缺失参数，无需持久化
    pending_arguments = tool_result.get("pending_arguments")
    if not isinstance(pending_arguments, dict):
        pending_arguments = {}
    return PendingIntentState(
        intent=intent or skill_name,
        skill=skill_name,
        required_entities=missing,
        filled_entities={
            PENDING_ARGUMENTS_KEY: json.dumps(pending_arguments, ensure_ascii=False, separators=(",", ":")),
        },
        last_prompt=str(tool_result.get("error") or "") or None,
    )


def _pending_arguments(pending_state: PendingIntentState) -> dict[str, Any]:
    """从 pending state 的反序列化参数中取出 dict。"""
    raw = pending_state.filled_entities.get(PENDING_ARGUMENTS_KEY)
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _merge_create_order(arguments: dict[str, Any], pending_args: dict[str, Any]) -> dict[str, Any]:
    """特殊的 create_order items 合并逻辑。

    create_order 的 items 是列表，不能简单 shallow merge。
    特殊处理 items[0] 的合并：
      - product_name 用当前的（用户第二轮的精确表达）
      - quantity 优先用上一轮的（用户没说新数量则沿用）
      - quantity_explicit 标记帮助判断本轮是否明确说了数量
    """
    merged = {**pending_args, **arguments}
    current_items = list(arguments.get("items") or [])
    pending_items = list(pending_args.get("items") or [])
    if not current_items or not pending_items:
        return merged  # 单边有 items，直接各自兜底

    current = dict(current_items[0]) if isinstance(current_items[0], dict) else {}
    pending = dict(pending_items[0]) if isinstance(pending_items[0], dict) else {}
    if not current:
        return merged

    # 合并第一个商品项：当前值优先覆盖，但数量保留上一轮的
    item = {**pending, **current}
    if not current.get("quantity_explicit") and pending.get("quantity"):
        item["quantity"] = pending["quantity"]
    merged["items"] = [item, *current_items[1:]]
    return merged


# ── 注册表初始化（模块加载时执行）──

def _build_merge_registry() -> None:
    """构建跨轮参数合并函数注册表。

    将需要定制合并逻辑的技能注册到 MERGE_REGISTRY。
    大多数技能用默认 shallow merge 就够，无需注册。
    """
    MERGE_REGISTRY.update({
        "create_order": _merge_create_order,  # items 列表合并需要特殊逻辑
    })


_build_merge_registry()
