"""基础断言实现。"""

from __future__ import annotations

import re

from tests.harness.schemas import AssertionDef, AssertionResult, TurnResult


def check_assertions(
    expected: AssertionDef | None,
    turn: TurnResult,
) -> list[AssertionResult]:
    """对单轮对话结果执行所有定义的断言。

    Args:
        expected: 断言定义（可为 None，此时返回空列表）。
        turn:     单轮对话结果。

    Returns:
        断言结果列表（每个断言一条记录，含 expected/actual/passed/message）。
    """
    if expected is None:
        return []

    results: list[AssertionResult] = []

    # ── status_code ─────────────────────────────────────────────────────
    if expected.status_code is not None:
        passed = turn.status_code == expected.status_code
        results.append(AssertionResult(
            name="status_code",
            expected=expected.status_code,
            actual=turn.status_code,
            passed=passed,
            message="" if passed else f"期望 {expected.status_code}，实际 {turn.status_code}",
        ))

    # ── reply_not_empty ─────────────────────────────────────────────────
    if expected.reply_not_empty is True:
        passed = bool(turn.reply.strip())
        results.append(AssertionResult(
            name="reply_not_empty",
            expected=True,
            actual=bool(turn.reply.strip()),
            passed=passed,
            message="" if passed else "回复为空",
        ))

    # ── reply_contains ──────────────────────────────────────────────────
    for keyword in (expected.reply_contains or []):
        passed = keyword in turn.reply
        results.append(AssertionResult(
            name="reply_contains",
            expected=keyword,
            actual=turn.reply[:200],
            passed=passed,
            message="" if passed else f"回复中未包含预期文本: {keyword}",
        ))

    # ── reply_not_contains ──────────────────────────────────────────────
    for keyword in (expected.reply_not_contains or []):
        passed = keyword not in turn.reply
        results.append(AssertionResult(
            name="reply_not_contains",
            expected=keyword,
            actual=turn.reply[:200],
            passed=passed,
            message="" if passed else f"回复中包含了不应出现的文本: {keyword}",
        ))

    # ── reply_contains_any ──────────────────────────────────────────────
    if expected.reply_contains_any:
        passed = any(kw in turn.reply for kw in expected.reply_contains_any)
        results.append(AssertionResult(
            name="reply_contains_any",
            expected=expected.reply_contains_any,
            actual=turn.reply[:200],
            passed=passed,
            message="" if passed else f"回复中未包含任一关键词: {expected.reply_contains_any}",
        ))

    # ── reply_regex ─────────────────────────────────────────────────────
    if expected.reply_regex is not None:
        try:
            matched = bool(re.search(expected.reply_regex, turn.reply))
        except re.error as exc:
            matched = False
            results.append(AssertionResult(
                name="reply_regex",
                expected=expected.reply_regex,
                actual=turn.reply[:200],
                passed=False,
                message=f"正则表达式错误: {exc}",
            ))
        else:
            results.append(AssertionResult(
                name="reply_regex",
                expected=expected.reply_regex,
                actual=turn.reply[:200],
                passed=matched,
                message="" if matched else f"回复未匹配正则: {expected.reply_regex}",
            ))

    # ── reply_not_regex ─────────────────────────────────────────────────
    if expected.reply_not_regex is not None:
        try:
            matched = bool(re.search(expected.reply_not_regex, turn.reply))
        except re.error as exc:
            matched = True  # 正则无效视为不通过
            results.append(AssertionResult(
                name="reply_not_regex",
                expected=expected.reply_not_regex,
                actual=turn.reply[:200],
                passed=False,
                message=f"正则表达式错误: {exc}",
            ))
        else:
            passed = not matched
            results.append(AssertionResult(
                name="reply_not_regex",
                expected=expected.reply_not_regex,
                actual=turn.reply[:200],
                passed=passed,
                message="" if passed else f"回复匹配了不应匹配的正则: {expected.reply_not_regex}",
            ))

    # ── max_latency_ms ──────────────────────────────────────────────────
    if expected.max_latency_ms is not None:
        passed = turn.latency_ms <= expected.max_latency_ms
        results.append(AssertionResult(
            name="max_latency_ms",
            expected=expected.max_latency_ms,
            actual=round(turn.latency_ms, 1),
            passed=passed,
            message="" if passed else (
                f"响应超时: {round(turn.latency_ms, 1)}ms "
                f"(限制 {expected.max_latency_ms}ms)"
            ),
        ))

    return results
