"""OrderCreationGraph — 下单 LangGraph 子图。

流程：
  resolve_product  →  collect_shipping  →  confirm_order  →  execute_create  →  build_result

中断点：
  - 商品不明确 → resolved_products + interrupt 让用户选择
  - 收货地址缺失 → interrupt 让用户补充
  - 下单确认 → interrupt 等用户确认

写入约束（P1）：
  - SQLite 持久化 checkpointer（非 MemorySaver），重启后图状态可恢复
  - Redis 持久化幂等 key（非内存 dict），跨 worker/重启有效
  - execute_create 前必须从 IdempotencyService 查重，相同 key 只执行一次写操作
  - resolve_product_node 从 DB 查询真实商品，拒绝整句文本当下单商品名

Skilling：
  - execute_create 优先使用 config["configurable"]["order_skill"]（测试注入）
  - 未注入时回退到直接 import app.ai.skills.orders
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
    """返回持久化 SQLite checkpointer（测试时可用 MemorySaver 替换）。

    AsyncSqliteSaver.from_conn_string() 返回 context manager，
    这里直接用 aiosqlite.connect() + AsyncSqliteSaver(conn) 获取实例。
    """
    global _CHECKPOINTER
    if _CHECKPOINTER is not None:
        return _CHECKPOINTER

    if settings.FASTAGENT_TEST_MODE:
        _CHECKPOINTER = MemorySaver()
        return _CHECKPOINTER

    import aiosqlite

    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    _CHECKPOINTER_DIR.mkdir(parents=True, exist_ok=True)
    db_path = _CHECKPOINTER_DIR / "order_creation.db"
    conn = await aiosqlite.connect(str(db_path))
    _CHECKPOINTER = AsyncSqliteSaver(conn)
    return _CHECKPOINTER


def _set_checkpointer(cp: Any) -> None:
    """覆盖 checkpointer（测试用）。"""
    global _CHECKPOINTER
    _CHECKPOINTER = cp


async def close_checkpointer() -> None:
    """关闭 SQLite checkpointer 连接并清理全局单例。"""
    global _CHECKPOINTER, _GRAPH_INSTANCE
    if _CHECKPOINTER is not None and not settings.FASTAGENT_TEST_MODE:
        try:
            if hasattr(_CHECKPOINTER, "conn"):
                await _CHECKPOINTER.conn.close()
        except Exception:
            logger.warning("关闭下单 checkpointer 连接失败")
    _CHECKPOINTER = None
    _GRAPH_INSTANCE = None


# ══════════════════════════════════════════════
# State
# ══════════════════════════════════════════════


class OrderCreationState(TypedDict, total=False):
    """下单子图状态。"""

    # ── 入参 ──
    tenant_id: int
    conversation_id: int
    contact_id: int | None
    input_text: str

    # ── 商品解析 ──
    resolved_products: list[dict[str, Any]]  # 多候选商品列表
    selected_product_id: str | None  # 用户选择的商品 ID
    product_name: str | None  # 最终下单商品名
    quantity: int  # 数量（默认 1）

    # ── 收货信息 ──
    shipping_address: str | None

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
# Idempotency 常量
# ══════════════════════════════════════════════

_IDEMPOTENCY_SALT = "order_creation_v1"


def _build_idempotency_key(
    tenant_id: int,
    conversation_id: int,
    contact_id: int | None,
    graph_thread_id: str,
    input_text: str,
    product_name: str,
    quantity: int,
) -> str:
    """生成稳定的幂等 key。"""
    raw = "|".join([
        _IDEMPOTENCY_SALT,
        str(tenant_id),
        str(conversation_id),
        str(contact_id or ""),
        graph_thread_id,
        input_text,
        product_name,
        str(quantity),
    ])
    return hashlib.sha256(raw.encode()).hexdigest()


# ══════════════════════════════════════════════
# 节点
# ══════════════════════════════════════════════


async def _search_products_by_name(
    db: Any,
    tenant_id: int,
    text: str,
) -> list[dict[str, Any]]:
    """从 DB 查询匹配的商品。"""
    from sqlalchemy import select

    from app.models.product import Product

    stmt = (
        select(Product)
        .where(
            Product.tenant_id == tenant_id,
            Product.is_active.is_(True),
            Product.name.ilike(f"%{text.strip()}%"),
        )
        .order_by(Product.name)
    )
    result = await db.execute(stmt)
    products = result.scalars().all()
    return [
        {"id": str(p.id), "name": p.name, "price": float(p.price) if p.price else 0}
        for p in products
    ]


async def resolve_product_node(
    state: OrderCreationState,
    config: Optional[RunnableConfig] = None,
) -> dict[str, Any]:
    """解析商品引用。

    优先从 DB 查询匹配商品：
      - 1 个 → 直接选中
      - 多个 → resolved_products + interrupt 让用户选择
      - 0 个 → error
    无 DB（测试）时回退到整句文本作商品名。
    """
    resolved = state.get("resolved_products", [])
    selected_product_id = state.get("selected_product_id")
    product_name = state.get("product_name")

    # 已确定商品
    if selected_product_id and product_name:
        return {}

    # 有候选 → 中断等用户选择
    if resolved:
        choice = interrupt(
            "请选择要购买的商品：\n"
            + _format_product_choices(resolved)
        )
        try:
            idx = int(choice.strip()) - 1
            if 0 <= idx < len(resolved):
                p = resolved[idx]
                return {
                    "selected_product_id": p.get("id", ""),
                    "product_name": p.get("name", ""),
                    "quantity": 1,
                }
        except (ValueError, IndexError):
            logger.debug("下单：用户序号选择无效")
        return {"error": INVALID_CHOICE_REPLY, "reply": "请输入有效的商品编号。"}

    # 首次调用：尝试 DB 解析
    text = state.get("input_text", "")
    db = config.get("configurable", {}).get("db") if config else None

    if text.strip() and db is not None:
        products = await _search_products_by_name(db, state.get("tenant_id", 0), text)
        if len(products) == 1:
            return {
                "selected_product_id": products[0]["id"],
                "product_name": products[0]["name"],
                "quantity": 1,
            }
        if len(products) > 1:
            return {"resolved_products": products}
        return {
            "error": "未找到匹配商品",
            "reply": "未找到相关商品，请提供要购买的商品名称。",
        }

    # 无 DB（测试环境）：使用整句文本作商品名
    fallback_name = text.strip()
    if not fallback_name:
        return {"error": "缺少商品信息", "reply": "请告知需要购买的商品名称。"}
    return {
        "product_name": fallback_name,
        "selected_product_id": fallback_name,
        "quantity": 1,
    }


async def collect_shipping_node(
    state: OrderCreationState,
    config: Optional[RunnableConfig] = None,
) -> dict[str, Any]:
    """收集收货地址。"""
    _ = config
    if state.get("shipping_address"):
        return {}

    address = interrupt("请提供收货地址。")
    if address and address.strip():
        return {"shipping_address": address.strip()}

    return {
        "error": "缺少收货地址",
        "reply": "下单需要收货地址，请提供您的收货地址。",
    }


async def confirm_order_node(
    state: OrderCreationState,
    config: Optional[RunnableConfig] = None,
) -> dict[str, Any]:
    """展示订单确认信息，等待用户确认。"""
    _ = config
    product_name = state.get("product_name", "")
    quantity = state.get("quantity", 1)
    address = state.get("shipping_address", "")

    summary_parts = [
        "请确认订单信息：",
        f"  商品：{product_name}",
        f"  数量：{quantity}",
    ]
    if address:
        summary_parts.append(f"  收货地址：{address}")
    summary_parts.append("")
    summary_parts.append("输入「确认」提交订单，输入「取消」放弃下单。")

    choice = interrupt("\n".join(summary_parts))
    choice_stripped = choice.strip().lower()

    if choice_stripped in ("确认", "确认下单", "是", "yes", "y", "确定"):
        return {"confirmed": True, "reply": ""}

    if choice_stripped in ("取消", "取消下单", "算了", "不要了", "no", "n"):
        return {
            "confirmed": False,
            "reply": "已取消下单。如需其他帮助，请随时告诉我。",
        }

    return {
        "confirmed": False,
        "reply": CONFIRM_OR_CANCEL_PROMPT,
        "error": "确认输入无效",
    }


async def execute_create_node(
    state: OrderCreationState,
    config: Optional[RunnableConfig] = None,
) -> dict[str, Any]:
    """执行下单（原子幂等控制：setnx 占位 → 执行 → set 完成）。

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
                logger.info("幂等命中，跳过下单: key=%s", idempotency_key[:16])
                return {
                    "order_id": prev.get("order_id"),
                    "reply": prev.get("reply", "订单已创建（重复请求，跳过执行）。"),
                    "write_executed": True,
                }
            return {
                "error": "操作正在处理中",
                "reply": "订单正在处理中，请稍候。",
                "write_executed": True,
            }

    tenant_id = state.get("tenant_id", 0)
    contact_id = state.get("contact_id")
    product_name = state.get("product_name", "")
    quantity = state.get("quantity", 1)
    address = state.get("shipping_address")

    # 优先使用注入的 skill
    order_skill = config.get("configurable", {}).get("order_skill") if config else None
    db = config.get("configurable", {}).get("db") if config else None

    try:
        if order_skill is not None:
            result = await order_skill.create_order_draft(
                tenant_id=tenant_id,
                contact_id=contact_id,
                db=db,
                items=[{"product_name": product_name, "quantity": quantity}],
                shipping_address=address,
            )
            if not result.ok:
                logger.warning("下单失败(注入skill): tenant=%s error=%s", tenant_id, result.error)
                return graph_failed("下单", idempotency_key, result.error)
            payload = result.result or {}
        elif db is None:
            # 无 DB（测试环境无 skill 注入）→ mock
            mock_id = f"mock_{tenant_id}_{contact_id}"
            reply = _mock_create_reply(product_name, quantity, address, mock_id)
            if idempotency_key:
                await order_idempotency.set(idempotency_key, {"status": "completed", "order_id": mock_id, "reply": reply})
            return {"order_id": mock_id, "reply": reply, "write_executed": True}
        else:
            # 真实执行
            from app.ai.skills.orders import create_order_draft

            result = await create_order_draft(
                tenant_id=tenant_id,
                contact_id=contact_id,
                db=db,
                items=[{"product_name": product_name, "quantity": quantity}],
                shipping_address=address,
            )
            if not result.ok:
                logger.warning("下单失败: tenant=%s error=%s", tenant_id, result.error)
                return graph_failed("下单", idempotency_key, result.error)
            payload = result.result or {}
            await db.commit()

        order_id = payload.get("order_id", "")
        message = payload.get("message", f"订单已创建（#{order_id}）。")
        if idempotency_key:
            await order_idempotency.set(idempotency_key, {"status": "completed", "order_id": order_id, "reply": message})
        return {"order_id": order_id, "reply": message, "write_executed": True}

    except Exception as exc:
        logger.error("下单异常: tenant=%s error=%s", tenant_id, exc)
        return graph_exception(exc, idempotency_key)


