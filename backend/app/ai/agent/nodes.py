"""Agent 节点：置信度门控 + 工具调度 + 回复生成。"""

import logging
import time

from langgraph.types import RunnableConfig

from app.config import settings
from app.ai.agent.skill_registry import SIDEEFFECT_SKILLS, SKILL_REGISTRY, resolve_skill
from app.ai.agent.types import AgentContext, AgentState, ExecutionMode, ToolResult
from app.ai.classifier.types import RoutedIntent
from app.ai.llm.gateway import LLMClientError, LLMUseCase, complete
from app.ai.llm.prompts.agent import (
    FALLBACK_MESSAGES,
    build_clarify_messages,
    build_fallback_messages,
    build_generate_reply_messages,
)
from app.ai.tenant_config import get_custom_prompt

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# Node 1: build_context
# ──────────────────────────────────────────────

async def build_context(state: AgentState, config: RunnableConfig | None = None) -> AgentState:
    """从 config 提取 AgentContext + RoutedIntent，初始化 state。"""
    if config is None:
        config = {}
    ctx: AgentContext = config.get("configurable", {}).get("agent_context")
    routed: RoutedIntent | None = config.get("configurable", {}).get("routed_intent")

    if ctx is None or routed is None:
        logger.error("[build_context] 缺少 AgentContext 或 RoutedIntent")
        state["error"] = "missing_context"
        return state

    state["tenant_id"] = ctx.tenant_id
    state["conversation_id"] = ctx.conversation_id
    state["contact_id"] = ctx.contact_id
    state["tenant_custom_prompt"] = await get_custom_prompt(ctx.db, ctx.tenant_id)
    state["execution_mode"] = ""
    state["planned_tool_calls"] = []
    state["tool_results"] = []
    state["tool_call_count"] = 0
    state["final_reply"] = None
    state["error"] = None
    state["messages"] = [{"role": "user", "content": _extract_customer_text(routed)}]
    return state


# ──────────────────────────────────────────────
# Node 2: decide_execution_mode  — 置信度门控
# ──────────────────────────────────────────────

async def decide_execution_mode(state: AgentState, config: RunnableConfig | None = None) -> AgentState:
    """纯规则引擎：根据置信度 + 候选 skill 决定 DIRECT_SKILL / AGENT_PLANNER / CLARIFY。"""
    if config is None:
        config = {}
    routed: RoutedIntent | None = config.get("configurable", {}).get("routed_intent")
    if routed is None:
        state["execution_mode"] = ExecutionMode.CLARIFY.value
        return state

    hits = routed.hits

    # 无命中或极低置信 → 追问澄清
    if not hits or routed.confidence < 0.5:
        state["execution_mode"] = ExecutionMode.CLARIFY.value
        return state

    # 单意图
    if not routed.is_multi_intent or len(hits) == 1:
        hit = hits[0]
        skill_name = resolve_skill(hit.skill)
        if (
            hit.confidence >= 0.86
            and skill_name is not None
            and not hit.ambiguous
            and skill_name not in SIDEEFFECT_SKILLS
        ):
            state["execution_mode"] = ExecutionMode.DIRECT_SKILL.value
            logger.info("[decide] DIRECT_SKILL intent=%s skill=%s conf=%.2f", hit.intent, skill_name, hit.confidence)
        else:
            state["execution_mode"] = ExecutionMode.AGENT_PLANNER.value
            logger.info("[decide] AGENT_PLANNER intent=%s conf=%.2f", hit.intent, hit.confidence)
        return state

    # 多意图：全部高置信且有 skill 才直接执行
    all_direct = all(
        hit.confidence >= 0.86
        and resolve_skill(hit.skill) is not None
        and not hit.ambiguous
        and resolve_skill(hit.skill) not in SIDEEFFECT_SKILLS
        for hit in hits
    )
    state["execution_mode"] = ExecutionMode.DIRECT_SKILL.value if all_direct else ExecutionMode.AGENT_PLANNER.value
    logger.info("[decide] %s hits=%s", state["execution_mode"], len(hits))
    return state


