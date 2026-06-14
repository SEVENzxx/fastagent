"""JSON 报告输出。"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from tests.harness.schemas import HarnessReport


def default_report_path() -> str:
    """生成默认报告路径（项目根目录 reports/harness/）。"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = Path(__file__).resolve().parent.parent.parent.parent / "reports" / "harness"
    base.mkdir(parents=True, exist_ok=True)
    return str(base / f"harness_report_{timestamp}.json")


def _case_to_dict(case: Any) -> dict:
    """将 CaseResult 转为 JSON 兼容字典。"""
    return {
        "name": case.name,
        "tags": case.tags,
        "passed": case.passed,
        "messages": case.messages,
        "turns": [
            {
                "input": t.input,
                "status_code": t.status_code,
                "reply": t.reply,
                "latency_ms": round(t.latency_ms, 1),
                "error": t.error,
            }
            for t in case.turns
        ],
        "final_reply": case.final_reply,
        "latency_ms": round(case.total_latency_ms, 1),
        "errors": case.errors,
        "assertion_results": [
            {
                "name": a.name,
                "expected": _serialize(a.expected),
                "actual": _serialize(a.actual),
                "passed": a.passed,
                "message": a.message,
            }
            for a in case.assertion_results
        ],
    }


def _serialize(val: Any) -> Any:
    """安全序列化（处理非 JSON 原生类型）。"""
    if isinstance(val, (str, int, float, bool, type(None))):
        return val
    return str(val)


def write_json_report(report: HarnessReport, path: str | None = None) -> str:
    """将报告写入 JSON 文件。

    Args:
        report: 运行报告。
        path:   输出路径；None 则自动生成。

    Returns:
        实际写入的文件路径。
    """
    output_path = path or default_report_path()

    payload = {
        "summary": {
            "total": report.total,
            "passed": report.passed,
            "failed": report.failed,
            "duration": round(report.duration, 2),
            "env": report.env,
            "base_url": report.base_url,
            "started_at": report.started_at,
        },
        "cases": [_case_to_dict(c) for c in report.cases],
    }

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    return output_path
