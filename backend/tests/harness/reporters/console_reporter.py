"""控制台报告输出。"""

from __future__ import annotations

import sys

from tests.harness.schemas import CaseResult, HarnessReport


def print_report(report: HarnessReport) -> None:
    """打印可读的控制台报告。"""
    _print_summary(report)
    _print_failures(report)


def _print_summary(report: HarnessReport) -> None:
    """打印汇总信息。"""
    total = report.total
    passed = report.passed
    failed = report.failed
    duration = report.duration

    status_icon = "OK" if failed == 0 else "FAIL"
    print(f"\n{'=' * 60}")
    print(f"  Harness Report [{status_icon}]")
    print(f"  环境:      {report.env}")
    print(f"  目标:      {report.base_url}")
    print(f"  总计:      {total}")
    print(f"  通过:      {passed}")
    print(f"  失败:      {failed}")
    print(f"  耗时:      {duration:.2f}s")
    print(f"{'=' * 60}\n")


def _print_failures(report: HarnessReport) -> None:
    """打印失败用例详情。"""
    failed_cases = [c for c in report.cases if not c.passed]
    if not failed_cases:
        return

    print(f"{'─' * 60}")
    print(f"  失败用例 ({len(failed_cases)}):")
    print(f"{'─' * 60}")

    for case in failed_cases:
        print(f"\n  [FAIL] {case.name}")
        print(f"  标签:    {', '.join(case.tags) if case.tags else '-'}")
        print(f"  耗时:    {case.total_latency_ms:.0f}ms")
        print(f"  最终回复: {case.final_reply[:200]}")

        if case.errors:
            print(f"  错误:")
            for err in case.errors:
                print(f"    - {err[:200]}")

        failed_ass = [a for a in case.assertion_results if not a.passed]
        if failed_ass:
            print(f"  未通过断言:")
            for ass in failed_ass:
                print(f"    - {ass.name}: {ass.message}")
                print(f"      期望: {ass.expected}, 实际: {ass.actual}")

    print(f"{'─' * 60}\n")
