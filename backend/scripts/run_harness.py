#!/usr/bin/env python
"""FastAgent Harness — HTTP 黑盒回归验证工具。

用法::

    # Phase 1: 框架验证（加载用例 + 检查配置 + 登录）
    uv run python scripts/run_harness.py --case smoke.yaml --email admin@example.com --password xxx

    # Phase 3: 启用 Internal Harness API
    # 1. 目标服务设置 HARNESS_API_TOKEN=xxx 且 APP_ENV=development
    # 2. 运行:
    uv run python scripts/run_harness.py --case smoke.yaml \\
        --backend simulate --harness-token xxx

    # 覆盖 base_url / tenant_id
    uv run python scripts/run_harness.py --case smoke.yaml \\
        --base-url http://localhost:8000 --tenant-id 123

    # 只运行特定 tag
    uv run python scripts/run_harness.py --case smoke.yaml --tag p0

环境变量替代（CI 友好）::

    export HARNESS_EMAIL=admin@example.com
    export HARNESS_PASSWORD=xxx
    export HARNESS_BASE_URL=http://localhost:8000
    export HARNESS_TENANT_ID=319767484162940928
    export HARNESS_BACKEND=simulate
    export HARNESS_API_TOKEN=xxx           # Internal Harness API token
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _add_scripts_dir() -> None:
    """确保 backend 目录在 sys.path 中（便于 import tests.harness）。"""
    script = Path(__file__).resolve()
    backend = script.parent.parent  # scripts/.. → backend/
    if str(backend) not in sys.path:
        sys.path.insert(0, str(backend))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="FastAgent Harness — HTTP 黑盒回归验证工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--case", "-c", required=True,
        help="用例文件路径（必填）",
    )
    parser.add_argument(
        "--env", "-e", default="local",
        help="环境名称，用于选择 YAML env 段中的 base_url（默认 local）",
    )
    parser.add_argument(
        "--base-url", default=None,
        help="覆盖 YAML 中的 base_url",
    )
    parser.add_argument(
        "--tenant-id", type=int, default=None,
        help="覆盖 YAML 中的 tenant_id",
    )
    parser.add_argument(
        "--backend", default=None,
        choices=["none", "simulate"],
        help="HTTP 对话后端（默认 none；simulate 需要 Internal Harness API）",
    )
    parser.add_argument(
        "--email", default=None,
        help="登录邮箱",
    )
    parser.add_argument(
        "--password", default=None,
        help="登录密码",
    )
    parser.add_argument(
        "--harness-token", default=None,
        help="X-Harness-Token（目标服务的 HARNESS_API_TOKEN 值）",
    )
    parser.add_argument(
        "--platform-guid", type=int, default=None,
        help="WeCom 渠道 ID（--backend simulate 时必须指定）",
    )
    parser.add_argument(
        "--tag", "-t", default=None,
        help="只运行指定 tag 的 case",
    )
    parser.add_argument(
        "--output", "-o", default=None,
        help="JSON 报告输出路径",
    )
    parser.add_argument(
        "--timeout", type=int, default=None,
        help="HTTP 请求超时秒数（默认 30）",
    )
    return parser.parse_args(argv)


def main() -> int:
    _add_scripts_dir()

    args = parse_args()

    from tests.harness.config import HarnessConfig, BACKEND_NONE
    cfg = HarnessConfig.from_env()

    # CLI 参数覆盖
    if args.env:
        cfg.env_name = args.env
    if args.base_url:
        cfg.base_url = args.base_url
    if args.tenant_id:
        cfg.tenant_id = args.tenant_id
    if args.backend:
        cfg.backend = args.backend
    if args.email:
        cfg.email = args.email
    if args.password:
        cfg.password = args.password
    if args.harness_token:
        # 设置到环境变量中，config.harness_token 属性会读取它
        import os
        os.environ[cfg.harness_token_env] = args.harness_token
    if args.platform_guid:
        cfg.platform_guid = args.platform_guid
    if args.tag:
        cfg.tag_filter = args.tag
    if args.output:
        cfg.output_path = args.output
    if args.timeout:
        cfg.timeout = args.timeout

    # 凭证检查（仅非 none 后端需要）
    if cfg.backend != "none":
        if not cfg.email or not cfg.password:
            print("[Harness] 注意: backend=simulate 但未提供登录凭证。仅使用 X-Harness-Token 认证。")

    # backend=simulate 时检查 token 和 platform_guid
    if cfg.backend == "simulate":
        if not cfg.harness_token:
            print("[Harness] 错误: backend=simulate 但未设置 Harness API Token。请设置 --harness-token 或环境变量 HARNESS_API_TOKEN")
            return 1
        if not cfg.platform_guid:
            print("[Harness] 错误: backend=simulate 但未设置 platform_guid。请设置 --platform-guid")
            return 1
        if not cfg.tenant_id:
            print("[Harness] 错误: backend=simulate 但未设置 tenant_id。请设置 --tenant-id")
            return 1

    # 加载用例
    case_path = Path(args.case)
    if not case_path.is_absolute():
        harness_cases = Path(__file__).resolve().parent.parent / "tests" / "harness" / "cases"
        candidate = harness_cases / case_path
        if candidate.exists():
            case_path = candidate
        else:
            cwd_candidate = Path.cwd() / case_path
            if cwd_candidate.exists():
                case_path = cwd_candidate

    if not case_path.exists():
        print(f"[Harness] 错误: 用例文件不存在: {case_path}")
        return 1

    cfg._case_dir = str(case_path.parent)

    # 运行
    from tests.harness.case_loader import load_case_file
    from tests.harness.runner import run as run_harness

    case_file = load_case_file(str(case_path))
    cfg.tenant_id = cfg.tenant_id or case_file.tenant_id

    report = run_harness(cfg, case_file=case_file)

    return 0 if report.failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
