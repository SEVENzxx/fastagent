"""AI 工具参数基础 Schema。"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class SkillArgs(BaseModel):
    """AI 技能参数基类。

    extra="allow" 让技能合约迁移可以渐进推进：新旧字段可以短期共存，
    各模块再逐步收敛到更严格的参数结构。
    """

    model_config = ConfigDict(extra="allow")
