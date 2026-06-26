"""OrderCreationGraph — 下单 LangGraph 子图（完整生命周期）。

流程：
  resolve_product → confirm_product → collect_missing_info → show_summary
  → execute_create → simulate_payment → wait_agent_approval
  → arrange_shipping → notify_customer → build_result

中断点：
  - 商品不明确 → resolved_products + interrupt 让用户选择
  - 产品确认 → interrupt 展示商品+价格，让用户确认/修改数量
  - 信息收集 → interrupt 灵活收集地址/电话（可一次性提供）
  - 汇总确认 → interrupt 展示完整订单摘要，等待最终确认
  - 坐席审批（可选）→ interrupt 等待坐席手动审批（auto_approve=False 时）

写入约束（P1）：
  - SQLite 持久化 checkpointer（非 MemorySaver），重启后图状态可恢复
  - Redis 持久化幂等 key（非内存 dict），跨 worker/重启有效
  - execute_create 前必须从 IdempotencyService 查重，相同 key 只执行一次写操作
  - simulate_payment / arrange_shipping 各自独立幂等

Skilling：
  - execute_create 优先使用 config["configurable"]["order_skill"]（测试注入）
  - 未注入时回退到直接 import app.ai.skills.orders
"""

from __future__ import annotations

import hashlib
import logging
import re
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
    """下单子图状态 — 完整生命周期。"""

    # ── 入参 ──
    tenant_id: int
    conversation_id: int
    contact_id: int | None
    input_text: str

    # ── 商品解析 ──
    resolved_products: list[dict[str, Any]]
    selected_product_id: str | None
    product_name: str | None
    product_price: float | None
    quantity: int

    # ── 产品确认 ──
    product_confirmed: bool

    # ── 信息收集 ──
    collected_slots: list[str]
    shipping_address: str | None
    receiver_name: str | None
    receiver_phone: str | None

    # ── 汇总确认 ──
    total_amount: float | None
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


async def _lookup_product_price(
    db: Any,
    tenant_id: int,
    product_id: str,
) -> float | None:
    """通过 product_id 查询商品单价。"""
    from sqlalchemy import select

    from app.models.product import Product

    try:
        pid = int(product_id)
    except (ValueError, TypeError):
        return None
    stmt = select(Product.price).where(Product.id == pid, Product.tenant_id == tenant_id)
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()
    return float(row) if row is not None else None


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

    # 已确定商品 — 若缺少价格信息则尝试补充
    if selected_product_id and product_name:
        if state.get("product_price") is None:
            db = config.get("configurable", {}).get("db") if config else None
            if db is not None:
                price = await _lookup_product_price(db, int(state["tenant_id"]), selected_product_id)
                if price is not None:
                    return {"product_price": price}
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
                    "product_price": p.get("price"),
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
                "product_price": products[0].get("price"),
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


async def confirm_product_node(
    state: OrderCreationState,
    config: Optional[RunnableConfig] = None,
) -> dict[str, Any]:
    """展示商品信息，让用户确认产品与数量。

    中断并等待用户确认/修改数量/取消。
    """
    _ = config
    product_name = state.get("product_name", "?")
    price = state.get("product_price")
    quantity = state.get("quantity", 1)

    price_line = f"  ¥{price:.2f}" if price is not None else ""
    lines = [
        f"您要购买的是：",
        f"  商品：{product_name}{price_line}",
        f"  数量：{quantity}",
        "",
        "请确认是否购买该商品，或输入数量（如「2个」）修改购买数量。",
        "输入「确认」继续，输入「取消」放弃下单。",
    ]

    choice = interrupt("\n".join(lines))
    choice_stripped = choice.strip().lower()

    # 取消
    if choice_stripped in ("取消", "算了", "不要了", "不买了"):
        return {
            "product_confirmed": False,
            "confirmed": False,
            "reply": "已取消下单。如需其他帮助，请随时告诉我。",
        }

    # 确认
    if choice_stripped in ("确认", "确认购买", "是", "确定", "yes", "y"):
        return {"product_confirmed": True}

    # 修改数量：解析数字
    qty_match = re.search(r"(\d+)", choice_stripped)
    if qty_match:
        new_qty = max(int(qty_match.group(1)), 1)
        return {"product_confirmed": True, "quantity": new_qty}

    # 无效输入 → 重试（不走 error，让 routing 循环回本节点）
    return {"reply": "请回复「确认」购买，或输入数量（如「2个」），或「取消」放弃。"}


