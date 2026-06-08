"""Agent 6 节点：上下文构建 → 置信度门控 → 技能规划 → 调度 → LLM生成 → 后处理。"""

import logging
import time

from langgraph.types import RunnableConfig

from app.ai.agent.argument_extractor import extract_arguments_for_plan
from app.ai.agent.argument_pending import merge_pending_arguments
from app.ai.agent.business_resolver import enrich_plan_with_business_context
from app.ai.agent.llm_argument_extractor import extract_arguments_with_llm
from app.ai.agent.skill_registry import SKILL_REGISTRY, resolve_skill
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
from app.config import settings

logger = logging.getLogger(__name__)


def _cfg(config: RunnableConfig | None) -> dict:
    """安全取出 config.configurable，避免各处重复 .get() 链。"""
    return (config or {}).get("configurable", {})


# Node 1: build_context — 初始化 AgentState
async def build_context(state: AgentState, config: RunnableConfig | None = None) -> AgentState:
    """从 config 提取 AgentContext + RoutedIntent，初始化 state。"""
    ctx: AgentContext = _cfg(config).get("agent_context")
    routed: RoutedIntent | None = _cfg(config).get("routed_intent")

    if ctx is None or routed is None:
        logger.error("[build_context] 缺少 context 或 intent，拒绝执行")
        state["error"] = "missing_context"
        return state

    customer_text = _extract_customer_text(routed)
    logger.info(
        "[build_context] tenant=%s conversation=%s intent=%s conf=%.2f text=%s",
        ctx.tenant_id, ctx.conversation_id,
        routed.primary_intent, routed.confidence,
        customer_text[:60],
    )

    state.update({
        "tenant_id": ctx.tenant_id,
        "conversation_id": ctx.conversation_id,
        "contact_id": ctx.contact_id,
        "tenant_custom_prompt": await get_custom_prompt(ctx.db, ctx.tenant_id),
        "execution_mode": "",
        "planned_tool_calls": [],
        "tool_results": [],
        "tool_call_count": 0,
        "final_reply": None,
        "error": None,
        "messages": [{"role": "user", "content": customer_text}],
    })
    return state


# Node 2: decide_execution_mode — 置信度门控
async def decide_execution_mode(state: AgentState, config: RunnableConfig | None = None) -> AgentState:
    """纯规则引擎：根据置信度 + skill 决定 DIRECT_SKILL / AGENT_PLANNER / CLARIFY。"""
    routed: RoutedIntent | None = _cfg(config).get("routed_intent")
    if routed is None:
        state["execution_mode"] = ExecutionMode.CLARIFY.value
        return state

    hits = routed.hits
    if routed.need_clarification:
        state["execution_mode"] = ExecutionMode.CLARIFY.value
        return state
    # 无命中或极低置信 → 追问澄清
    if not hits or routed.confidence < 0.5:
        state["execution_mode"] = ExecutionMode.CLARIFY.value
        return state

    # 单意图
    if not routed.is_multi_intent or len(hits) == 1:
        state["execution_mode"] = _decide_single(hits[0])
        return state

    # 多意图：全部高置信 + 有 skill → DIRECT；否则 AGENT_PLANNER
    all_direct = all(_can_direct(hit) for hit in hits)
    state["execution_mode"] = ExecutionMode.DIRECT_SKILL.value if all_direct else ExecutionMode.AGENT_PLANNER.value
    logger.info("[decide] %s hits=%s", state["execution_mode"], len(hits))
    return state


def _can_direct(hit) -> bool:
    """单个意图候选是否满足 DIRECT_SKILL 条件"""
    skill = resolve_skill(hit.skill)
    return skill is not None and hit.confidence >= 0.86 and not hit.ambiguous and not hit.need_clarification


def _decide_single(hit) -> str:
    """单意图模式决策。"""
    mode = ExecutionMode.DIRECT_SKILL.value if _can_direct(hit) else ExecutionMode.AGENT_PLANNER.value
    logger.info("[decide] %s intent=%s conf=%.2f", mode, hit.intent, hit.confidence)
    return mode