def _mock_create_reply(product_name: str, quantity: int, address: str | None, order_id: str) -> str:
    reply_parts = ["订单已创建（模拟）：", f"  商品：{product_name} ×{quantity}"]
    if address:
        reply_parts.append(f"  收货地址：{address}")
    reply_parts.append(f"  订单号：#" + order_id)
    return "\n".join(reply_parts)


async def build_result_node(
    state: OrderCreationState,
    config: Optional[RunnableConfig] = None,
) -> dict[str, Any]:
    """最终结果整理。"""
    _ = config
    if state.get("error") and not state.get("reply"):
        return {"reply": f"下单失败：{state['error']}"}
    return {}


# ══════════════════════════════════════════════
# 辅助函数
# ══════════════════════════════════════════════


def _format_product_choices(products: list[dict[str, Any]]) -> str:
    """格式化商品候选列表供用户选择。"""
    lines: list[str] = []
    for idx, p in enumerate(products, start=1):
        name = p.get("name", "?")
        price = p.get("price")
        label = f"{idx}. {name}"
        if price is not None:
            label += f"  ¥{price:.2f}"
        lines.append(label)
    return "\n".join(lines)


# ══════════════════════════════════════════════
# 条件路由
# ══════════════════════════════════════════════


def _route_resolve_product(state: OrderCreationState) -> str:
    if state.get("error"):
        return "build_result"
    # 有候选但未选中 → 循环回自身让 interrupt 触发
    if state.get("resolved_products") and not state.get("selected_product_id"):
        return "resolve_product"
    return "collect_shipping"