async def collect_missing_info_node(
    state: OrderCreationState,
    config: Optional[RunnableConfig] = None,
) -> dict[str, Any]:
    """灵活收集缺失的订单信息（地址/电话）。

    支持一次性提供多项信息，或逐项补充。
    """
    _ = config
    shipping_address = state.get("shipping_address")
    receiver_phone = state.get("receiver_phone")
    collected = set(state.get("collected_slots") or [])

    if shipping_address:
        collected.add("shipping_address")
    if receiver_phone:
        collected.add("receiver_phone")

    if collected >= {"shipping_address", "receiver_phone"}:
        return {"collected_slots": list(collected)}

    # 构建缺失项提示
    missing_labels = []
    if "shipping_address" not in collected:
        missing_labels.append("收货地址")
    if "receiver_phone" not in collected:
        missing_labels.append("联系电话")

    prompt = (
        f"请补充以下信息：{'、'.join(missing_labels)}（可一次性提供）。"
        if len(missing_labels) > 1
        else f"请提供{missing_labels[0]}。"
    )

    reply = interrupt(prompt)
    reply_stripped = reply.strip()
    if not reply_stripped:
        return {"reply": "请提供所需信息，或输入「取消」放弃下单。"}

    # 取消
    if reply_stripped.lower() in ("取消", "算了", "不要了", "不买了"):
        return {"confirmed": False, "reply": "已取消下单。"}

    # 解析电话
    phone_match = re.search(r"1[3-9]\d{9}", reply_stripped)
    if phone_match and "receiver_phone" not in collected:
        receiver_phone = phone_match.group()
        collected.add("receiver_phone")

    # 解析地址
    for sep in ("地址：", "地址:", "收货地址：", "收货地址:"):
        if sep in reply_stripped:
            parts = reply_stripped.split(sep, 1)
            if parts[1].strip():
                shipping_address = parts[1].strip()
                collected.add("shipping_address")
                break
    else:
        # 无显式地址标记时，去掉已解析的电话后剩余的长文本作为地址
        if "shipping_address" not in collected and not any(
            kw in reply_stripped for kw in ("电话", "手机", "联系")
        ):
            remaining = re.sub(r"1[3-9]\d{9}", "", reply_stripped).strip()
            if len(remaining) >= 4:
                shipping_address = remaining
                collected.add("shipping_address")

    updates: dict[str, Any] = {"collected_slots": list(collected)}
    if shipping_address is not None:
        updates["shipping_address"] = shipping_address
    if receiver_phone is not None:
        updates["receiver_phone"] = receiver_phone

    # 若仍有未收集的项，循环回去继续 interrupt
    if collected < {"shipping_address", "receiver_phone"}:
        updates["reply"] = "还有信息需要补充，请继续提供。"

    return updates


async def show_summary_node(
    state: OrderCreationState,
    config: Optional[RunnableConfig] = None,
) -> dict[str, Any]:
    """展示完整订单摘要，等待用户最终确认。"""
    _ = config
    product_name = state.get("product_name", "?")
    price = state.get("product_price")
    quantity = state.get("quantity", 1)
    address = state.get("shipping_address", "")
    phone = state.get("receiver_phone", "")

    total = (price or 0) * quantity

    lines = [
        "请确认订单信息：",
        f"  商品：{product_name} × {quantity}",
    ]
    if price is not None:
        lines.append(f"  单价：¥{price:.2f}")
        lines.append(f"  总价：¥{total:.2f}")
    if address:
        lines.append(f"  收货地址：{address}")
    if phone:
        lines.append(f"  联系电话：{phone}")
    lines.append("")
    lines.append("输入「确认」提交订单，输入「取消」放弃下单。")

    choice = interrupt("\n".join(lines))
    choice_stripped = choice.strip().lower()

    if choice_stripped in ("确认", "确认下单", "是", "yes", "y", "确定"):
        return {"confirmed": True, "total_amount": total, "reply": ""}

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


