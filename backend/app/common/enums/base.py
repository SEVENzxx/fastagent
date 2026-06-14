"""LabeledEnum 基类 — 所有枚举的基类，强制提供中文展示名。

用法::

    class MyEnum(LabeledEnum):
        VALUE = "value"

        @property
        def label(self) -> str:
            return "中文含义"
"""

from __future__ import annotations

from enum import Enum


class LabeledEnum(str, Enum):
    """所有业务枚举的基类。

    子类必须实现 label 属性返回中文展示名。
    枚举值本身使用短英文小写串，确保序列化兼容。
    """

    @property
    def label(self) -> str:
        """中文展示名，子类必须覆盖。"""
        msg = f"{self.__class__.__name__}.{self.value} 缺少 label 定义"
        raise NotImplementedError(msg)
