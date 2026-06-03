"""AI 路由处理器注册表。

设计目标：
- 所有 route handler 遵循同一份协议。
- handler 模块通过 ``@register_handler("ROUTE")`` 主动注册自己。
- MessageRouter 只依赖注册表，不需要用 if-else 了解每个具体 handler。
- 每次 get_handler() 创建新实例，避免并发共享状态。
"""

from __future__ import annotations

import importlib
import logging
import pkgutil
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Protocol

from app.ai.classifier.types import RoutedIntent

if TYPE_CHECKING:
    from app.ai.agent.types import AgentContext

logger = logging.getLogger(__name__)


class RouteHandler(Protocol):
    """统一路由处理器协议。

    所有 handler 属性均为类属性（路由元数据），tool_results 为实例属性
    （每次请求独立，Agent 执行后填充）。
    """

    route: str
    reply_sender_type: str | None
    clear_pending_state: bool
    transfer_to_human: bool
    send_ai_greeting: bool
    show_typing: bool
    requires_agent_context: bool
    tool_results: list[dict]

    async def handle(
        self,
        routed: RoutedIntent,
        *,
        agent_context: AgentContext | None = None,
    ) -> str:
        """返回完整回复文本。"""

    async def stream(
        self,
        routed: RoutedIntent,
        *,
        agent_context: AgentContext | None = None,
    ) -> AsyncIterator[str]:
        """返回流式回复片段。"""


_HANDLERS: dict[str, type] = {}
_DISCOVERED = False


def register_handler(route: str):
    """注册 route handler 类。

    用法：

    ``@register_handler("GENERAL_REPLY")``
    ``class GeneralReplyHandler: ...``

    存储类（非实例），每次 get_handler() 按请求创建新实例。
    """

    normalized_route = route.strip().upper()

    def decorator(cls):
        if normalized_route in _HANDLERS:
            logger.warning("AI route handler 被覆盖：route=%s class=%s", normalized_route, cls.__name__)
        _HANDLERS[normalized_route] = cls
        logger.info("AI route handler 已注册：route=%s class=%s", normalized_route, cls.__name__)
        return cls

    return decorator


def get_handler(route: str) -> RouteHandler:
    """按 route 获取处理器实例（每次调用创建新实例，并发安全）。"""

    autodiscover_handlers()
    normalized_route = route.strip().upper()
    cls = _HANDLERS.get(normalized_route)
    if cls is None:
        raise KeyError(f"未注册 AI route handler: {normalized_route}")
    return cls()


def registered_routes() -> tuple[str, ...]:
    """返回已注册 route，主要用于测试和启动诊断。"""

    autodiscover_handlers()
    return tuple(sorted(_HANDLERS))


def autodiscover_handlers() -> None:
    """自动导入 handlers 包下的模块，触发装饰器注册。

    Python 的装饰器注册依赖模块被 import。这里集中做一次包扫描，避免
    MessageRouter 手动 import 每个 handler，也避免 handler 清单散落在业务逻辑里。
    """

    global _DISCOVERED
    if _DISCOVERED:
        return

    import app.ai.handlers as handlers_package

    package_prefix = handlers_package.__name__ + "."
    for module in pkgutil.iter_modules(handlers_package.__path__, package_prefix):
        if module.name.endswith(".registry"):
            continue
        importlib.import_module(module.name)

    _DISCOVERED = True
    logger.info("AI route handler 自动发现完成：routes=%s", sorted(_HANDLERS))