async def simulate_payment_node(
    state: OrderCreationState,
    config: Optional[RunnableConfig] = None,
) -> dict[str, Any]:
    """模拟支付 — pending_customer_confirm → paid。"""
    _ = config
    order_id = state.get("order_id")
    if state.get("write_executed") or not order_id:
        return {}

    from app.ai.services.idempotency import order_idempotency

    idempotency_key = f"payment_{order_id}"
    claimed = await order_idempotency.setnx(idempotency_key, {"status": "processing"})
    if not claimed:
        prev = await order_idempotency.get(idempotency_key)
        if prev and prev.get("status") == "completed":
            return {}
        return {"error": "支付正在处理中", "write_executed": True}

    db = config.get("configurable", {}).get("db") if config else None
    order_skill = config.get("configurable", {}).get("order_skill") if config else None

    try:
        if order_skill is not None:
            result = await order_skill.simulate_payment(
                tenant_id=state.get("tenant_id", 0),
                contact_id=state.get("contact_id"),
                db=db,
                order_id=order_id,
            )
        else:
            from app.ai.skills.orders import simulate_payment

            result = await simulate_payment(
                tenant_id=state.get("tenant_id", 0),
                contact_id=state.get("contact_id"),
                db=db,
                order_id=order_id,
            )
            if db is not None:
                await db.commit()

        if not result.ok:
            logger.warning("模拟支付失败: %s", result.error)
            await order_idempotency.delete(idempotency_key)
            return graph_failed("模拟支付", idempotency_key, result.error)

        await order_idempotency.set(idempotency_key, {"status": "completed"})
        logger.info("模拟支付成功: order_id=%s", order_id)
        return {"write_executed": True}

    except Exception as exc:
        logger.error("模拟支付异常: %s", exc)
        await order_idempotency.delete(idempotency_key)
        return graph_exception(exc, idempotency_key)


async def wait_agent_approval_node(
    state: OrderCreationState,
    config: Optional[RunnableConfig] = None,
) -> dict[str, Any]:
    """坐席审批节点。

    auto_approve=True（默认）→ 自动审批通过。
    auto_approve=False → 中断等待坐席手动审批（预留接口）。
    """
    order_id = state.get("order_id")
    if not order_id:
        return {}

    auto_approve = True
    if config and "configurable" in config:
        auto_approve = config["configurable"].get("auto_approve", True)

    if auto_approve:
        db = config.get("configurable", {}).get("db") if config else None
        order_skill = config.get("configurable", {}).get("order_skill") if config else None

        try:
            if order_skill is not None:
                result = await order_skill.agent_approve(
                    tenant_id=state.get("tenant_id", 0),
                    contact_id=state.get("contact_id"),
                    db=db,
                    order_id=order_id,
                )
            else:
                from app.ai.skills.orders import agent_approve

                result = await agent_approve(
                    tenant_id=state.get("tenant_id", 0),
                    contact_id=state.get("contact_id"),
                    db=db,
                    order_id=order_id,
                )
                if db is not None:
                    await db.commit()

            if not result.ok:
                logger.warning("自动审批失败: %s", result.error)
                return graph_failed("坐席审批", "", result.error)

            logger.info("自动审批通过: order_id=%s", order_id)
            return {}

        except Exception as exc:
            logger.error("自动审批异常: %s", exc)
            return graph_exception(exc)

    # 非自动审批 → 中断预留（等待坐席通过 admin API 恢复线程）
    interrupt(
        f"订单 #{order_id} 需要坐席审批。请等待客服人员审核确认。"
    )
    return {}


async def arrange_shipping_node(
    state: OrderCreationState,
    config: Optional[RunnableConfig] = None,
) -> dict[str, Any]:
    """安排发货 — agent_confirmed → shipped。"""
    order_id = state.get("order_id")
    if not order_id:
        return {}

    from app.ai.services.idempotency import order_idempotency

    idempotency_key = f"shipping_{order_id}"
    claimed = await order_idempotency.setnx(idempotency_key, {"status": "processing"})
    if not claimed:
        prev = await order_idempotency.get(idempotency_key)
        if prev and prev.get("status") == "completed":
            return {}
        return {"error": "发货正在处理中", "write_executed": True}

    db = config.get("configurable", {}).get("db") if config else None
    order_skill = config.get("configurable", {}).get("order_skill") if config else None

    try:
        if order_skill is not None:
            result = await order_skill.arrange_shipping(
                tenant_id=state.get("tenant_id", 0),
                contact_id=state.get("contact_id"),
                db=db,
                order_id=order_id,
            )
        else:
            from app.ai.skills.orders import arrange_shipping

            result = await arrange_shipping(
                tenant_id=state.get("tenant_id", 0),
                contact_id=state.get("contact_id"),
                db=db,
                order_id=order_id,
            )
            if db is not None:
                await db.commit()

        if not result.ok:
            logger.warning("安排发货失败: %s", result.error)
            await order_idempotency.delete(idempotency_key)
            return graph_failed("安排发货", idempotency_key, result.error)

        await order_idempotency.set(idempotency_key, {"status": "completed"})
        logger.info("安排发货成功: order_id=%s", order_id)
        return {"write_executed": True}

    except Exception as exc:
        logger.error("安排发货异常: %s", exc)
        await order_idempotency.delete(idempotency_key)
        return graph_exception(exc, idempotency_key)