# Node 3: plan_tools_from_routed_intent
async def plan_tools_from_routed_intent(state: AgentState, config: RunnableConfig | None = None) -> AgentState:
    """从意图命中生成技能调用计划（DIRECT_SKILL / AGENT_PLANNER 均生成）。"""
    routed: RoutedIntent | None = _cfg(config).get("routed_intent")
    if routed is None:
        logger.info("[plan_tools] 无 routed_intent，清空工具计划")
        state["planned_tool_calls"] = []
        return state

    plans = [
        {
            "skill_name": skill_name,
            "arguments": {"query": hit.segment, "customer_text": _extract_customer_text(routed)},
            "source": "intent_route",
            "reason": hit.reason or f"{hit.intent} conf={hit.confidence:.2f}",
        }
        for hit in routed.hits
        if (skill_name := resolve_skill(hit.skill)) is not None
    ]
    logger.info("[plan_tools] 生成 %s 个技能计划: %s", len(plans), [p["skill_name"] for p in plans])
    state["planned_tool_calls"] = plans
    return state


# Node 4: normalize_planned_tool_arguments — 参数抽取与校验
async def normalize_planned_tool_arguments(state: AgentState, config: RunnableConfig | None = None) -> AgentState:
    """对每个技能调用计划执行确定性参数提取和 schema 校验。

    此处不从 LLM 获取参数，而是用正则+规则引擎从客户原文中抽取，
    确保参数质量，避免后续 dispatch_tools 时因参数缺失而失败。
    """
    ctx: AgentContext | None = _cfg(config).get("agent_context")
    normalized_plans: list[dict] = []
    for plan in state.get("planned_tool_calls", []):
        skill = str(plan.get("skill_name") or "?")
        normalized = extract_arguments_for_plan(plan)

        # LLM 参数补填（默认关）
        if settings.AI_AGENT_ENABLE_LLM_ARGUMENT_EXTRACTION and (
            normalized.get("missing_arguments") or normalized.get("argument_errors")
        ):
            llm_args = await extract_arguments_with_llm(
                skill,
                str((normalized.get("arguments") or {}).get("customer_text") or ""),
                dict(normalized.get("arguments") or {}),
                tenant_id=ctx.tenant_id if ctx else state.get("tenant_id"),
            )
            if llm_args:
                llm_plan = dict(normalized)
                llm_plan["arguments"] = {**dict(normalized.get("arguments") or {}), **llm_args}
                normalized = extract_arguments_for_plan(llm_plan)

        # 跨轮参数合并
        has_pending = ctx is not None and ctx.pending_state is not None
        if has_pending:
            pending_plan = dict(normalized)
            pending_plan["arguments"] = merge_pending_arguments(
                dict(normalized.get("arguments") or {}),
                ctx.pending_state,
                skill_name=skill,
            )
            normalized = extract_arguments_for_plan(pending_plan)

        # 业务数据解析（商品名→product_id）
        if ctx is not None:
            normalized = await enrich_plan_with_business_context(
                normalized,
                db=ctx.db,
                tenant_id=ctx.tenant_id,
            )

        missing = normalized.get("missing_arguments")
        errors = normalized.get("argument_errors")
        if missing or errors:
            logger.info("[normalize] %s 缺参=%s 错误=%s", skill, missing or "", errors or "")
        normalized_plans.append(normalized)

    state["planned_tool_calls"] = normalized_plans
    return state