# ──────────────────────────────────────────────
# Node 3: plan_tools_from_routed_intent
# ──────────────────────────────────────────────

async def plan_tools_from_routed_intent(state: AgentState, config: RunnableConfig | None = None) -> AgentState:
    """从 RoutedIntent 的 hits 生成技能调用计划。DIRECT_SKILL 走映射表，AGENT_PLANNER 返回空。"""
    if state["execution_mode"] == ExecutionMode.AGENT_PLANNER.value:
        state["planned_tool_calls"] = []
        return state

    if config is None:
        config = {}
    routed: RoutedIntent | None = config.get("configurable", {}).get("routed_intent")
    if routed is None:
        state["planned_tool_calls"] = []
        return state

    plans: list[dict] = []
    for hit in routed.hits:
        skill_name = resolve_skill(hit.skill)
        if skill_name is None:
            continue
        plans.append({
            "skill_name": skill_name,
            "arguments": {
                "query": hit.segment,
                "customer_text": _extract_customer_text(routed),
            },
            "source": "intent_route",
            "reason": hit.reason or f"{hit.intent} conf={hit.confidence:.2f}",
        })

    state["planned_tool_calls"] = plans
    return state


# ──────────────────────────────────────────────
# Node 4: dispatch_tools  — 顺序执行技能
# ──────────────────────────────────────────────

async def dispatch_tools(state: AgentState, config: RunnableConfig | None = None) -> AgentState:
    """顺序执行 planned_tool_calls，最多 AI_AGENT_MAX_TOOL_CALLS 次。"""
    started = time.perf_counter()
    if config is None:
        config = {}
    ctx: AgentContext = config.get("configurable", {}).get("agent_context")
    if ctx is None:
        state["error"] = "missing_agent_context"
        return state

    plans = state.get("planned_tool_calls", [])
    results: list[dict] = []
    count = state.get("tool_call_count", 0)
    max_calls = settings.AI_AGENT_MAX_TOOL_CALLS

    for plan in plans:
        if count >= max_calls:
            logger.warning("[dispatch] 达到调用上限 max=%s", max_calls)
            break

        skill_name = plan["skill_name"]
        skill_func = SKILL_REGISTRY.get(skill_name)
        if skill_func is None:
            results.append({"skill_name": skill_name, "ok": False, "result": None, "error": f"Unknown: {skill_name}"})
            continue

        try:
            result: ToolResult = await skill_func(
                tenant_id=ctx.tenant_id, contact_id=ctx.contact_id, db=ctx.db,
                **plan.get("arguments", {}),
            )
            results.append({"skill_name": result.skill_name, "ok": result.ok, "result": result.result, "error": result.error})
        except Exception as exc:
            logger.error("[dispatch] skill=%s 异常: %s", skill_name, exc)
            results.append({"skill_name": skill_name, "ok": False, "result": None, "error": str(exc)})
        count += 1

    state["tool_results"] = results
    state["tool_call_count"] = count
    ok_count = sum(1 for r in results if r["ok"])
    logger.info("[dispatch] 完成 %s/%s ok elapsed=%.0fms", ok_count, len(results), (time.perf_counter() - started) * 1000)
    return state


# ──────────────────────────────────────────────
# Node 5: generate_reply  — LLM 生成回复
# ──────────────────────────────────────────────

