"""统一错误码与异常基类。

用法::

    raise AppError("商品不存在", code="PRODUCT_NOT_FOUND", http_status=404)
"""

from __future__ import annotations

from typing import Any


class AppError(RuntimeError):
    """应用层异常基类。

    所有可预见的业务异常应抛出此类型或其子类，
    方便 API 层统一捕获并返回结构化错误响应。
    """

    def __init__(
        self,
        message: str = "",
        *,
        code: str = "INTERNAL_ERROR",
        http_status: int = 500,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.code = code
        self.http_status = http_status
        self.details = details or {}
        super().__init__(message)

    def __str__(self) -> str:
        return f"[{self.code}] {super().__str__()}"
