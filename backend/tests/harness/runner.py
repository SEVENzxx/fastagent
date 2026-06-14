"""Harness 运行编排器。

流程：
  1. 加载 YAML 用例文件 + 按 tag 过滤
  2. 校验 HTTP 后端配置
  3. 登录获取 JWT
  4. 逐 case 逐轮发送消息并记录结果
  5. 执行断言
  6. 输出控制台报告 + JSON 报告
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

from tests.harness.adapters.http_adapter import HttpAdapter
from tests.harness.assertions.basic_assertions import check_assertions
from tests.harness.case_loader import CaseFile, load_case_file
from tests.harness.config import BACKEND_NONE, HarnessConfig
from tests.harness.reporters.console_reporter import print_report
from tests.harness.reporters.json_reporter import write_json_report
from tests.harness.schemas import CaseResult, HarnessReport


def _build_error_report(
    report: HarnessReport,
    all_cases: list,
    error_msg: str,
    started: float,
) -> HarnessReport:
    """快速构建全失败报告（适配器初始化或登录失败时用）。"""
    for tc in all_cases:
        cr = CaseResult(name=tc.name, tags=tc.tags)
        cr.passed = False
        cr.errors.append(error_msg)
        report.cases.append(cr)
        report.failed += 1
    report.total = len(all_cases)
    report.duration = time.perf_counter() - started

    print_report(report)
    write_json_report(report)
    return report


def run(config: HarnessConfig, case_file: CaseFile | None = None) -> HarnessReport:
    """执行 Harness 运行。

    Args:
        config:    运行时配置（含 base_url、凭证、后端类型等）。
        case_file: 预加载的用例文件。None 时从 config._case_dir 扫描。

    Returns:
        完整运行报告。
    """
    report = HarnessReport(
        env=config.env_name,
        base_url=config.base_url,
        started_at=datetime.now(timezone.utc).isoformat(),
    )
    started = time.perf_counter()

    # ── 1: 加载用例 ─────────────────────────────────────────────────────
    if case_file is None:
        from pathlib import Path
        case_dir = Path(__file__).resolve().parent / "cases"
        yaml_files = sorted(case_dir.glob("*.yaml"))
        case_files = [load_case_file(str(yf)) for yf in yaml_files]
    else:
        case_files = [case_file]

    all_cases = []
    for cf in case_files:
        if cf.tenant_id:
            config.tenant_id = cf.tenant_id
        if cf.conversation_prefix:
            config.conversation_prefix = cf.conversation_prefix
        if cf.env and config.env_name in cf.env:
            env_base = cf.env[config.env_name].get("base_url")
            if env_base:
                config.base_url = env_base
                report.base_url = env_base

        for tc in cf.cases:
            if config.tag_filter and config.tag_filter not in tc.tags:
                continue
            all_cases.append(tc)

    if not all_cases:
        print("[Harness] 没有匹配的用例，退出。")
        return report

    print(f"[Harness] 加载 {len(all_cases)} 个用例 ({len(case_files)} 个文件)")

    # ── 2: 初始化 adapter ───────────────────────────────────────────────
    adapter: HttpAdapter | None = None
    try:
        adapter = HttpAdapter(config)
    except (ValueError, NotImplementedError) as exc:
        print(f"[Harness] Adapter 初始化失败: {exc}")
        report = _build_error_report(report, all_cases, str(exc), started)
        return report

    # ── 3: 登录（仅当提供了凭证时） ──────────────────────────────────────
    if config.email and config.password:
        try:
            adapter.login(config.email, config.password)
            print(f"[Harness] 登录成功: {config.email}")
        except RuntimeError as exc:
            print(f"[Harness] 登录失败: {exc}")
            report = _build_error_report(report, all_cases, f"登录失败: {exc}", started)
            adapter.close()
            return report
    else:
        print("[Harness] 跳过登录：未提供凭证")

    # ── 4: 执行用例 ─────────────────────────────────────────────────────
    run_id = adapter.generate_run_id()
    case_idx = 0
    for tc in all_cases:
        case_idx += 1
        print(f"[{case_idx}/{len(all_cases)}] {tc.name} ... ", end="", flush=True)

        case_result = CaseResult(name=tc.name, tags=tc.tags)
        external_user_id = adapter.generate_external_user_id(tc.name)

        for msg_idx, mc in enumerate(tc.messages):
            try:
                turn = adapter.send_message(
                    external_user_id, mc.content, run_id=run_id,
                )
            except NotImplementedError as exc:
                # 后端未实现 → 标记所有剩余 case 为 blocked
                turn = None
                case_result.errors.append(f"turn[{msg_idx}]: HTTP 后端未配置 — {exc}")
                # 将错误信息填入假 turn 以便断言
                from tests.harness.schemas import TurnResult
                turn = TurnResult(
                    input=mc.content,
                    status_code=0,
                    error=f"HTTP 后端未配置（backend={config.backend}）",
                )
                case_result.turns.append(turn)
                break  # 不再继续发消息

            case_result.turns.append(turn)

            if mc.expected:
                case_result.assertion_results.extend(
                    check_assertions(mc.expected, turn)
                )
            if turn.error:
                case_result.errors.append(f"turn[{msg_idx}]: {turn.error}")

        # Case 级别断言（作用于最后一轮）
        final_turn = case_result.turns[-1] if case_result.turns else None
        if tc.expected and final_turn:
            case_result.assertion_results.extend(
                check_assertions(tc.expected, final_turn)
            )

        case_result.messages = [mc.content for mc in tc.messages]
        case_result.final_reply = final_turn.reply if final_turn else ""
        case_result.total_latency_ms = sum(t.latency_ms for t in case_result.turns)

        failed_assertions = [a for a in case_result.assertion_results if not a.passed]
        has_turn_errors = any(t.error for t in case_result.turns)
        case_result.passed = (not failed_assertions) and (not has_turn_errors)

        if case_result.passed:
            print(f"PASS ({case_result.total_latency_ms:.0f}ms)")
        else:
            print(f"FAIL ({case_result.total_latency_ms:.0f}ms)")

        if case_result.passed:
            report.passed += 1
        else:
            report.failed += 1
        report.cases.append(case_result)

    # ── 5: 报告 ─────────────────────────────────────────────────────────
    report.total = len(all_cases)
    report.duration = time.perf_counter() - started

    print_report(report)

    json_path = config.output_path or None
    saved = write_json_report(report, json_path)
    print(f"[Harness] JSON 报告: {saved}")

    if adapter is not None:
        adapter.close()
    return report
