"""AssistantRuntimeResult — 主编排最终输出。

供 entry/processor.py 消费，不负责渠道落库、WebSocket、推送。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.ai.handlers.base import HandlerResult


class AssistantRuntimeResult(BaseModel):
    """主编排最终输出。"""

    reply: str                               # 回复内容
    handler_result: HandlerResult | None = None  # 原始 Handler 结果

    metadata: dict[str, Any] = Field(default_factory=dict)  # 元数据

    @classmethod
    def from_handler_result(cls, result: HandlerResult) -> AssistantRuntimeResult:
        """从 HandlerResult 构造。"""
        return cls(
            reply=result.reply,
            handler_result=result,
            metadata={
                "scenario_id": result.scenario_id,
                "pending_directive": result.pending_directive.value,
                "resource_trace": result.resource_trace.model_dump(mode="json"),
            },
        )