def _route_collect_shipping(state: OrderCreationState) -> str:
    if state.get("error"):
        return "build_result"
    return "confirm_order"


def _route_confirm_order(state: OrderCreationState) -> str:
    if state.get("error"):
        return "build_result"
    if not state.get("confirmed"):
        return "build_result"
    return "execute_create"


def _route_execute_create(state: OrderCreationState) -> str:
    return "build_result"


# ══════════════════════════════════════════════
# Graph 构造
# ══════════════════════════════════════════════


def build_order_creation_graph(checkpointer: Any | None = None) -> StateGraph:
    """构造 OrderCreation 子图。

    Args:
        checkpointer: 覆盖默认 checkpointer。不传时使用 MemorySaver（测试兼容）。
    """
    builder = StateGraph(OrderCreationState)

    builder.add_node("resolve_product", resolve_product_node)
    builder.add_node("collect_shipping", collect_shipping_node)
    builder.add_node("confirm_order", confirm_order_node)
    builder.add_node("execute_create", execute_create_node)
    builder.add_node("build_result", build_result_node)

    builder.add_edge(START, "resolve_product")
    builder.add_conditional_edges("resolve_product", _route_resolve_product)
    builder.add_conditional_edges("collect_shipping", _route_collect_shipping)
    builder.add_conditional_edges("confirm_order", _route_confirm_order)
    builder.add_conditional_edges("execute_create", _route_execute_create)
    builder.add_edge("build_result", END)

    return builder.compile(checkpointer=checkpointer or MemorySaver())


async def get_creation_graph() -> StateGraph:
    """返回模块级单例（延迟 async 构造，保证 checkpointer 正确初始化）。"""
    global _GRAPH_INSTANCE
    if _GRAPH_INSTANCE is not None:
        return _GRAPH_INSTANCE  # type: ignore[return-value]
    cp = await _get_checkpointer()
    _GRAPH_INSTANCE = build_order_creation_graph(checkpointer=cp)
    return _GRAPH_INSTANCE  # type: ignore[return-value]


# ── 模块级单例（async lazy）──


async def run_order_creation(
    initial_state: dict[str, Any],
    config: dict[str, Any],
) -> dict[str, Any]:
    """下单子图外部入口。"""
    logger.info(
        "订单创建图开始: tenant=%s conv=%s text=%s",
        initial_state.get("tenant_id"),
        initial_state.get("conversation_id"),
        str(initial_state.get("input_text", ""))[:40],
    )
    graph = await get_creation_graph()
    return await graph.ainvoke(initial_state, config=config)