async def generate_reply(state: AgentState) -> AgentState:
    """LLM 将 tool_results 转为自然客服回复。Agent 优先使用租户模型，兜底本地。"""
    mode = state.get("execution_mode", "")
    customer_text = state["messages"][0]["content"] if state.get("messages") else ""
    tool_results = state.get("tool_results", [])
    tenant_id = state.get("tenant_id")

    # AGENT_PLANNER stub: 固定话术
    if mode == ExecutionMode.AGENT_PLANNER.value:
        state["final_reply"] = FALLBACK_MESSAGES["agent_planner"]
        return state

    # CLARIFY: 生成澄清追问
    if mode == ExecutionMode.CLARIFY.value:
        state["final_reply"] = await _generate_clarify_reply(customer_text, tenant_id=tenant_id)
        return state

    # DIRECT_SKILL: 基于 tool_results 生成回复
    if not tool_results:
        state["final_reply"] = await _generate_fallback_reply(customer_text, tenant_id=tenant_id)
    else:
        state["final_reply"] = await _generate_from_tool_results(
            customer_text,
            tool_results,
            tenant_id=tenant_id,
            tenant_custom_prompt=state.get("tenant_custom_prompt"),
        )
    return state


# ──────────────────────────────────────────────
# Node 6: post_process  — 格式清洗 + 兜底
# ──────────────────────────────────────────────

async def post_process(state: AgentState) -> AgentState:
    """格式清洗 + 空回复兜底。"""
    reply = (state.get("final_reply") or "").strip()
    for prefix in ("客服：", "助手：", "AI：", "回复：", "回答："):
        if reply.startswith(prefix):
            reply = reply[len(prefix):].strip()

    if not reply:
        mode = state.get("execution_mode", "")
        if mode == ExecutionMode.AGENT_PLANNER.value:
            reply = FALLBACK_MESSAGES["agent_planner"]
        elif mode == ExecutionMode.CLARIFY.value:
            reply = FALLBACK_MESSAGES["clarify_product_or_order"]
        else:
            reply = FALLBACK_MESSAGES["generic_ack"]

    state["final_reply"] = reply
    return state


# ===========================================================================
# 内部 helpers
# ===========================================================================


async def _generate_from_tool_results(
    customer_text: str, tool_results: list[dict], *, tenant_id: int | None = None,
    tenant_custom_prompt: str | None = None,
) -> str:
    """基于技能结果生成自然回复。"""
    try:
        return await complete(
            LLMUseCase.AGENT,
            build_generate_reply_messages(
                customer_text,
                tool_results,
                tenant_custom_prompt=tenant_custom_prompt,
            ),
            tenant_id=tenant_id,
            temperature=0.2,
        )
    except LLMClientError:
        return _template_fallback(tool_results)


async def _generate_clarify_reply(customer_text: str, *, tenant_id: int | None = None) -> str:
    """生成澄清追问。"""
    try:
        return await complete(
            LLMUseCase.AGENT,
            build_clarify_messages(customer_text),
            tenant_id=tenant_id,
            temperature=0.2,
        )
    except LLMClientError:
        return FALLBACK_MESSAGES["clarify_product_or_order"]


async def _generate_fallback_reply(customer_text: str, *, tenant_id: int | None = None) -> str:
    """无技能结果时的兜底回复。"""
    try:
        return await complete(
            LLMUseCase.AGENT,
            build_fallback_messages(customer_text),
            tenant_id=tenant_id,
            temperature=0.2,
        )
    except LLMClientError:
        return FALLBACK_MESSAGES["empty_reply_general"]


def _template_fallback(tool_results: list[dict]) -> str:
    """LLM 不可用时的模板拼接兜底。"""
    ok_results = [r for r in tool_results if r.get("ok")]
    if not ok_results:
        return FALLBACK_MESSAGES["error_fallback"]
    parts = [
        str(r["result"]["message"]) if isinstance(r.get("result"), dict) and "message" in r["result"]
        else str(r["result"]) if isinstance(r.get("result"), str)
        else ""
        for r in ok_results
    ]
    return "\n\n".join(p for p in parts if p) or FALLBACK_MESSAGES["template_fallback"]


def _extract_customer_text(routed: RoutedIntent) -> str:
    segments = [h.segment for h in routed.hits if h.segment]
    return "；".join(segments) or "用户暂未提供明确问题"
