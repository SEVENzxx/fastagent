"""通用 DTO 基类 — 用于类型化参数对象。

继承自 Pydantic BaseModel，提供：
- 字段中文 description（通过 Field(description=...)）
- model_dump / model_validate 序列化
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class BaseDTO(BaseModel):
    """所有 DTO 的基类。

    用于替代 ``dict[str, Any]`` 的散装传递。
    重要字段必须带中文 description。
    """

    model_config = ConfigDict(
        from_attributes=True,     # 支持从 ORM 模型读取
        populate_by_name=True,    # 支持字段名和别名双向填充
        frozen=False,             # 默认可变，子类可按需覆盖
    )


class PaginatedResult(BaseDTO):
    """分页返回结果的通用包装。"""

    items: list[BaseDTO] = Field(default_factory=list, description="数据列表")
    total: int = Field(default=0, description="总数")
    page: int = Field(default=1, description="当前页码")
    page_size: int = Field(default=20, description="每页条数")