async def dispatch_tools(state: AgentState, config: RunnableConfig | None = None) -> AgentState:
    """顺序执行技能调用，受 AI_AGENT_MAX_TOOL_CALLS 上限约束。

    执行前检查参数校验错误和缺失必填参数：
    - argument_errors → 直接标记失败，不执行技能
    - missing_arguments → 返回缺参提示，不执行技能
    """
    started = time.perf_counter()
    ctx: AgentContext = _cfg(config).get("agent_context")
    if ctx is None:
        state["error"] = "missing_agent_context"
        return state

    results: list[dict] = []
    count = state.get("tool_call_count", 0)
    max_calls = settings.AI_AGENT_MAX_TOOL_CALLS

    for plan in state.get("planned_tool_calls", []):
        if count >= max_calls:
            logger.warning("[dispatch] 达到技能调用上限 %s，跳过剩余计划", max_calls)
            break

        skill_name = plan["skill_name"]
        skill_func = SKILL_REGISTRY.get(skill_name)
        if skill_func is None:
            logger.error("[dispatch] 技能未注册: %s", skill_name)
            results.append({"skill_name": skill_name, "ok": False, "result": None, "error": f"Unknown: {skill_name}"})
            continue

        # 步骤 1：检查 Pydantic 参数校验错误
        if plan.get("argument_errors"):
            err_msg = "参数校验失败: " + "; ".join(plan["argument_errors"])
            logger.info("[dispatch] %s 参数校验未通过: %s", skill_name, err_msg)
            results.append({"skill_name": skill_name, "ok": False, "result": None, "error": err_msg})
            count += 1
            continue

        # 步骤 2：检查缺失的必填参数
        if plan.get("missing_arguments"):
            logger.info("[dispatch] %s 缺少必填参数: %s", skill_name, plan["missing_arguments"])
            results.append({
                "skill_name": skill_name,
                "ok": False,
                "result": None,
                "error": plan.get("missing_prompt") or "缺少必要参数。",
                "missing_arguments": plan["missing_arguments"],
                "pending_arguments": plan.get("arguments", {}),
            })
            count += 1
            continue

        # 步骤 3：通过校验后执行技能
        try:
            result: ToolResult = await skill_func(
                tenant_id=ctx.tenant_id, contact_id=ctx.contact_id, db=ctx.db,
                **plan.get("arguments", {}),
            )
            results.append({
                "skill_name": result.skill_name,
                "ok": result.ok,
                "result": result.result,
                "error": result.error,
            })
            if result.ok:
                logger.info("[dispatch] %s 执行成功, %s", skill_name,
                            str(result.result)[:80] if result.result else "无返回")
            else:
                logger.warning("[dispatch] %s 执行失败: %s", skill_name, result.error)
        except Exception as exc:
            logger.error("[dispatch] %s 异常: %s", skill_name, exc)
            results.append({"skill_name": skill_name, "ok": False, "result": None, "error": str(exc)})
        count += 1

    state["tool_results"] = results
    state["tool_call_count"] = count
    ok_count = sum(1 for r in results if r["ok"])
    logger.info("[dispatch] %s/%s ok, %.0fms", ok_count, len(results), (time.perf_counter() - started) * 1000)
    return state


# Node 5: generate_reply — LLM 生成回复
async def generate_reply(state: AgentState) -> AgentState:
    """按模式分发：CLARIFY 追问 / 基于工具结果生成 / 无结果兜底。"""
    mode = state.get("execution_mode", "")
    customer_text = state["messages"][0]["content"] if state.get("messages") else ""
    tool_results = state.get("tool_results", [])
    tenant_id = state.get("tenant_id")

    if mode == ExecutionMode.CLARIFY.value:
        logger.info("[generate] 模式=澄清追问, text=%s", customer_text[:40])
        state["final_reply"] = await _generate_clarify_reply(customer_text)
    elif missing_reply := _missing_argument_reply(tool_results):
        logger.info("[generate] 模式=缺参追问, text=%s", customer_text[:40])
        state["final_reply"] = missing_reply
    elif not tool_results:
        logger.info("[generate] 模式=无技能结果兜底, text=%s", customer_text[:40])
        state["final_reply"] = await _generate_fallback_reply(customer_text)
    else:
        tool_count = len([r for r in tool_results if r.get("ok")])
        logger.info("[generate] 模式=基于技能结果合成, text=%s 成功技能=%s/%s",
                    customer_text[:40], tool_count, len(tool_results))
        state["final_reply"] = await _generate_from_tool_results(
            customer_text, tool_results, tenant_id=tenant_id,
            tenant_custom_prompt=state.get("tenant_custom_prompt"),
        )
    return state


