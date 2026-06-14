"""应用日志配置。

业务日志统一通过 ``logging.getLogger(__name__)`` 获取 logger。
这里在应用导入阶段强制重建 root handler，避免 uvicorn、watchfiles、
PyCharm FastAPI 运行配置提前安装 handler 后，导致 ``basicConfig`` 失效。
"""

from __future__ import annotations

import logging
import sys

from app.common.logging.filter import TraceIdFilter
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
        format="%(asctime)s %(levelname)-8s [%(trace_id)s] %(name)s | %(message)s",
        stream=sys.stdout,
        force=True,
    )
    for handler in logging.getLogger().handlers:
        handler.addFilter(TraceIdFilter())
    logging.captureWarnings(True)

    logging.getLogger("app").setLevel(level)
    logging.getLogger("uvicorn").setLevel(logging.INFO)
    logging.getLogger("uvicorn.error").setLevel(logging.INFO)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("watchfiles.main").setLevel(logging.WARNING)

    # 关闭 httpx/httpcore 底层连接 DEBUG 日志
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)

    # SQL 日志：通过 settings.SQL_ECHO 控制，避免 echo=True 导致双份输出
    if settings.SQL_ECHO:
        logging.getLogger("sqlalchemy.engine").setLevel(logging.INFO)


def _resolve_log_level() -> int:
    """根据配置解析日志级别，默认开发环境输出 INFO。"""

    configured = (settings.LOG_LEVEL or "").strip().upper()
    if configured:
        return getattr(logging, configured, logging.INFO)
    return logging.DEBUG if settings.APP_DEBUG else logging.INFO
