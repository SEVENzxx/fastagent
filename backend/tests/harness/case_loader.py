"""YAML 用例文件加载。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from tests.harness.schemas import AssertionDef


@dataclass
class MessageCase:
    """单条消息定义。"""
    content: str
    expected: AssertionDef | None = None
    description: str | None = None


@dataclass
class TestCase:
    __test__ = False  # pytest: 不是测试类
    """单个测试用例。"""
    name: str
    tags: list[str]
    messages: list[MessageCase]
    expected: AssertionDef | None = None  # case 级断言，作用于最后一个 turn
    description: str | None = None
    risk_level: str | None = None
    business_constraints: list[str] | None = None


@dataclass
class CaseFile:
    """完整 YAML 用例文件。"""
    env: dict[str, dict[str, str]]
    tenant_id: int
    conversation_prefix: str
    cases: list[TestCase]


def _parse_expected(data: dict | None) -> AssertionDef | None:
    """将 YAML dict 转为 AssertionDef，忽略 None 值。"""
    if not data:
        return None
    cleaned = {k: v for k, v in data.items() if v is not None}
    return AssertionDef(**cleaned) if cleaned else None


def load_case_file(path: str) -> CaseFile:
    """加载并解析 YAML 用例文件。

    YAML 格式：:

        env:
          local:
            base_url: "http://localhost:8000"
        tenant_id: 123
        conversation_prefix: "harness"

        cases:
          - name: "商品搜索"
            tags: ["product", "p0"]
            messages:
              - text: "你们有什么产品"
            expected:
              status_code: 200
              reply_not_empty: true

    每条消息可以是纯字符串或 ``{text: str, expected?: {...}}`` 对象。
    case 级别 ``expected`` 作用于该 case 的最后一轮消息。
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"用例文件不存在: {path}")

    with open(path, "r", encoding="utf-8") as f:
        raw: dict[str, Any] = yaml.safe_load(f)

    env = raw.get("env", {})
    tenant_id = int(raw.get("tenant_id", 0))
    conversation_prefix = raw.get("conversation_prefix", "harness")
    raw_cases: list[dict] = raw.get("cases", [])

    cases: list[TestCase] = []
    for i, rc in enumerate(raw_cases):
        name = rc.get("name", f"case_{i}")
        tags: list[str] = rc.get("tags", [])
        description = rc.get("description") or None
        risk_level = rc.get("risk_level") or None
        business_constraints = rc.get("business_constraints") or None

        # case 级断言
        case_expected = _parse_expected(rc.get("expected"))

        # 解析消息列表
        raw_msgs: list = rc.get("messages", [])
        messages: list[MessageCase] = []
        for rm in raw_msgs:
            if isinstance(rm, str):
                messages.append(MessageCase(content=rm))
            elif isinstance(rm, dict):
                content = rm.get("content", rm.get("text", ""))
                msg_expected = _parse_expected(rm.get("expected"))
                msg_desc = rm.get("description") or None
                messages.append(MessageCase(content=content, expected=msg_expected, description=msg_desc))
            else:
                raise TypeError(f"未知的消息格式: {type(rm)}")

        case = TestCase(
            name=name,
            tags=tags,
            messages=messages,
            expected=case_expected,
            description=description,
            risk_level=risk_level,
            business_constraints=business_constraints,
        )
        cases.append(case)

    return CaseFile(
        env=env,
        tenant_id=tenant_id,
        conversation_prefix=conversation_prefix,
        cases=cases,
    )