async def notify_customer_node(
    state: OrderCreationState,
    config: Optional[RunnableConfig] = None,
) -> dict[str, Any]:
    """推送已发货通知。"""
    _ = config
    order_id = state.get("order_id", "")
    product_name = state.get("product_name", "")
    quantity = state.get("quantity", 1)

    if state.get("notified"):
        return {}

    reply = (
        f"您的订单 #{order_id} 已发货，请注意查收。\n"
        f"商品：{product_name} × {quantity}"
    )

    return {"reply": reply, "notified": True}


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
    if state.get("resolved_products") and not state.get("selected_product_id"):
        return "resolve_product"
    return "confirm_product"


def _route_confirm_product(state: OrderCreationState) -> str:
    if state.get("error"):
        return "build_result"
    if state.get("confirmed") is False:
        return "build_result"
    if not state.get("product_confirmed"):
        return "confirm_product"
    return "collect_missing_info"


def _route_collect_missing_info(state: OrderCreationState) -> str:
    if state.get("error"):
        return "build_result"
    if state.get("confirmed") is False:
        return "build_result"
    collected = set(state.get("collected_slots") or [])
    if collected >= {"shipping_address", "receiver_phone"}:
        return "show_summary"
    # 还有未收集项但不一定已中断过 → 依靠节点内部 interrupt
    return "collect_missing_info"


def _route_show_summary(state: OrderCreationState) -> str:
    if state.get("error"):
        return "build_result"
    if not state.get("confirmed"):
        return "build_result"
    return "execute_create"


def _route_execute_create(state: OrderCreationState) -> str:
    if state.get("error"):
        return "build_result"
    return "simulate_payment"


def _route_simulate_payment(state: OrderCreationState) -> str:
    if state.get("error"):
        return "build_result"
    return "wait_agent_approval"


def _route_wait_agent_approval(state: OrderCreationState) -> str:
    if state.get("error"):
        return "build_result"
    return "arrange_shipping"


def _route_arrange_shipping(state: OrderCreationState) -> str:
    if state.get("error"):
        return "build_result"
    return "notify_customer"


def _route_notify_customer(state: OrderCreationState) -> str:
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
    builder.add_node("confirm_product", confirm_product_node)
    builder.add_node("collect_missing_info", collect_missing_info_node)
    builder.add_node("show_summary", show_summary_node)
    builder.add_node("execute_create", execute_create_node)
    builder.add_node("simulate_payment", simulate_payment_node)
    builder.add_node("wait_agent_approval", wait_agent_approval_node)
    builder.add_node("arrange_shipping", arrange_shipping_node)
    builder.add_node("notify_customer", notify_customer_node)
    builder.add_node("build_result", build_result_node)

    builder.add_edge(START, "resolve_product")
    builder.add_conditional_edges("resolve_product", _route_resolve_product)
    builder.add_conditional_edges("confirm_product", _route_confirm_product)
    builder.add_conditional_edges("collect_missing_info", _route_collect_missing_info)
    builder.add_conditional_edges("show_summary", _route_show_summary)
    builder.add_conditional_edges("execute_create", _route_execute_create)
    builder.add_conditional_edges("simulate_payment", _route_simulate_payment)
    builder.add_conditional_edges("wait_agent_approval", _route_wait_agent_approval)
    builder.add_conditional_edges("arrange_shipping", _route_arrange_shipping)
    builder.add_conditional_edges("notify_customer", _route_notify_customer)
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
