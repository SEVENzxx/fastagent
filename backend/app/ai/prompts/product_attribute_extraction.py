"""LLM product attribute extraction prompt."""

from __future__ import annotations

from app.ai.types import Messages

PRODUCT_ATTR_EXTRACT_SYSTEM_PROMPT = """你是商品属性专用抽取器，严格遵守以下规则，输出固定 JSON 格式：

输出结构（三部分）：
{"attr": {}, "feature_tags": [], "scenario_tags": []}

核心原则：只抽取用户输入中明确提到的属性，没有明确提及的一律视为未知，不要猜测或联想。

1. attr：仅抽取给定模板内的字段，不新增不删减。
   取值规范：
   - 文本类：用户明确提到该属性时如实填写值，未提及填空字符串 ""
   - 数值类(price/battery_hours/total_power_w 等)：用户明确提到数字时只提取纯数字（去除¥/单位/文字后缀），未提及填 null
   - 布尔类：用户明确要求该功能 → true；用户明确说不要该功能 → false；用户未提及该功能 → null
     注意：false 和 null 含义不同。false = "用户明确排除"，null = "用户没提到，不确定"
     例子：用户说"防水耳机" → is_waterproof: true, 其他布尔字段全部 null
     例子：用户说"不要降噪" → is_noise_cancelling: false, 其他布尔字段全部 null
   续航区分：耳机/音箱用 battery_hours，穿戴设备用 battery_days，另一项填 null

2. feature_tags：仅从用户输入中提取 1-5 个明确提到的功能卖点，不联想补充。
   例子：用户说"防水运动耳机" → ["防水", "运动"]

3. scenario_tags：仅从用户输入中提取 1-3 个明确提到的使用场景，不联想补充。
   例子：用户说"跑步用" → ["跑步"]

不添加注释、解释、markdown，只输出标准 JSON。"""


def build_product_attr_extract_messages(
    content: str,
    product_name: str = "",
    template_fields: list[str] | None = None,
) -> Messages:
    """Build product attribute extraction messages constrained by tenant template."""
    fields = template_fields or []
    user_prompt = f"""允许抽取字段列表：
{fields}

商品名称：{product_name or "未知"}

待解析商品内容（截取前 4000 字符）：
{content[:4000]}"""
    return [
        {"role": "system", "content": PRODUCT_ATTR_EXTRACT_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]
