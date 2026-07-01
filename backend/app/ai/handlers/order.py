"""OrderHandler — 订单场景 Handler。

支持以下 scenario：
  - order.list / order.filter / order.detail / order.shipping_status
  - order.create（使用 OrderCreationGraph 子图）
  - order.cancel（使用 OrderCancelGraph 子图）
  - order.confirm（骨架占位）

写操作（order.create / order.cancel）保留 LangGraph 子图，
Redis PendingState 只保存 graph_thread_id / interrupt_id。
"""

from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any

from app.ai.components.order_create_guard import OrderCreateGuard
from app.ai.components.order_reference import (
    OrderReferenceResolver,
    OrderReferenceResult,
    _extract_order_number,
)
from app.ai.context.pending_state import PendingDirective, PendingState
from app.ai.graphs.observability import (
    graph_run_input_summary,
    graph_run_output_summary,
    graph_snapshot_metadata,
)
from app.ai.handlers.base import BaseHandler, HandlerResult, call_skill_failed
from app.ai.observability import observe_span, set_observation_io
from app.ai.recognition.types import ScenarioDecision
from app.ai.reply_builders.order import OrderReplyBuilder
from app.ai.context.session_context import SessionContext
from app.ai.handlers.base import ToolResult
from app.ai.services.order_create_start_lock import (
    OrderCreateStartLock,
    order_create_start_lock,
)
from app.ai.skills.gateway import SkillError, call_skill
from app.config import settings

logger = logging.getLogger(__name__)

_CN_NUM_MAP: dict[str, int] = {
    "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
    "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
}
_RE_ORDER_PRODUCT_ORDINAL = re.compile(r"第\s*([一二两三四五六七八九十\d]+)\s*[款个台件]?")
_RE_BARE_NUMBER = re.compile(r"^\s*(\d+)\s*$")
_PRODUCT_DEIXIS_WORDS: tuple[str, ...] = (
    "这个", "这款", "它", "那个", "那款",
    "刚才那个", "刚刚那个", "刚才那款", "刚刚那款",
)


def _parse_order_product_ordinal(text: str) -> int | None:
    """从下单文本中解析商品序号。"""
    stripped = text.strip()
    m = _RE_BARE_NUMBER.fullmatch(stripped)
    if m:
        return int(m.group(1))
    m = _RE_ORDER_PRODUCT_ORDINAL.search(stripped)
    if not m:
        return None
    raw = m.group(1).strip()
    return int(raw) if raw.isdigit() else _CN_NUM_MAP.get(raw)


def _contains_product_deixis(text: str) -> bool:
    """判断下单文本中是否包含商品指代。"""
    stripped = text.strip()
    return bool(stripped) and any(word in stripped for word in _PRODUCT_DEIXIS_WORDS)


def _candidate_id_name(item: Any) -> tuple[str, str] | None:
    """兼容 product_candidates / last_visible_products 的商品候选格式。"""
    if not isinstance(item, dict):
        return None
    raw_id = item.get("product_id") or item.get("id")
    if raw_id is None:
        return None
    name = str(item.get("name") or item.get("product_name") or "")
    return str(raw_id), name


def _context_product_candidates(ctx: SessionContext) -> list[dict[str, str]]:
    """按最近可见顺序提取商品候选。"""
    raw_candidates = ctx.last_visible_products or ctx.product_candidates
    candidates: list[dict[str, str]] = []
    for item in raw_candidates:
        id_name = _candidate_id_name(item)
        if id_name is not None:
            pid, name = id_name
            candidates.append({"id": pid, "name": name})
    return candidates


