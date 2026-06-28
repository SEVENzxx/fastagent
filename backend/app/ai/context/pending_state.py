"""Pending 状态模型与指令枚举。

PendingState 只作为 LangGraph 子图的恢复信封。
普通商品/知识上下文由 SessionContext 承载，避免双写。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.common.enums.base import LabeledEnum


class PendingStateCorruptedError(Exception):
    """Pending 数据损坏或解析失败。

    由 PendingService.get() 在 JSON 解析失败时抛出，
    主编排应捕获此异常并回复"当前操作状态暂时不可用"。
    """


class PendingAction(LabeledEnum):
    """PendingGuard 检查后返回的动作指令。"""
    HUMAN = "human"   # 转人工请求
    CANCEL = "cancel" # 退出信号："算了""不要了"
    RESUME = "resume" # 恢复 LangGraph Handler

    @property
    def label(self) -> str:
        labels = {
            PendingAction.HUMAN: "转人工",
            PendingAction.CANCEL: "退出/取消",
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
    """持久化的 LangGraph 恢复信封。

    只保存顶层路由和图恢复索引；业务进度由 LangGraph checkpoint 保存。
    """

    scenario_id: str = Field(description="场景 ID")
    step: str = Field(description="当前图节点")
    graph_thread_id: str = Field(description="LangGraph 线程 ID")
    interrupt_id: str | None = Field(default=None, description="LangGraph 中断点 ID")