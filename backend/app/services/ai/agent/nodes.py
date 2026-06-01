"""Phase 9 Agent 节点：置信度门控 + 工具调度 + 回复生成。

每个节点必须有结构化日志，格式: [节点名] key1=value1 key2=value2
"""

import logging
import time

from langgraph.types import RunnableConfig

from app.config import settings
from app.integrations.llm_client import LLMClient, LLMClientError
from app.services.ai.agent.prompts import build_generate_reply_user_prompt, get_effective_system_prompt
from app.services.ai.agent.skill_registry import SIDEEFFECT_SKILLS, SKILL_REGISTRY, resolve_skill
from app.services.ai.agent.types import AgentContext, AgentState, ExecutionMode, ToolResult
from app.services.ai.intent.types import RoutedIntent
from app.services.ai.tenant_ai_config import (
    DEFAULT_CLARIFY_PROMPT,
    DEFAULT_FALLBACK_MESSAGES,
    DEFAULT_FALLBACK_SYSTEM_PROMPT,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Node: build_context
# ---------------------------------------------------------------------------


async def build_context(state: AgentState, config: RunnableConfig | None = None) -> AgentState:
    """从 config 提取 AgentContext，反序列化 RoutedIntent。

    输入: state (空或部分填充) + config["configurable"]["agent_context"]
    输出: state 填充 tenant_id / conversation_id / contact_id / routed_intent / messages
    """
    started = time.perf_counter()
    if config is None:
        config = {}
    ctx: AgentContext = config.get("configurable", {}).get("agent_context")
    routed: RoutedIntent | None = config.get("configurable", {}).get("routed_intent")
    if ctx is None:
        logger.error("[build_context] 缺少 AgentContext — 检查 config 传递")
        state["error"] = "missing_agent_context"
        return state
    if routed is None:
        logger.error("[build_context] 缺少 RoutedIntent — 检查 config 传递")
        state["error"] = "missing_routed_intent"
        return state

    customer_text = _extract_customer_text(routed)

    state["tenant_id"] = ctx.tenant_id
    state["conversation_id"] = ctx.conversation_id
    state["contact_id"] = ctx.contact_id
    state["execution_mode"] = ""
    state["planned_tool_calls"] = []
    state["tool_results"] = []
    state["tool_call_count"] = 0
    state["final_reply"] = None
    state["error"] = None
    state["messages"] = [{"role": "user", "content": customer_text}]

    logger.info(
        "[build_context] tenant_id=%s conversation_id=%s contact_id=%s "
        "intent=%s route=%s confidence=%.4f hits=%s multi=%s elapsed_ms=%.0f",
        ctx.tenant_id,
        ctx.conversation_id,
        ctx.contact_id,
        routed.primary_intent,
        routed.route,
        routed.confidence,
        len(routed.hits),
        routed.is_multi_intent,
        (time.perf_counter() - started) * 1000,
    )
    return state


# ---------------------------------------------------------------------------
# Node: decide_execution_mode
# ---------------------------------------------------------------------------


async def decide_execution_mode(state: AgentState, config: RunnableConfig | None = None) -> AgentState:
    """置信度门控：纯规则引擎，不用 LLM。

    从 config 读取 RoutedIntent（不由 state 反序列化），输出 state.execution_mode。
    """
    started = time.perf_counter()
    if config is None:
        config = {}
    routed: RoutedIntent | None = config.get("configurable", {}).get("routed_intent")
    if routed is None:
        logger.error("[decide_execution_mode] 缺少 RoutedIntent — 检查 config 传递")
        state["execution_mode"] = ExecutionMode.CLARIFY.value
        return state

    hits = routed.hits

    # 1. 无 hits 或极低置信 → CLARIFY
    if not hits or routed.confidence < 0.5:
        logger.info(
            "[decide_execution_mode] mode=CLARIFY reason=%s confidence=%.4f",
            "no_hits" if not hits else "low_confidence",
            routed.confidence,
        )
        state["execution_mode"] = ExecutionMode.CLARIFY.value
        return state

    # 2. 单 hit
    if not routed.is_multi_intent or len(hits) == 1:
        hit = hits[0]
        skill_name = resolve_skill(hit.skill)
        if (
            hit.confidence >= 0.86
            and skill_name is not None
            and not hit.ambiguous
            and skill_name not in SIDEEFFECT_SKILLS
        ):
            logger.info(
                "[decide_execution_mode] mode=DIRECT_SKILL reason=high_confidence_single "
                "intent=%s skill=%s confidence=%.4f",
                hit.intent,
                skill_name,
                hit.confidence,
            )
            state["execution_mode"] = ExecutionMode.DIRECT_SKILL.value
        else:
            reason = "low_confidence" if hit.confidence < 0.86 else (
                "ambiguous" if hit.ambiguous else "skill_not_registered_or_sideeffect"
            )
            logger.info(
                "[decide_execution_mode] mode=AGENT_PLANNER reason=%s "
                "intent=%s skill=%s confidence=%.4f ambiguous=%s",
                reason,
                hit.intent,
                skill_name,
                hit.confidence,
                hit.ambiguous,
            )
            state["execution_mode"] = ExecutionMode.AGENT_PLANNER.value
        return state

    # 3. 多 hits
    all_direct = True
    for hit in hits:
        skill_name = resolve_skill(hit.skill)
        if hit.confidence < 0.86 or skill_name is None or hit.ambiguous or skill_name in SIDEEFFECT_SKILLS:
            all_direct = False
            break

    if all_direct:
        skill_list = [resolve_skill(h.skill) for h in hits]
        logger.info(
            "[decide_execution_mode] mode=DIRECT_SKILL reason=multi_hit_all_high_confidence "
            "hits=%s skills=%s",
            len(hits),
            skill_list,
        )
        state["execution_mode"] = ExecutionMode.DIRECT_SKILL.value
    else:
        logger.info(
            "[decide_execution_mode] mode=AGENT_PLANNER reason=multi_hit_not_all_qualified hits=%s",
            len(hits),
        )
        state["execution_mode"] = ExecutionMode.AGENT_PLANNER.value

    logger.info(
        "[decide_execution_mode] mode=%s elapsed_ms=%.0f",
        state["execution_mode"],
        (time.perf_counter() - started) * 1000,
    )
    return state


# ---------------------------------------------------------------------------
# Node: plan_tools_from_routed_intent
# ---------------------------------------------------------------------------


async def plan_tools_from_routed_intent(state: AgentState, config: RunnableConfig | None = None) -> AgentState:
    """从 RoutedIntent 生成 PlannedToolCall 列表。

    DIRECT_SKILL: 查 intent→skill→tool 映射表，不用 LLM
    AGENT_PLANNER: stub — 返回空列表
    """
    started = time.perf_counter()
    mode = state["execution_mode"]

    if mode == ExecutionMode.AGENT_PLANNER.value:
        logger.info("[plan_tools] mode=AGENT_PLANNER — stub 返回空列表")
        state["planned_tool_calls"] = []
        return state

    # DIRECT_SKILL
    if config is None:
        config = {}
    routed: RoutedIntent | None = config.get("configurable", {}).get("routed_intent")
    if routed is None:
        logger.error("[plan_tools] 缺少 RoutedIntent — 检查 config 传递")
        state["planned_tool_calls"] = []
        return state

    plans: list[dict] = []

    for hit in routed.hits:
        skill_name = resolve_skill(hit.skill)
        if skill_name is None:
            logger.info(
                "[plan_tools] 跳过无 skill 的 hit：intent=%s skill=%s",
                hit.intent,
                hit.skill,
            )
            continue

        plans.append({
            "skill_name": skill_name,
            "arguments": {
                "query": hit.segment,
                "customer_text": _extract_customer_text(routed),
            },
            "source": "intent_route",
            "reason": hit.reason or f"意图 {hit.intent} 置信度 {hit.confidence:.2f}",
        })
        logger.info(
            "[plan_tools] 生成 PlannedToolCall：skill=%s intent=%s confidence=%.4f",
            skill_name,
            hit.intent,
            hit.confidence,
        )

    state["planned_tool_calls"] = plans
    logger.info(
        "[plan_tools] mode=DIRECT_SKILL planned_count=%s elapsed_ms=%.0f",
        len(plans),
        (time.perf_counter() - started) * 1000,
    )
    return state


# ---------------------------------------------------------------------------
# Node: dispatch_tools
# ---------------------------------------------------------------------------


async def dispatch_tools(state: AgentState, config: RunnableConfig | None = None) -> AgentState:
    """顺序执行 planned_tool_calls，上限 10 次。

    从 config 获取 AgentContext（含 db session），注入 tenant_id / contact_id。
    """
    started = time.perf_counter()
    if config is None:
        config = {}
    ctx: AgentContext = config.get("configurable", {}).get("agent_context")
    if ctx is None:
        logger.error("[dispatch_tools] 缺少 AgentContext — 检查 config 传递")
        state["error"] = "missing_agent_context"
        return state
    plans = state.get("planned_tool_calls", [])
    results: list[dict] = []
    count = state.get("tool_call_count", 0)

    for i, plan in enumerate(plans):
        max_calls = settings.AI_AGENT_MAX_TOOL_CALLS
        if count >= max_calls:
            logger.warning(
                "[dispatch_tools] 达到调用上限 max=%s current=%s — 停止调度",
                max_calls,
                count,
            )
            break

        skill_name = plan["skill_name"]
        skill_func = SKILL_REGISTRY.get(skill_name)

        if skill_func is None:
            logger.warning("[dispatch_tools] 未知 skill：%s — 跳过", skill_name)
            results.append({
                "skill_name": skill_name,
                "ok": False,
                "result": None,
                "error": f"Unknown skill: {skill_name}",
            })
            continue

        call_started = time.perf_counter()
        try:
            result: ToolResult = await skill_func(
                tenant_id=ctx.tenant_id,
                contact_id=ctx.contact_id,
                db=ctx.db,
                **plan.get("arguments", {}),
            )
            elapsed = (time.perf_counter() - call_started) * 1000
            logger.info(
                "[dispatch_tools] [%s/%s] skill=%s ok=%s elapsed_ms=%.0f",
                i + 1,
                len(plans),
                skill_name,
                result.ok,
                elapsed,
            )
            results.append({
                "skill_name": result.skill_name,
                "ok": result.ok,
                "result": result.result,
                "error": result.error,
            })
        except Exception as exc:
            elapsed = (time.perf_counter() - call_started) * 1000
            logger.error(
                "[dispatch_tools] [%s/%s] skill=%s 异常：%s elapsed_ms=%.0f",
                i + 1,
                len(plans),
                skill_name,
                exc,
                elapsed,
            )
            results.append({
                "skill_name": skill_name,
                "ok": False,
                "result": None,
                "error": str(exc),
            })

        count += 1

    state["tool_results"] = results
    state["tool_call_count"] = count
    logger.info(
        "[dispatch_tools] 完成：executed=%s ok=%s fail=%s total_elapsed_ms=%.0f",
        len(results),
        sum(1 for r in results if r["ok"]),
        sum(1 for r in results if not r["ok"]),
        (time.perf_counter() - started) * 1000,
    )
    return state


# ---------------------------------------------------------------------------
# Node: generate_reply
# ---------------------------------------------------------------------------


async def generate_reply(state: AgentState) -> AgentState:
    """LLM 将 tool_results + 上下文组织成自然客服回复。

    CLARIFY 模式: 生成澄清追问
    无 tool_results: 直接用上下文生成通用回复
    """
    started = time.perf_counter()
    mode = state.get("execution_mode", "")
    customer_text = state["messages"][0]["content"] if state.get("messages") else ""
    tool_results = state.get("tool_results", [])

    # AGENT_PLANNER stub: 直接返回固定话术
    if mode == ExecutionMode.AGENT_PLANNER.value:
        logger.info("[generate_reply] mode=AGENT_PLANNER — stub 固定话术")
        state["final_reply"] = DEFAULT_FALLBACK_MESSAGES["agent_planner"]
        return state

    # CLARIFY: 生成澄清追问
    if mode == ExecutionMode.CLARIFY.value:
        reply = await _generate_clarify_reply(customer_text)
        state["final_reply"] = reply
        logger.info(
            "[generate_reply] mode=CLARIFY reply_len=%s elapsed_ms=%.0f",
            len(reply),
            (time.perf_counter() - started) * 1000,
        )
        return state

    # DIRECT_SKILL: 基于 tool_results 生成自然回复
    if not tool_results:
        logger.info("[generate_reply] 无 tool_results — 生成通用引导回复")
        reply = await _generate_fallback_reply(customer_text)
        state["final_reply"] = reply
        return state

    reply = await _generate_from_tool_results(customer_text, tool_results)
    state["final_reply"] = reply
    logger.info(
        "[generate_reply] mode=DIRECT_SKILL tool_count=%s reply_len=%s elapsed_ms=%.0f",
        len(tool_results),
        len(reply),
        (time.perf_counter() - started) * 1000,
    )
    return state


# ---------------------------------------------------------------------------
# Node: post_process
# ---------------------------------------------------------------------------


async def post_process(state: AgentState) -> AgentState:
    """格式清洗 + 日志 + 错误兜底。"""
    started = time.perf_counter()
    reply = state.get("final_reply") or ""

    # 格式清洗
    reply = reply.strip()
    # 去除常见的 LLM 多输出标记
    for prefix in ("客服：", "助手：", "AI：", "回复：", "回答："):
        if reply.startswith(prefix):
            reply = reply[len(prefix):].strip()

    # 错误兜底
    if not reply:
        mode = state.get("execution_mode", "")
        if mode == ExecutionMode.AGENT_PLANNER.value:
            reply = DEFAULT_FALLBACK_MESSAGES["agent_planner"]
        elif mode == ExecutionMode.CLARIFY.value:
            reply = DEFAULT_FALLBACK_MESSAGES["clarify_product_or_order"]
        else:
            reply = DEFAULT_FALLBACK_MESSAGES["generic_ack"]

    state["final_reply"] = reply
    logger.info(
        "[post_process] mode=%s reply_len=%s error=%s elapsed_ms=%.0f",
        state.get("execution_mode"),
        len(reply),
        state.get("error"),
        (time.perf_counter() - started) * 1000,
    )
    return state


# ===========================================================================
# Internal helpers
# ===========================================================================


async def _generate_from_tool_results(customer_text: str, tool_results: list[dict], system_prompt: str | None = None) -> str:
    """LLM 基于 tool_results 生成自然回复。"""
    user_prompt = build_generate_reply_user_prompt(customer_text, tool_results)
    messages = [
        {"role": "system", "content": system_prompt or get_effective_system_prompt()},
        {"role": "user", "content": user_prompt},
    ]
    try:
        client = LLMClient()
        return await client.complete(
            messages,
            model=settings.AI_AGENT_MODEL or settings.AI_LLM_MODEL,
            max_tokens=settings.AI_AGENT_MAX_TOKENS,
            temperature=settings.AI_AGENT_TEMPERATURE,
        )
    except LLMClientError as exc:
        logger.warning("[generate_reply] LLM 调用失败：%s — 使用模板兜底", exc)
        return _template_fallback(tool_results)


async def _generate_clarify_reply(customer_text: str) -> str:
    """生成澄清追问。"""
    clarify_prompt = DEFAULT_CLARIFY_PROMPT
    messages = [
        {"role": "system", "content": clarify_prompt},
        {"role": "user", "content": customer_text or "用户暂未提供明确问题"},
    ]
    try:
        client = LLMClient()
        return await client.complete(
            messages,
            model=settings.AI_GENERAL_REPLY_MODEL or settings.AI_LLM_MODEL,
            max_tokens=settings.AI_GENERAL_REPLY_MAX_TOKENS,
            temperature=settings.AI_GENERAL_REPLY_TEMPERATURE,
        )
    except LLMClientError:
        return DEFAULT_FALLBACK_MESSAGES["clarify_product_or_order"]


async def _generate_fallback_reply(customer_text: str) -> str:
    """无工具调用时的兜底回复。"""
    messages = [
        {"role": "system", "content": DEFAULT_FALLBACK_SYSTEM_PROMPT},
        {"role": "user", "content": customer_text or "你好"},
    ]
    try:
        client = LLMClient()
        return await client.complete(
            messages,
            model=settings.AI_GENERAL_REPLY_MODEL or settings.AI_LLM_MODEL,
            max_tokens=settings.AI_GENERAL_REPLY_MAX_TOKENS,
            temperature=settings.AI_GENERAL_REPLY_TEMPERATURE,
        )
    except LLMClientError:
        return DEFAULT_FALLBACK_MESSAGES["empty_reply_general"]


def _template_fallback(tool_results: list[dict]) -> str:
    """无 LLM 时的模板兜底。"""
    ok_results = [r for r in tool_results if r.get("ok")]
    if not ok_results:
        return DEFAULT_FALLBACK_MESSAGES["error_fallback"]
    parts: list[str] = []
    for r in ok_results:
        result = r.get("result")
        if isinstance(result, dict) and "message" in result:
            parts.append(str(result["message"]))
        elif isinstance(result, str):
            parts.append(result)
    return "\n\n".join(parts) if parts else DEFAULT_FALLBACK_MESSAGES["template_fallback"]


def _extract_customer_text(routed: RoutedIntent) -> str:
    segments = [h.segment for h in routed.hits if h.segment]
    return "；".join(segments) or "用户暂未提供明确问题"