def _resolve_create_product_from_context(text: str, ctx: SessionContext) -> tuple[str | None, str | None, str | None]:
    """解析下单文本中的商品引用，返回 product_id / product_name / error_reply。"""
    if ctx.last_focus_product_id:
        return str(ctx.last_focus_product_id), ctx.last_product_name or text, None

    candidates = _context_product_candidates(ctx)
    ordinal = _parse_order_product_ordinal(text)
    if ordinal is not None:
        if not candidates:
            return None, None, None
        if 1 <= ordinal <= len(candidates):
            target = candidates[ordinal - 1]
            return target["id"], target["name"], None
        return None, None, f"没有找到第 {ordinal} 款商品，请回复列表中的有效序号。"

    if _contains_product_deixis(text):
        last_pid = ctx.last_product_id
        if last_pid:
            return str(last_pid), ctx.last_product_name or text, None
        if len(candidates) == 1:
            target = candidates[0]
            return target["id"], target["name"], None
        if len(candidates) > 1:
            return None, None, "您想购买哪一款？请回复商品序号后再下单。"

    return None, ctx.last_product_name or text, None


class OrderHandler(BaseHandler):
    """订单查询/操作 Handler。

    只读场景（list / filter / detail / shipping_status）走 OrderReferenceResolver + OrderSkill。
    写操作（create / cancel）走 LangGraph 子图 + graph PendingState。
    """

    def __init__(
        self,
        resolver: OrderReferenceResolver | None = None,
        skill: object = None,
        create_guard: OrderCreateGuard | None = None,
        start_lock: OrderCreateStartLock | None = None,
    ) -> None:
        self._resolver = resolver
        self._skill = skill  # None = lazy import real module on first _call_skill
        self._create_guard = create_guard or OrderCreateGuard()
        self._start_lock = start_lock or order_create_start_lock

    async def execute(
        self,
        decision: ScenarioDecision,
        context: object,
    ) -> HandlerResult:
        """处理订单场景。"""
        ctx: SessionContext = context  # type: ignore[assignment]
        scenario = decision.scenario_id
        text = decision.entities.get("raw_text", "")
        if not text:
            text = getattr(ctx, "last_user_message", "") or ""

        self._init_trace_context(scenario)

        if scenario == "order.list":
            result = await self._handle_list(text, ctx)
        elif scenario == "order.filter":
            result = await self._handle_filter(text, ctx)
        elif scenario == "order.detail":
            result = await self._handle_detail(text, ctx)
        elif scenario == "order.shipping_status":
            result = await self._handle_shipping_status(text, ctx)
        elif scenario == "order.create":
            result = await self._handle_create(text, ctx)
        elif scenario == "order.cancel":
            result = await self._handle_cancel(text, ctx)
        elif scenario == "order.refund":
            result = await self._handle_refund(text, ctx)
        else:
            logger.info("订单操作未实现: scenario=%s", scenario)
            result = HandlerResult(
                scenario_id=scenario,
                reply="该订单操作功能正在开发中，请稍后再试。",
                pending_directive=PendingDirective.CLEAR,
            )

        self._merge_trace_context(result)
        return result

    async def resume(
        self,
        pending: object,
        message: str,
        context: object,
    ) -> HandlerResult:
        """恢复 Pending 流程。

        graph pending → 恢复对应 LangGraph 子图。
        """
        ps: PendingState = pending  # type: ignore[assignment]
        ctx: SessionContext = context  # type: ignore[assignment]

        if ps.scenario_id == "order.create":
            if self._create_guard.looks_like_new_order_start(message):
                return HandlerResult(
                    scenario_id=ps.scenario_id,
                    reply=OrderReplyBuilder.order_create_pending_exists(),
                    pending_directive=PendingDirective.KEEP,
                )
            return await self._resume_create_graph(ps, message, ctx)
        if ps.scenario_id == "order.cancel":
            return await self._resume_cancel_graph(ps, message, ctx)
        if ps.scenario_id == "order.refund":
            return await self._resume_refund_graph(ps, message, ctx)

        return HandlerResult(
            scenario_id=ps.scenario_id,
            reply="订单功能开发中，请稍后再试。",
            pending_directive=PendingDirective.CLEAR,
        )

    # ── 下单图 ──

    async def _handle_create(
        self,
        text: str,
        ctx: SessionContext,
    ) -> HandlerResult:
        """下单入口：创建图线程并首次调用。

        优先使用会话焦点商品（用户刚看过详情后下单），
        无焦点商品时尝试从文本解析。
        """
        if not text.strip():
            return HandlerResult(
                scenario_id="order.create",
                reply="请描述您要购买的商品。",
                pending_directive=PendingDirective.CLEAR,
            )

        if not await self._start_lock.acquire(ctx, text):
            return HandlerResult(
                scenario_id="order.create",
                reply=OrderReplyBuilder.order_create_start_in_progress(),
                pending_directive=PendingDirective.CLEAR,
            )

        # 从会话上下文取焦点商品
        product_id, product_name, error_reply = _resolve_create_product_from_context(text, ctx)
        if error_reply:
            return HandlerResult(
                scenario_id="order.create",
                reply=error_reply,
                pending_directive=PendingDirective.CLEAR,
            )
        product_name = product_name or text

        from app.ai.graphs.order_creation import get_creation_graph

        graph = await get_creation_graph()
        graph_thread_id = str(uuid.uuid4())

        initial_state: dict[str, Any] = {
            "tenant_id": ctx.tenant_id,
            "conversation_id": ctx.conversation_id,
            "contact_id": ctx.contact_id,
            "input_text": text,
            "selected_product_id": product_id,
            "product_name": product_name,
            "quantity": 1,
        }

        config = {
            "configurable": {
                "thread_id": graph_thread_id,
            },
        }

        return await self._run_graph(
            scenario_id="order.create",
            graph=graph,
            initial_state=initial_state,
            config=config,
            graph_thread_id=graph_thread_id,
        )

    async def _resume_create_graph(
        self,
        pending: PendingState,
        message: str,
        ctx: SessionContext,
    ) -> HandlerResult:
        """恢复下单图。"""
        from app.ai.graphs.order_creation import get_creation_graph

        graph = await get_creation_graph()
        graph_thread_id = pending.graph_thread_id or ""
        config = {"configurable": {"thread_id": graph_thread_id}}

        return await self._run_graph(
            scenario_id="order.create",
            graph=graph,
            initial_state=None,
            config=config,
            graph_thread_id=graph_thread_id,
            resume_message=message,
        )

    # ── 取消订单图 ──

    async def _handle_cancel(
        self,
        text: str,
        ctx: SessionContext,
    ) -> HandlerResult:
        """取消订单入口：创建图线程并首次调用。"""
        if not text.strip():
            return HandlerResult(
                scenario_id="order.cancel",
                reply="请提供要取消的订单号。",
                pending_directive=PendingDirective.CLEAR,
            )

        from app.ai.graphs.order_cancel import get_cancel_graph

        graph = await get_cancel_graph()
        graph_thread_id = str(uuid.uuid4())

        initial_state: dict[str, Any] = {
            "tenant_id": ctx.tenant_id,
            "conversation_id": ctx.conversation_id,
            "contact_id": ctx.contact_id,
            "input_text": text,
        }

        config = {"configurable": {"thread_id": graph_thread_id}}

        return await self._run_graph(
            scenario_id="order.cancel",
            graph=graph,
            initial_state=initial_state,
            config=config,
            graph_thread_id=graph_thread_id,
        )

    async def _resume_cancel_graph(
        self,
        pending: PendingState,
        message: str,
        ctx: SessionContext,
    ) -> HandlerResult:
        """恢复取消订单图。"""
        from app.ai.graphs.order_cancel import get_cancel_graph

        graph = await get_cancel_graph()
        graph_thread_id = pending.graph_thread_id or ""
        config = {"configurable": {"thread_id": graph_thread_id}}

        return await self._run_graph(
            scenario_id="order.cancel",
            graph=graph,
            initial_state=None,
            config=config,
            graph_thread_id=graph_thread_id,
            resume_message=message,
        )

    # ── 售后/退款图 ──

    async def _handle_refund(
        self,
        text: str,
        ctx: SessionContext,
    ) -> HandlerResult:
        """售后入口：创建图线程并首次调用。"""
        if not text.strip():
            return HandlerResult(
                scenario_id="order.refund",
                reply="请描述您要申请售后的问题。",
                pending_directive=PendingDirective.CLEAR,
            )

        from app.ai.graphs.order_refund import get_refund_graph

        graph = await get_refund_graph()
        graph_thread_id = str(uuid.uuid4())

        initial_state: dict[str, Any] = {
            "tenant_id": ctx.tenant_id,
            "conversation_id": ctx.conversation_id,
            "contact_id": ctx.contact_id,
            "input_text": text,
        }

        config = {"configurable": {"thread_id": graph_thread_id}}

        return await self._run_graph(
            scenario_id="order.refund",
            graph=graph,
            initial_state=initial_state,
            config=config,
            graph_thread_id=graph_thread_id,
        )

    async def _resume_refund_graph(
        self,
        pending: PendingState,
        message: str,
        ctx: SessionContext,
    ) -> HandlerResult:
        """恢复售后图。"""
        from app.ai.graphs.order_refund import get_refund_graph

        graph = await get_refund_graph()
        graph_thread_id = pending.graph_thread_id or ""
        config = {"configurable": {"thread_id": graph_thread_id}}

        return await self._run_graph(
            scenario_id="order.refund",
            graph=graph,
            initial_state=None,
            config=config,
            graph_thread_id=graph_thread_id,
            resume_message=message,
        )

    # ── 通用图运行器 ──

    async def _run_graph(
        self,
        *,
        scenario_id: str,
        graph: Any,
        initial_state: dict[str, Any] | None,
        config: dict[str, Any],
        graph_thread_id: str,
        resume_message: str | None = None,
    ) -> HandlerResult:
        """运行 LangGraph 子图并处理中断/完成。

        如果图中断（需要用户输入）→ 返回 SET graph PendingState。
        如果图完成 → 返回 CLEAR 并附带回复。
        """
        # 尝试注入 DB session（测试模式不连接真实 DB）
        db = None
        if not settings.FASTAGENT_TEST_MODE:
            try:
                from app.integrations.database import AsyncSessionLocal

                db = AsyncSessionLocal()
            except Exception:
                logger.warning("创建 DB 会话失败，降级为无 DB 模式")

        try:
            async with observe_span(
                f"langgraph.{scenario_id}.run",
                input_data=graph_run_input_summary(
                    scenario_id=scenario_id,
                    graph_thread_id=graph_thread_id,
                    initial_state=initial_state,
                    resume_message=resume_message,
                ),
                scenario_id=scenario_id,
                graph_thread_id=graph_thread_id,
                resume=resume_message is not None,
            ) as observation:
                # 恢复调用时检查图是否已完成（防御：重复 resume）
                if resume_message is not None:
                    state_result = await graph.aget_state(config)
                    if not state_result.next:
                        reply = {
                            "order.create": "订单已提交，请勿重复操作。",
                            "order.cancel": "该订单已处理，请勿重复操作。",
                            "order.refund": "该售后申请已处理，请勿重复操作。",
                        }.get(scenario_id, "操作已完成，请勿重复操作。")
                        set_observation_io(
                            observation,
                            output_data={
                                "status": "already_completed",
                                **graph_run_output_summary({}, state_result),
                            },
                            metadata={
                                "status": "already_completed",
                                **graph_snapshot_metadata(state_result),
                            },
                        )
                        return HandlerResult(
                            scenario_id=scenario_id,
                            reply=reply,
                            pending_directive=PendingDirective.CLEAR,
                        )

                # 注入 skill 供图节点使用（测试时可注入 FakeOrderSkill）
                if self._skill is not None:
                    config["configurable"]["order_skill"] = self._skill

                if db is not None:
                    async with db as session:
                        config["configurable"]["db"] = session
                        result = await self._invoke_graph(
                            graph, initial_state, config, resume_message,
                        )
                else:
                    config["configurable"]["db"] = None
                    result = await self._invoke_graph(
                        graph, initial_state, config, resume_message,
                    )

                current = await graph.aget_state(config)
                set_observation_io(
                    observation,
                    output_data={
                        "status": "completed",
                        **graph_run_output_summary(result, current),
                    },
                    metadata={
                        "status": "completed",
                        **graph_snapshot_metadata(current),
                    },
                )
        except Exception as exc:
            logger.warning("图执行异常: scenario=%s error=%s", scenario_id, exc)
            return HandlerResult(
                scenario_id=scenario_id,
                reply="操作执行异常，请稍后再试。",
                pending_directive=PendingDirective.CLEAR,
            )

        # 检查是否中断
        if current.next:
            # 图中断 → 设置 LangGraph PendingState
            interrupt_value = ""
            if current.interrupts:
                interrupt_value = current.interrupts[0].value or ""

            pending_state = PendingState(
                scenario_id=scenario_id,
                step=",".join(current.next),
                graph_thread_id=graph_thread_id,
                interrupt_id=str(current.interrupts[0].id) if current.interrupts else None,
            )

            return HandlerResult(
                scenario_id=scenario_id,
                reply=interrupt_value or "请继续操作。",
                pending_directive=PendingDirective.SET,
                pending_state=pending_state,
            )

        # 图完成
        reply = result.get("reply", "") if isinstance(result, dict) else ""
        if not reply:
            reply = "操作已完成。"

        return HandlerResult(
            scenario_id=scenario_id,
            reply=reply,
            pending_directive=PendingDirective.CLEAR,
        )

    @staticmethod
    async def _invoke_graph(
        graph: Any,
        initial_state: dict[str, Any] | None,
        config: dict[str, Any],
        resume_message: str | None,
    ) -> dict[str, Any]:
        """首次调用或恢复调用图。"""
        if resume_message is not None:
            from langgraph.types import Command

            return await graph.ainvoke(Command(resume=resume_message), config=config)  # type: ignore[arg-type]
        return await graph.ainvoke(initial_state, config=config)  # type: ignore[arg-type]

    # ── 只读场景 ──

    async def _handle_list(
        self,
        text: str,
        ctx: SessionContext,
    ) -> HandlerResult:
        """订单列表。"""
        result = await self._resolve(text, ctx)
        _ = result

        if ctx.contact_id is None:
            return HandlerResult(
                scenario_id="order.list",
                reply="请先确认客户身份后查询订单。",
                pending_directive=PendingDirective.CLEAR,
            )

        orders_data = await self._call_skill(
            "manage_order",
            tenant_id=ctx.tenant_id,
            contact_id=ctx.contact_id,
        )
        if not orders_data.ok:
            return HandlerResult(
                scenario_id="order.list",
                reply="暂时无法查询订单信息，请稍后再试。",
                pending_directive=PendingDirective.CLEAR,
            )

        payload = orders_data.result
        orders: list[dict[str, Any]] = payload.get("orders", [])
        count = int(payload.get("count", 0))

        # 无订单且用户未提供订单号 → 追问订单号
        if not orders and not _extract_order_number(text):
            return HandlerResult(
                scenario_id="order.list",
                reply="请提供订单号以便查询。",
                pending_directive=PendingDirective.CLEAR,
            )

        reply = OrderReplyBuilder.order_list(orders, count)

        return HandlerResult(
            scenario_id="order.list",
            reply=reply,
            pending_directive=PendingDirective.CLEAR,
            context_update={
                "recent_orders": _summarize_orders(orders),
                "last_intent": "order.list",
            },
        )

    async def _handle_filter(
        self,
        text: str,
        ctx: SessionContext,
    ) -> HandlerResult:
        """订单筛选。"""
        result = await self._resolve(text, ctx)

        if ctx.contact_id is None:
            return HandlerResult(
                scenario_id="order.filter",
                reply="请先确认客户身份后查询订单。",
                pending_directive=PendingDirective.CLEAR,
            )

        skill_kwargs: dict[str, Any] = {
            "tenant_id": ctx.tenant_id,
            "contact_id": ctx.contact_id,
            "filter_time_ref": result.time_ref,
        }
        if result.statuses:
            skill_kwargs["filter_statuses"] = result.statuses
        if result.status:
            skill_kwargs["status"] = result.status

        orders_data = await self._call_skill("manage_order", **skill_kwargs)
        if not orders_data.ok:
            return HandlerResult(
                scenario_id="order.filter",
                reply="暂时无法查询订单信息，请稍后再试。",
                pending_directive=PendingDirective.CLEAR,
            )

        payload = orders_data.result
        filtered: list[dict[str, Any]] = payload.get("orders", [])
        count = int(payload.get("count", 0))

        if not filtered:
            # 无匹配订单且用户未提供订单号 → 追问订单号
            if not _extract_order_number(text):
                return HandlerResult(
                    scenario_id="order.filter",
                    reply="请提供订单号以便查询。",
                    pending_directive=PendingDirective.CLEAR,
                    context_update={"last_intent": "order.filter"},
                )
            return HandlerResult(
                scenario_id="order.filter",
                reply="暂无符合条件的订单。",
                pending_directive=PendingDirective.CLEAR,
                context_update={"last_intent": "order.filter"},
            )

        reply = OrderReplyBuilder.order_list(filtered, count)
        return HandlerResult(
            scenario_id="order.filter",
            reply=reply,
            pending_directive=PendingDirective.CLEAR,
            context_update={
                "recent_orders": _summarize_orders(filtered),
                "last_intent": "order.filter",
            },
        )

    async def _handle_detail(
        self,
        text: str,
        ctx: SessionContext,
    ) -> HandlerResult:
        """订单详情。"""
        if ctx.contact_id is None:
            return HandlerResult(
                scenario_id="order.detail",
                reply="请先确认客户身份后查询订单。",
                pending_directive=PendingDirective.CLEAR,
            )

        result = await self._resolve(text, ctx)
        order_id = _get_order_id(result, ctx)

        if order_id is None:
            return await self._fallback_to_list(ctx, "order.detail")

        orders_data = await self._call_skill(
            "manage_order",
            tenant_id=ctx.tenant_id,
            contact_id=ctx.contact_id,
            order_id=order_id,
        )
        if not orders_data.ok or not orders_data.result:
            return HandlerResult(
                scenario_id="order.detail",
                reply=f"未找到订单 #{order_id}。",
                pending_directive=PendingDirective.CLEAR,
            )

        order = orders_data.result
        reply = OrderReplyBuilder.order_detail(order)
        return HandlerResult(
            scenario_id="order.detail",
            reply=reply,
            pending_directive=PendingDirective.CLEAR,
            context_update={
                "active_order_id": str(order_id),
                "last_intent": "order.detail",
            },
        )

    async def _handle_shipping_status(
        self,
        text: str,
        ctx: SessionContext,
    ) -> HandlerResult:
        """物流/发货状态查询。"""
        if ctx.contact_id is None:
            return HandlerResult(
                scenario_id="order.shipping_status",
                reply="请先确认客户身份后查询订单。",
                pending_directive=PendingDirective.CLEAR,
            )

        result = await self._resolve(text, ctx)
        order_id = _get_order_id(result, ctx)

        if order_id is None:
            return await self._fallback_to_list(ctx, "order.shipping_status")

        orders_data = await self._call_skill(
            "manage_order",
            tenant_id=ctx.tenant_id,
            contact_id=ctx.contact_id,
            order_id=order_id,
        )
        if not orders_data.ok or not orders_data.result:
            return HandlerResult(
                scenario_id="order.shipping_status",
                reply=f"未找到订单 #{order_id}。",
                pending_directive=PendingDirective.CLEAR,
            )

        order = orders_data.result
        reply = OrderReplyBuilder.shipping_status(order)
        return HandlerResult(
            scenario_id="order.shipping_status",
            reply=reply,
            pending_directive=PendingDirective.CLEAR,
            context_update={
                "active_order_id": str(order_id),
                "last_intent": "order.shipping_status",
            },
        )

    # ── 内部方法 ──

    async def _resolve(self, text: str, ctx: SessionContext) -> OrderReferenceResult:
        resolver = self._get_resolver()
        return await resolver.resolve(
            text=text,
            contact_id=ctx.contact_id or 0,
            context=ctx,
        )

    def _get_resolver(self) -> OrderReferenceResolver:
        if self._resolver is not None:
            return self._resolver
        return OrderReferenceResolver()

    async def _fallback_to_list(
        self,
        ctx: SessionContext,
        scenario_id: str,
    ) -> HandlerResult:
        """未解析到具体订单时回落为列表。"""
        if ctx.contact_id is None:
            return HandlerResult(
                scenario_id=scenario_id,
                reply="请提供订单号或确认客户身份后查询。",
                pending_directive=PendingDirective.CLEAR,
            )

        orders_data = await self._call_skill(
            "manage_order",
            tenant_id=ctx.tenant_id,
            contact_id=ctx.contact_id,
        )
        if not orders_data.ok:
            return HandlerResult(
                scenario_id=scenario_id,
                reply="请提供订单号或从下方选择订单。",
                pending_directive=PendingDirective.CLEAR,
            )

        payload = orders_data.result
        orders: list[dict[str, Any]] = payload.get("orders", [])
        count = int(payload.get("count", 0))

        if not orders:
            return HandlerResult(
                scenario_id=scenario_id,
                reply="请提供订单号以便查询。",
                pending_directive=PendingDirective.CLEAR,
            )

        reply = (
            "请提供订单号或从下方选择订单：\n\n"
            f"{OrderReplyBuilder.order_list(orders, count)}"
        )
        return HandlerResult(
            scenario_id=scenario_id,
            reply=reply,
            pending_directive=PendingDirective.CLEAR,
            context_update={
                "recent_orders": _summarize_orders(orders),
                "last_intent": scenario_id,
            },
        )

    async def _call_skill(
        self,
        method: str,
        **kwargs: Any,
    ) -> ToolResult:
        """调用 Skill 方法（通过 SkillGateway 自动记录 trace + 管理 DB session）。"""
        if self._skill is None:
            import app.ai.skills.orders as _real_skill
            self._skill = _real_skill
        try:
            return await call_skill(self._skill, method, **kwargs)
        except SkillError:
            logger.warning("Skill 调用失败: method=%s", method)
            return call_skill_failed(method)