# Node 6: post_process — 格式清洗 + 兜底
async def post_process(state: AgentState) -> AgentState:
    """去除 LLM 输出前缀 + 空回复兜底。"""
    reply = (state.get("final_reply") or "").strip()
    for prefix in ("客服：", "助手：", "AI：", "回复：", "回答："):
        if reply.startswith(prefix):
            reply = reply[len(prefix):].strip()
            logger.debug("[post_process] 去除前缀 %s", prefix)

    if not reply:
        mode = state.get("execution_mode", "")
        fallback_key = {
            ExecutionMode.AGENT_PLANNER.value: "agent_planner",
            ExecutionMode.CLARIFY.value: "clarify_product_or_order",
        }.get(mode, "generic_ack")
        reply = FALLBACK_MESSAGES.get(fallback_key, "请稍后再试")
        logger.info("[post_process] 回复为空，使用兜底: mode=%s key=%s", mode, fallback_key)
    else:
        logger.info("[post_process] 最终回复长度=%s", len(reply))

    state["final_reply"] = reply
    return state


# 内部 helpers
async def _generate_from_tool_results(
    customer_text: str, tool_results: list[dict], *, tenant_id: int | None = None,
    tenant_custom_prompt: str | None = None,
) -> str:
    """基于技能结果调用 LLM 生成自然回复，失败时模板兜底。"""
    try:
        return await complete(
            LLMUseCase.AGENT,
            build_generate_reply_messages(customer_text, tool_results, tenant_custom_prompt=tenant_custom_prompt),
            tenant_id=tenant_id, temperature=0.2,
        )
    except LLMClientError:
        return _template_fallback(tool_results)


async def _generate_clarify_reply(customer_text: str) -> str:
    """生成澄清追问 — 用本地轻量模型，不走租户大模型。"""
    try:
        return await complete(
            LLMUseCase.GENERAL_REPLY, build_clarify_messages(customer_text), temperature=0.2,
        )
    except LLMClientError:
        return FALLBACK_MESSAGES["clarify_product_or_order"]


async def _generate_fallback_reply(customer_text: str) -> str:
    """无技能结果时的兜底回复 — 用本地轻量模型。"""
    try:
        return await complete(
            LLMUseCase.GENERAL_REPLY, build_fallback_messages(customer_text), temperature=0.2,
        )
    except LLMClientError:
        return FALLBACK_MESSAGES["empty_reply_general"]


def _template_fallback(tool_results: list[dict]) -> str:
    """LLM 不可用时从技能结果中拼接模板。"""
    parts = []
    for r in tool_results:
        if not r.get("ok"):
            continue
        result = r.get("result")
        if isinstance(result, dict) and "message" in result:
            parts.append(str(result["message"]))
        elif isinstance(result, str):
            parts.append(result)
    return "\n\n".join(parts) or FALLBACK_MESSAGES["template_fallback"]


def _missing_argument_reply(tool_results: list[dict]) -> str | None:
    """收集所有技能调用中缺失参数的追问话术，去重后拼接返回。"""
    prompts = [
        str(result.get("error") or "").strip()
        for result in tool_results
        if result.get("missing_arguments")
    ]
    prompts = [prompt for prompt in prompts if prompt]
    return "\n".join(dict.fromkeys(prompts)) if prompts else None


def _extract_customer_text(routed: RoutedIntent) -> str:
    segments = [h.segment for h in routed.hits if h.segment]
    return "；".join(segments) or "用户暂未提供明确问题"
