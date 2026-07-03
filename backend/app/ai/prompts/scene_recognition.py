"""RecognitionPipeline LLM 判决 prompt。

场景列表和说明自动从 SCENARIO_DESCRIPTIONS 生成，与 DEFAULT_INTENT_EXAMPLES 保持同步。
"""

from __future__ import annotations

from app.ai.recognition.examples import SCENARIO_DESCRIPTIONS

# 兜底场景不在此映射中，但 LLM 需要能返回
_ALL_SCENARIOS: list[tuple[str, str]] = [
    *SCENARIO_DESCRIPTIONS.items(),
    ("template.fallback", "无法判断的兜底"),
]

# ── 构建 Prompt ──

_HEADER = "你是一个电商客服平台的场景识别引擎。"

_SCENE_TABLE = "\n".join(
    f"| {sid} | {label} |" for sid, label in _ALL_SCENARIOS
)

_PRINCIPLES = "\n".join([
    "1. 明确转人工/投诉/辱骂 → human.transfer（这一步通常已被强规则拦截）",
    '2. 模糊指代（"这个"、"多少钱"、"怎么样"）→ product.detail',
    '3. "好不好用"、"适合…"、"能不能…"、"用来…" → product.usage（归适用性，不归 detail）',
    "4. 有明确两个比较对象（A和B对比、哪款和哪款区别）→ product.compare",
    '5. "哪个X"、"怎么选"无比较对象 → product.filter_search（列表分析/推荐）',
    '6. "有什么"、"有没有"+"商品类别" → product.filter_search（商品筛选/推荐）',
    '7. "推荐"、"找"、"筛选" 无指代 → product.filter_search',
    '8. 分类浏览（"你们卖什么"、"有哪些分类"）→ product.catalog',
    '9. "订单"+"取消"、"不想要了" → order.cancel',
    '10. "有什么优惠/活动/政策" → knowledge.policy',
    '11. "你好"、"在吗" → template.greeting',
    '12. "买/下单/购买" + 指代词/商品 → order.create',
])

_FOOTER = '只输出一行 JSON（不要 markdown 代码块）：\n{"scenario_id": "product.detail", "confidence": 0.85, "reason": "<简短理由>"}'

RECOGNITION_SYSTEM_PROMPT = f"""{_HEADER}。根据用户消息和候选场景，判断用户当前属于哪个场景。

## 场景列表

| 场景 ID | 说明 |
|--------|------|
{_SCENE_TABLE}

## 判断原则

{_PRINCIPLES}

## 输出格式

{_FOOTER}
"""


_DIRECT_HEADER = f"{_HEADER}。用户消息没有命中任何候选场景，请根据消息内容直接判断最可能属于哪个场景。"

RECOGNITION_DIRECT_PROMPT = f"""{_DIRECT_HEADER}

## 场景列表

| 场景 ID | 说明 |
|--------|------|
{_SCENE_TABLE}

## 输出格式

{_FOOTER}
"""
