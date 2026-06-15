"""Pending 状态模型与指令枚举。

PendingState 和 SessionContext 分开存储（不同 TTL）。
simple Pending 只保存短期可丢弃候选快照，graph Pending 只保存图恢复索引。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.common.enums.base import LabeledEnum


class PendingStateCorruptedError(Exception):
    """Pending 数据损坏或解析失败。

    由 PendingService.get() 在 JSON 解析失败时抛出，
    主编排应捕获此异常并回复"当前操作状态暂时不可用"。
    """


class PendingAction(LabeledEnum):
    """PendingGuard 检查后返回的动作指令。"""
    HUMAN = "human"           # 转人工请求
    CANCEL = "cancel"         # 退出信号："算了""不要了"
    NEW_INTENT = "new_intent" # 明显新意图，清理当前 Pending
    RESUME = "resume"         # 恢复 Pending Handler

    @property
    def label(self) -> str:
        labels = {
            PendingAction.HUMAN: "转人工",
            PendingAction.CANCEL: "退出/取消",
            PendingAction.NEW_INTENT: "新意图",
            PendingAction.RESUME: "恢复流程",
        }
        return labels[self]


class PendingDirective(LabeledEnum):
    """Handler 显式返回的 Pending 指令，禁止隐式规则。"""
    SET = "set"     # 设置新 Pending 或替换
    KEEP = "keep"   # 用户回答无效，继续保留当前 Pending
    CLEAR = "clear" # 流程完成/取消/转人工，清理 Pending

    @property
    def label(self) -> str:
        labels = {
            PendingDirective.SET: "设置 Pending",
            PendingDirective.KEEP: "保留 Pending",
            PendingDirective.CLEAR: "清理 Pending",
        }
        return labels[self]


class PendingState(BaseModel):
    """持久化的 Pending 状态。

    mode="simple": 保存短期可丢弃候选快照（如商品多候选），数据在 data 字段。
    mode="graph":  只保存恢复索引（graph_thread_id, interrupt_id），
                   业务进度在 LangGraph checkpoint 中。
    """

    scenario_id: str = Field(description="场景 ID")
    step: str = Field(description="当前步骤")
    expected_response_type: str = Field(description="期望的用户响应类型（ordinal/confirm/text）")
    mode: Literal["simple", "graph"] = Field(default="simple", description="Pending 模式")

    # simple pending 候选数据
    data: dict[str, Any] = Field(default_factory=dict, description="simple pending 候选数据快照")

    # graph pending 恢复索引
    graph_thread_id: str | None = Field(None, description="LangGraph 线程 ID")
    interrupt_id: str | None = Field(None, description="LangGraph 中断点 ID")

    created_at: datetime = Field(description="创建时间")
    expires_at: datetime = Field(description="过期时间")
    attempts: int = Field(0, description="已追问轮次")
    idempotency_key: str | None = Field(None, description="幂等 key（写操作时使用）")
