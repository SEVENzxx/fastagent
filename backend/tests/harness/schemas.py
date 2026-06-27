"""Harness 数据类型定义。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class AssertionDef:
    """用例/轮次断言定义，对应 YAML expected 字段。"""
    status_code: int | None = None
    reply_not_empty: bool | None = None
    reply_contains: list[str] | None = None
    reply_not_contains: list[str] | None = None
    reply_contains_any: list[str] | None = None
    reply_regex: str | None = None
    reply_not_regex: str | None = None
    max_latency_ms: int | None = None

    # ── ResourceTrace 断言 ────────────────────────────────────────────
    max_llm_calls: int | None = None           # LLM 调用次数上限
    max_vector_calls: int | None = None         # 向量检索次数上限
    allowed_skill_calls: list[str] | None = None   # 允许调用的 Skill 列表
    disallowed_skill_calls: list[str] | None = None  # 禁止调用的 Skill 列表


@dataclass
class TurnResult:
    """单轮对话结果。"""
    input: str = ""
    status_code: int = 0
    reply: str = ""
    latency_ms: float = 0.0
    error: str | None = None
    resource_trace: dict | None = None  # 资源调用轨迹


@dataclass
class AssertionResult:
    """单条断言执行结果。"""
    name: str = ""
    expected: Any = None
    actual: Any = None
    passed: bool = False
    message: str = ""


@dataclass
class CaseResult:
    """单个用例完整结果。"""
    name: str = ""
    tags: list[str] = field(default_factory=list)
    passed: bool = False
    messages: list[str] = field(default_factory=list)
    turns: list[TurnResult] = field(default_factory=list)
    final_reply: str = ""
    total_latency_ms: float = 0.0
    errors: list[str] = field(default_factory=list)
    assertion_results: list[AssertionResult] = field(default_factory=list)


@dataclass
class HarnessReport:
    """完整运行报告。"""
    total: int = 0
    passed: int = 0
    failed: int = 0
    duration: float = 0.0
    cases: list[CaseResult] = field(default_factory=list)
    env: str = ""
    base_url: str = ""
    started_at: str = ""
