"""Handler 基类与核心类型。

Handler 是场景链路唯一负责人。所有 Handler 继承 BaseHandler。
相同 scenario_id 只能对应一个 Handler 方法。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, Field

from app.ai.context.pending_state import PendingDirective, PendingState
from app.ai.recognition.types import ScenarioDecision


class ToolResult:
    """确定性 Skill 调用的返回结果。

    Attributes:
        ok: 调用是否成功
        skill_name: 被调用的 Skill 名称
        result: 成功时的返回数据
        error: 失败时的错误描述
    """

    def __init__(
        self,
        ok: bool,
        skill_name: str,
        result: object = None,
        error: str | None = None,
    ) -> None:
        self.ok = ok
        self.skill_name = skill_name
        self.result = result
        self.error = error


class ResourceTrace(BaseModel):
    """资源调用轨迹，由 Gateway 自动填充，Handler 不手动篡改。"""

    scenario_id: str = Field(default="", description="场景 ID")
    skill_calls: list[str] = Field(default_factory=list, description="调用的 Skill 名称列表")
    sql_calls: int = Field(0, description="SQL 查询次数")
    redis_reads: int = Field(0, description="Redis 读取次数")
    redis_writes: int = Field(0, description="Redis 写入次数")
    vector_calls: int = Field(0, description="向量检索次数")
    llm_calls: int = Field(0, description="LLM 调用次数")
    pending_directive: PendingDirective | None = Field(None, description="Pending 指令")


class HandlerResult(BaseModel):
    """Handler 执行结果。"""

    scenario_id: str = Field(description="场景 ID")
    reply: str = Field(description="回复内容")
    pending_directive: PendingDirective = Field(
        default=PendingDirective.CLEAR, description="Pending 指令"
    )
    pending_state: PendingState | None = Field(None, description="新 Pending（SET 时使用）")
    context_update: dict[str, Any] = Field(default_factory=dict, description="会话上下文更新")
    resource_trace: ResourceTrace = Field(
        default_factory=ResourceTrace, description="资源调用轨迹"
    )

    def model_post_init(self, __context: Any) -> None:
        """构造后将 scenario_id 同步到 resource_trace。"""
        self.resource_trace.scenario_id = self.scenario_id
        return super().model_post_init(__context)

    @classmethod
    def cancel(cls, scenario_id: str, reply: str) -> HandlerResult:
        """快捷构造取消结果。"""
        return cls(
            scenario_id=scenario_id,
            reply=reply,
            pending_directive=PendingDirective.CLEAR,
        )


class BaseHandler(ABC):
    """Handler 基类。

    execute() 处理新消息，resume() 恢复 Pending 流程。
    不实现 resume() 的 Handler 默认不支持 Pending 恢复。
    """

    @abstractmethod
    async def execute(
        self,
        decision: ScenarioDecision,
        context: Any,  # SessionContext（Phase 0 暂用 Any，后续定型）
    ) -> HandlerResult:
        """处理用户新消息。"""
        ...

    async def resume(
        self,
        pending: PendingState,
        message: str,
        context: Any,  # SessionContext
    ) -> HandlerResult:
        """恢复 Pending 流程。默认不支持。"""
        raise NotImplementedError(f"{type(self).__name__} 不支持 Pending 恢复")

    # ── ResourceTrace 辅助 ──

    def _init_trace_context(self, scenario_id: str) -> ResourceTrace:
        """初始化 ResourceTrace 并写入 contextvar。

        Gateway 层（LLMGateway / VectorGateway / SkillGateway）通过 contextvar
        自动记录 llm_calls / vector_calls / skill_calls。
        """
        trace = ResourceTrace(scenario_id=scenario_id)
        from app.ai.trace import set_trace

        set_trace({
            "llm_calls": 0,
            "vector_calls": 0,
            "skill_calls": [],
        })
        return trace

    def _merge_trace_context(self, result: HandlerResult) -> None:
        """将 contextvar 中的 Gateway 自动记录合并回 HandlerResult。

        覆盖 llm_calls / vector_calls / skill_calls 三个字段，
        合并后清理 contextvar。
        """
        from app.ai.trace import get_trace, set_trace

        td = get_trace()
        if td is not None:
            result.resource_trace.llm_calls = td.get("llm_calls", 0)
            result.resource_trace.vector_calls = td.get("vector_calls", 0)
            result.resource_trace.skill_calls = td.get("skill_calls", [])
        set_trace(None)


def call_skill_failed(method: str) -> ToolResult:
    """Skill 调用失败时的统一降级 ToolResult。"""
    return ToolResult(ok=False, skill_name=method, error="服务暂不可用")
