"""Bootstrap trace_id 生命周期测试。"""

from unittest.mock import patch

import runpy
import pytest

from app.common.trace.context import get_trace_id, reset_trace_id


class TestBootstrapMainBlock:
    """覆盖 app.bootstrap 的 __main__ 分支的 trace_id 生命周期。

    注：runpy.run_module 创建独立执行命名空间，模块级名称（包括 bootstrap）
    在该命名空间内定义，无法通过 patch("app.bootstrap.bootstrap") 拦截。
    因此 mock asyncio.run（__main__ 块通过它调用 bootstrap()），等价于验证
    __main__ 块的 ensure/reset 模式正确性。
    """

    def setup_method(self) -> None:
        reset_trace_id()

    def test_main_sets_and_resets_trace_id(self) -> None:
        """__main__ 执行期间 trace_id 非空，结束后重置。"""
        def mock_run(main_coro, **kwargs):
            assert get_trace_id() != "", "bootstrap 执行期间 trace_id 不应为空"
            main_coro.close()  # 避免 "coroutine never awaited" 告警

        with (
            patch("asyncio.run", mock_run),
            patch("app.logging_config.setup_logging"),
        ):
            runpy.run_module("app.bootstrap", run_name="__main__")

        assert get_trace_id() == "", "__main__ 结束后 trace_id 应被重置"

    def test_main_resets_on_exception(self) -> None:
        """bootstrap 抛异常时 finally 仍执行 reset。"""
        def mock_run_fail(main_coro, **kwargs):
            assert get_trace_id() != ""
            main_coro.close()
            raise RuntimeError("bootstrap 失败")

        with (
            patch("asyncio.run", mock_run_fail),
            patch("app.logging_config.setup_logging"),
        ):
            with pytest.raises(RuntimeError):
                runpy.run_module("app.bootstrap", run_name="__main__")

        assert get_trace_id() == "", "异常路径下 trace_id 也应被重置"