# ── 工具函数 ──


def _summarize_orders(orders: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "id": o.get("order_id", str(index)),
            "status": o.get("status", ""),
            "status_label": o.get("status_label", o.get("status", "")),
            "payable_amount": o.get("payable_amount", 0),
        }
        for index, o in enumerate(orders)
    ]


def _get_order_id(
    result: OrderReferenceResult,
    ctx: SessionContext,
) -> int | None:
    if result.resolved and result.order_id is not None:
        return result.order_id
    if result.reference_type == "active" and ctx.active_order_id:
        return int(ctx.active_order_id)
    return None


def _filter_orders(
    orders: list[dict[str, Any]],
    *,
    statuses: list[str] | None = None,
    single_status: str | None = None,
    time_ref: str | None = None,
) -> list[dict[str, Any]]:
    result = list(orders)
    if statuses:
        status_set = set(statuses)
        result = [o for o in result if o.get("status") in status_set]
    elif single_status:
        result = [o for o in result if o.get("status") == single_status]
    if time_ref:
        result = _filter_by_time(result, time_ref)
    return result


def _filter_by_time(
    orders: list[dict[str, Any]],
    time_ref: str,
) -> list[dict[str, Any]]:
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    if time_ref == "today":
        return [o for o in orders if _parse_order_time(o) >= today_start]
    if time_ref == "yesterday":
        yesterday_start = today_start - timedelta(days=1)
        return [
            o for o in orders
            if yesterday_start <= _parse_order_time(o) < today_start
        ]
    if time_ref == "this_month":
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        return [o for o in orders if _parse_order_time(o) >= month_start]
    if time_ref == "recent":
        week_ago = today_start - timedelta(days=7)
        return [o for o in orders if _parse_order_time(o) >= week_ago]
    return orders


def _parse_order_time(order: dict[str, Any]) -> datetime:
    raw = order.get("created_at")
    if raw:
        try:
            if isinstance(raw, str):
                return datetime.fromisoformat(raw)
            if isinstance(raw, datetime):
                return raw
        except (ValueError, TypeError):
            logger.debug("日期解析失败: raw=%s", raw[:100] if isinstance(raw, str) else raw)
    return datetime.min.replace(tzinfo=timezone.utc)
