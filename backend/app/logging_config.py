"""应用日志配置。

业务日志统一通过 ``logging.getLogger(__name__)`` 获取 logger。
这里在应用导入阶段强制重建 root handler，避免 uvicorn、watchfiles、
PyCharm FastAPI 运行配置提前安装 handler 后，导致 ``basicConfig`` 失效。
"""

from __future__ import annotations

import logging
import sys

from app.config import settings


def setup_logging() -> None:
    """初始化应用日志。

    关键点：
    - ``force=True`` 会替换已有 root handlers，解决 uvicorn/PyCharm 先配置日志后
      ``logging.basicConfig`` 不生效的问题。
    - 业务模块统一走 ``app`` logger 层级，默认继承 root handler。
    - uvicorn 自身 logger 保持可见，但 access log 仍由 main.py 中间件接管。
    """

    level = _resolve_log_level()
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-8s %(name)s | %(message)s",
        stream=sys.stdout,
        force=True,
    )
    logging.captureWarnings(True)

    logging.getLogger("app").setLevel(level)
    logging.getLogger("uvicorn").setLevel(logging.INFO)
    logging.getLogger("uvicorn.error").setLevel(logging.INFO)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


def _resolve_log_level() -> int:
    """根据配置解析日志级别，默认开发环境输出 INFO。"""

    configured = (settings.LOG_LEVEL or "").strip().upper()
    if configured:
        return getattr(logging, configured, logging.INFO)
    return logging.DEBUG if settings.APP_DEBUG else logging.INFO
