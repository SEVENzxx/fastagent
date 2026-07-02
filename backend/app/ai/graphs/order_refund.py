"""OrderRefundGraph — 订单售后 LangGraph 子图。

流程：
  resolve_order → validate_refundable → collect_reason → confirm_refund → execute_refund → build_result

中断点：
  - 订单多候选 → interrupt 让用户选择
  - 退款原因 → interrupt 让用户填写
  - 退款确认 → interrupt 等用户确认

写入约束（P1）：
  - SQLite 持久化 checkpointer（非 MemorySaver），重启后图状态可恢复
  - Redis 持久化幂等 key，跨 worker/重启有效
  - execute_refund 前必须从 IdempotencyService 查重
  - validate_refundable_node 查 DB 校验订单归属 + 可售后状态
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Any, Optional

from langchain_core.runnables import RunnableConfig

from app.ai.graphs.common import (
    CONFIRM_OR_CANCEL_PROMPT,
    INVALID_CHOICE_REPLY,
    graph_exception,
    graph_failed,
)
from app.ai.graphs.observability import observe_graph_node
from app.config import settings
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt
from typing_extensions import TypedDict

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════
# 持久化 Checkpointer
# ══════════════════════════════════════════════

_CHECKPOINTER_DIR = Path(__file__).resolve().parents[3] / "data" / "checkpoints"
_CHECKPOINTER = None
_GRAPH_INSTANCE = None


async def _get_checkpointer() -> Any:
    """返回持久化 SQLite checkpointer（测试时可用 MemorySaver 替换）。"""
    global _CHECKPOINTER
    if _CHECKPOINTER is not None:
        return _CHECKPOINTER

    if settings.FASTAGENT_TEST_MODE:
        _CHECKPOINTER = MemorySaver()
        return _CHECKPOINTER

    import aiosqlite

    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    _CHECKPOINTER_DIR.mkdir(parents=True, exist_ok=True)
    db_path = _CHECKPOINTER_DIR / "order_refund.db"
    conn = await aiosqlite.connect(str(db_path))
    _CHECKPOINTER = AsyncSqliteSaver(conn)
    return _CHECKPOINTER


async def close_checkpointer() -> None:
    """关闭 SQLite checkpointer 连接并清理全局单例。"""
    global _CHECKPOINTER, _GRAPH_INSTANCE
    if _CHECKPOINTER is not None and not settings.FASTAGENT_TEST_MODE:
        try:
            if hasattr(_CHECKPOINTER, "conn"):
                await _CHECKPOINTER.conn.close()
        except Exception:
            logger.warning("关闭售后 checkpointer 连接失败")
    _CHECKPOINTER = None
    _GRAPH_INSTANCE = None


# ══════════════════════════════════════════════
# State
# ══════════════════════════════════════════════


class OrderRefundState(TypedDict, total=False):
    """订单售后子图状态。"""

    # ── 入参 ──
    tenant_id: int
    conversation_id: int
    contact_id: int | None
    input_text: str

    # ── 订单解析 ──
    resolved_orders: list[dict[str, Any]]
    selected_order_id: str | None
    selected_order_status: str | None

    # ── 校验 ──
    refundable: bool
    refund_not_allowed_reason: str | None

    # ── 原因收集 ──
    refund_reason: str | None

    # ── 确认 ──
    confirmed: bool

    # ── 执行结果 ──
    order_id: str | None
    reply: str
    error: str | None

    # ── 幂等 ──
    idempotency_key: str | None
    write_executed: bool


# ══════════════════════════════════════════════
# Idempotency
# ══════════════════════════════════════════════

_IDEMPOTENCY_SALT = "order_refund_v1"


def _build_idempotency_key(
    tenant_id: int,
    conversation_id: int,
    contact_id: int | None,
    graph_thread_id: str,
    order_id: str,
) -> str:
    """生成稳定的幂等 key。"""
    raw = "|".join([
        _IDEMPOTENCY_SALT,
        str(tenant_id),
        str(conversation_id),
        str(contact_id or ""),
        graph_thread_id,
        order_id,
    ])
    return hashlib.sha256(raw.encode()).hexdigest()


# ══════════════════════════════════════════════
# 可售后状态列表
# ══════════════════════════════════════════════

_REFUNDABLE_STATUSES: frozenset[str] = frozenset({
    "shipped",
    "signed",
})


# ══════════════════════════════════════════════
# 节点
# ══════════════════════════════════════════════


async def resolve_order_node(
    state: OrderRefundState,
    config: Optional[RunnableConfig] = None,
) -> dict[str, Any]:
    """解析订单引用。

    从 input_text 中提取订单号。如通过上下文能确定订单则直接选中。
    多候选时 interrupt 让用户选择。
    """
    _ = config
    text = state.get("input_text", "")
    resolved_orders = state.get("resolved_orders", [])

    # 恢复调用且已有候选列表
    if resolved_orders:
        choice = interrupt(
            "请选择要申请售后的订单编号：\n"
            + _format_order_choices(resolved_orders)
            + "\n\n输入订单编号选择，输入「取消」放弃售后申请。"
        )
        choice_stripped = choice.strip().lower()
        if choice_stripped in ("取消", "不退了", "算了", "不要了", "no", "n"):
            return {"error": "用户取消售后申请", "reply": "已取消售后申请，订单保持不变。如需其他帮助请随时告诉我。"}

        try:
            idx = int(choice_stripped) - 1
            if 0 <= idx < len(resolved_orders):
                order = resolved_orders[idx]
                return {
                    "selected_order_id": order.get("order_id") or order.get("id", ""),
                    "selected_order_status": order.get("status", ""),
                }
        except (ValueError, IndexError):
            logger.debug("售后：用户序号选择无效")
        return {"error": INVALID_CHOICE_REPLY, "reply": "请输入有效的订单编号，或输入「取消」放弃售后申请。"}

    # 首次调用：从文本提取订单号
    from app.ai.skills.orders import _extract_order_id as extract_id

    order_id = extract_id(text)

    if order_id is not None:
        thread_id = config.get("configurable", {}).get("thread_id", "") if config else ""
        key = _build_idempotency_key(
            tenant_id=state.get("tenant_id", 0),
            conversation_id=state.get("conversation_id", 0),
            contact_id=state.get("contact_id"),
            graph_thread_id=thread_id,
            order_id=str(order_id),
        )
        return {
            "selected_order_id": str(order_id),
            "selected_order_status": None,
            "idempotency_key": key,
        }

    return {
        "error": "缺少订单号",
        "reply": "请提供要申请售后的订单号。",
    }


async def validate_refundable_node(
    state: OrderRefundState,
    config: Optional[RunnableConfig] = None,
) -> dict[str, Any]:
    """校验订单是否可发起售后 + 订单归属。"""
    order_id = state.get("selected_order_id", "")
    if not order_id:
        return {
            "refundable": False,
            "refund_not_allowed_reason": "缺少订单号。",
            "reply": "请提供要申请售后的订单号。",
        }

    db = config.get("configurable", {}).get("db") if config else None

    if db is not None:
        from app.services import order_service

        tenant_id = state.get("tenant_id", 0)
        contact_id = state.get("contact_id")

        if contact_id is None:
            return {
                "refundable": False,
                "refund_not_allowed_reason": "无法确认客户身份。",
                "reply": "请先确认客户身份后再申请售后。",
            }

        order = await order_service.get_order(db, int(order_id), tenant_id)
        if order is None:
            return {
                "refundable": False,
                "refund_not_allowed_reason": f"未找到订单 #{order_id}。",
                "reply": f"未找到订单 #{order_id}，请核对订单号。",
            }

        # 所有权校验：订单必须属于当前客户
        if order.contact_id != contact_id:
            logger.warning(
                "售后归属校验失败: order=%s tenant=%s order_contact=%s req_contact=%s",
                order_id,
                tenant_id,
                order.contact_id,
                contact_id,
            )
            return {
                "refundable": False,
                "refund_not_allowed_reason": "该订单不属于当前客户。",
                "reply": "未找到该客户的此订单，请核对订单号。",
            }

        status = order.status
        real_order_id = str(order.id)
        if status in _REFUNDABLE_STATUSES:
            return {
                "refundable": True,
                "refund_not_allowed_reason": None,
                "selected_order_id": real_order_id,
                "selected_order_status": status,
            }
        return {
            "refundable": False,
            "refund_not_allowed_reason": f"订单当前状态不支持售后（{status}）。",
            "reply": "该订单当前状态不支持申请售后。如需帮助请联系人工客服。",
            "selected_order_id": real_order_id,
            "selected_order_status": status,
        }

    # 无 DB（测试）: 按已知状态判断
    status = state.get("selected_order_status")
    if status is None:
        return {"refundable": True, "refund_not_allowed_reason": None}

    if status in _REFUNDABLE_STATUSES:
        return {"refundable": True, "refund_not_allowed_reason": None}

    return {
        "refundable": False,
        "refund_not_allowed_reason": f"订单当前状态不支持售后（{status}）。",
        "reply": "该订单当前状态不支持申请售后。如需帮助请联系人工客服。",
    }


async def collect_reason_node(
    state: OrderRefundState,
    config: Optional[RunnableConfig] = None,
) -> dict[str, Any]:
    """收集退款/售后原因。"""
    _ = config
    if state.get("refund_reason"):
        return {}

    reason = interrupt(
        "请告知退款或售后原因，例如：商品质量问题、发错货等。\n输入「取消」放弃售后申请。"
    )
    reason_stripped = reason.strip() if reason else ""
    if reason_stripped.lower() in ("取消", "不退了", "算了", "不要了", "no", "n"):
        return {
            "confirmed": False,
            "error": "用户取消售后申请",
            "reply": "已取消售后申请，订单保持不变。如需其他帮助请随时告诉我。",
        }
    if reason_stripped:
        return {"refund_reason": reason_stripped, "error": None}

    return {
        "error": "缺少退款原因",
        "reply": "请提供退款或售后原因，或输入「取消」放弃售后申请。",
    }


async def confirm_refund_node(
    state: OrderRefundState,
    config: Optional[RunnableConfig] = None,
) -> dict[str, Any]:
    """展示退款信息，等待用户确认。"""
    _ = config
    order_id = state.get("selected_order_id", "")
    reason = state.get("refund_reason", "")

    choice = interrupt(
        f"请确认售后申请：\n"
        f"  订单 #{order_id}\n"
        f"  原因：{reason}\n\n"
        "输入「确认」提交售后申请，输入「取消」放弃操作。"
    )
    choice_stripped = choice.strip().lower()

    if choice_stripped in ("确认", "确认退款", "确认售后", "是", "yes", "y", "确定"):
        return {"confirmed": True, "error": None}

    if choice_stripped in ("取消", "不退了", "算了", "不要了", "no", "n"):
        return {
            "confirmed": False,
            "reply": "已取消售后申请，订单保持不变。如需其他帮助请随时告诉我。",
        }

    return {
        "confirmed": False,
        "reply": CONFIRM_OR_CANCEL_PROMPT,
        "error": "确认输入无效",
    }


async def execute_refund_node(
    state: OrderRefundState,
    config: Optional[RunnableConfig] = None,
) -> dict[str, Any]:
    """执行售后退款（原子幂等控制：setnx 占位 → 执行 → set 完成）。

    优先使用 config["configurable"]["order_skill"]（测试注入），
    未注入时回退到 import app.ai.skills.orders。
    """
    if state.get("write_executed"):
        return {}

    from app.ai.services.idempotency import order_idempotency

    idempotency_key = state.get("idempotency_key") or ""

    # 原子幂等检查：setnx 占位，成功则当前请求获得执行权
    if idempotency_key:
        claimed = await order_idempotency.setnx(idempotency_key, {"status": "processing"})
        if not claimed:
            prev = await order_idempotency.get(idempotency_key)
            if prev and prev.get("status") == "completed":
                logger.info("幂等命中，跳过售后: key=%s", idempotency_key[:16])
                return {
                    "order_id": prev.get("order_id"),
                    "reply": prev.get("reply", "售后申请已提交（重复请求，跳过执行）。"),
                    "write_executed": True,
                }
            return {
                "error": "操作正在处理中",
                "reply": "售后申请正在处理中，请稍候。",
                "write_executed": True,
            }

    tenant_id = state.get("tenant_id", 0)
    contact_id = state.get("contact_id")
    order_id = state.get("selected_order_id", "")
    refund_reason = state.get("refund_reason", "")

    # 优先使用注入的 skill
    order_skill = config.get("configurable", {}).get("order_skill") if config else None
    db = config.get("configurable", {}).get("db") if config else None

    try:
        if order_skill is not None:
            result = await order_skill.create_refund(
                tenant_id=tenant_id,
                contact_id=contact_id,
                db=db,
                order_id=order_id,
                reason=refund_reason,
            )
            if not result.ok:
                logger.warning("售后失败(注入skill): tenant=%s order=%s error=%s", tenant_id, order_id, result.error)
                return graph_failed("售后申请", idempotency_key, result.error)
            payload = result.result or {}
        elif db is None:
            # 无 DB（测试环境无 skill 注入）→ 模拟
            reply = f"订单 #{order_id} 售后申请已提交（模拟）。原因：{refund_reason}"
            if idempotency_key:
                await order_idempotency.set(idempotency_key, {"status": "completed", "order_id": order_id, "reply": reply})
            return {"order_id": order_id, "reply": reply, "write_executed": True}
        else:
            # 真实执行
            from app.ai.skills.orders import create_refund

            result = await create_refund(
                tenant_id=tenant_id,
                contact_id=contact_id,
                db=db,
                order_id=order_id,
                reason=refund_reason,
            )
            if not result.ok:
                logger.warning("售后失败: tenant=%s order=%s error=%s", tenant_id, order_id, result.error)
                return graph_failed("售后申请", idempotency_key, result.error)
            payload = result.result or {}
            await db.commit()

        message = payload.get("message", f"订单 #{order_id} 售后申请已提交。")
        if idempotency_key:
            await order_idempotency.set(idempotency_key, {"status": "completed", "order_id": order_id, "reply": message})
        return {"order_id": order_id, "reply": message, "write_executed": True}

    except Exception as exc:
        logger.error("售后异常: tenant=%s order=%s error=%s", tenant_id, order_id, exc)
        return graph_exception(exc, idempotency_key)



async def build_result_node(
    state: OrderRefundState,
    config: Optional[RunnableConfig] = None,
) -> dict[str, Any]:
    """最终结果整理。"""
    _ = config
    if state.get("error") and not state.get("reply"):
        reason = state.get("refund_not_allowed_reason") or state["error"]
        return {"reply": f"售后申请失败：{reason}"}
    return {}


# ══════════════════════════════════════════════
# 辅助函数
# ══════════════════════════════════════════════


def _format_order_choices(orders: list[dict[str, Any]]) -> str:
    """格式化订单候选列表供用户选择。"""
    lines: list[str] = []
    for idx, order in enumerate(orders, start=1):
        oid = order.get("order_id") or order.get("id", "?")
        status = order.get("status_label") or order.get("status", "")
        lines.append(f"{idx}. 订单 #{oid}（{status}）")
    return "\n".join(lines)


# ══════════════════════════════════════════════
# 条件路由
# ══════════════════════════════════════════════


def _route_resolve_order(state: OrderRefundState) -> str:
    # error + 未选中订单 → 当前节点的错误
    if state.get("error") and not state.get("selected_order_id"):
        if state.get("confirmed") is False:
            return "build_result"
        if state.get("resolved_orders"):
            return "resolve_order"
        return "build_result"
    return "validate_refundable"


def _route_validate_refundable(state: OrderRefundState) -> str:
    if state.get("error"):
        return "build_result"
    if not state.get("refundable"):
        return "build_result"
    return "collect_reason"


def _route_collect_reason(state: OrderRefundState) -> str:
    if state.get("error"):
        if state.get("confirmed") is False:
            return "build_result"
        if not state.get("refund_reason"):
            return "collect_reason"
        return "build_result"
    return "confirm_refund"


def _route_confirm_refund(state: OrderRefundState) -> str:
    # error + 未确认 → 当前节点的无效输入
    if state.get("error") and not state.get("confirmed"):
        return "confirm_refund"
    if not state.get("confirmed"):
        return "build_result"
    return "execute_refund"


def _route_execute_refund(state: OrderRefundState) -> str:
    return "build_result"


# ══════════════════════════════════════════════
# Graph 构造
# ══════════════════════════════════════════════


def build_order_refund_graph(checkpointer: Any | None = None) -> StateGraph:
    """构造 OrderRefund 子图。

    Args:
        checkpointer: 覆盖默认 checkpointer。不传时使用 MemorySaver（测试兼容）。
    """
    builder = StateGraph(OrderRefundState)

    builder.add_node("resolve_order", observe_graph_node("order.refund", "resolve_order", resolve_order_node))
    builder.add_node("validate_refundable",observe_graph_node("order.refund", "validate_refundable", validate_refundable_node))
    builder.add_node("collect_reason", observe_graph_node("order.refund", "collect_reason", collect_reason_node))
    builder.add_node("confirm_refund", observe_graph_node("order.refund", "confirm_refund", confirm_refund_node))
    builder.add_node("execute_refund", observe_graph_node("order.refund", "execute_refund", execute_refund_node))
    builder.add_node("build_result", observe_graph_node("order.refund", "build_result", build_result_node))

    builder.add_edge(START, "resolve_order")
    builder.add_conditional_edges("resolve_order", _route_resolve_order)
    builder.add_conditional_edges("validate_refundable", _route_validate_refundable)
    builder.add_conditional_edges("collect_reason", _route_collect_reason)
    builder.add_conditional_edges("confirm_refund", _route_confirm_refund)
    builder.add_conditional_edges("execute_refund", _route_execute_refund)
    builder.add_edge("build_result", END)

    return builder.compile(checkpointer=checkpointer or MemorySaver())


async def get_refund_graph() -> StateGraph:
    """返回模块级单例（延迟 async 构造，保证 checkpointer 正确初始化）。"""
    global _GRAPH_INSTANCE
    if _GRAPH_INSTANCE is not None:
        return _GRAPH_INSTANCE  # type: ignore[return-value]
    cp = await _get_checkpointer()
    _GRAPH_INSTANCE = build_order_refund_graph(checkpointer=cp)
    return _GRAPH_INSTANCE  # type: ignore[return-value]

