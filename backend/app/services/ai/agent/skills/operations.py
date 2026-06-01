"""运营类技能。"""

from __future__ import annotations

import logging

from app.services.ai.agent.types import ToolResult

logger = logging.getLogger(__name__)


async def update_price_strategy(
    *,
    tenant_id: int,
    contact_id: int | None = None,
    **kwargs,
) -> ToolResult:
    """执行三级报价判断：原价、折扣价、低于底价待审批。"""
    db = kwargs.get("db")
    quoted_price = kwargs.get("quoted_price")
    if db is None or contact_id is None or quoted_price is None:
        return ToolResult(ok=False, skill_name="update_price_strategy", error="缺少客户、数据库会话或报价金额。")
    from app.services import sales_intelligence_service as service
    try:
        result = await service.update_price_strategy(
            db,
            tenant_id,
            contact_id,
            product_id=kwargs.get("product_id"),
            product_name=kwargs.get("product_name"),
            quoted_price=float(quoted_price),
        )
    except (TypeError, ValueError) as exc:
        return ToolResult(ok=False, skill_name="update_price_strategy", error=str(exc))
    message = (
        f"{result['product_name']} 的报价为 ¥{result['quoted_price']:.2f}。"
        + ("该价格低于底价，已转人工审批。" if result["requires_approval"] else "报价策略已记录。")
    )
    return ToolResult(
        ok=True,
        skill_name="update_price_strategy",
        result={**result, "message": message},
    )


async def list_documents(
    *,
    tenant_id: int,
    contact_id: int | None = None,
    **kwargs,
) -> ToolResult:
    """通过统一 Qdrant 层检索营销资料。"""
    _ = contact_id
    query = str(kwargs.get("query") or kwargs.get("keyword") or "").strip()
    db = kwargs.get("db")
    if not query or db is None:
        logger.info("list_documents missing query or db: tenant_id=%s has_db=%s", tenant_id, db is not None)
        return ToolResult(
            ok=True,
            skill_name="list_documents",
            result={"documents": [], "message": "请提供要检索的营销资料主题。"},
        )

    from app.services.marketing_service import MarketingService

    docs = await MarketingService().search_docs(db, tenant_id, query, top_k=5, is_active=True)
    items = [
        {
            "id": str(doc.id),
            "title": doc.title,
            "file_url": doc.file_url,
            "file_type": doc.file_type,
            "question_associations": doc.question_associations or [],
            "qdrant_point_id": doc.qdrant_point_id,
        }
        for doc in docs
    ]
    return ToolResult(ok=True, skill_name="list_documents", result={"documents": items, "count": len(items)})


async def manage_todos(
    *,
    tenant_id: int,
    contact_id: int | None = None,
    **kwargs,
) -> ToolResult:
    """查询、创建或完成会话待办。"""
    db = kwargs.get("db")
    if db is None:
        return ToolResult(ok=False, skill_name="manage_todos", error="缺少数据库会话。")
    from app.schemas.sales_intelligence import TodoCreate, TodoUpdate
    from app.services import sales_intelligence_service as service

    action = str(kwargs.get("action") or "list").lower()
    conversation_id = kwargs.get("conversation_id")
    if action == "create":
        if conversation_id is None or not str(kwargs.get("content") or "").strip():
            return ToolResult(ok=False, skill_name="manage_todos", error="创建待办需要会话 ID 和待办内容。")
        item = await service.create_todo(
            db,
            tenant_id,
            TodoCreate(
                conversation_id=int(conversation_id),
                content=str(kwargs["content"]),
                due_at=kwargs.get("due_at"),
                created_by_type="ai",
            ),
        )
        return ToolResult(ok=True, skill_name="manage_todos", result={"todo_id": str(item.id), "message": "待办已创建。"})
    if action in {"done", "cancel"}:
        todo_id = kwargs.get("todo_id")
        if todo_id is None:
            return ToolResult(ok=False, skill_name="manage_todos", error="请提供待办 ID。")
        item = await service.update_todo(
            db,
            tenant_id,
            int(todo_id),
            TodoUpdate(status="done" if action == "done" else "cancelled"),
        )
        if item is None:
            return ToolResult(ok=False, skill_name="manage_todos", error="待办不存在。")
        return ToolResult(ok=True, skill_name="manage_todos", result={"todo_id": str(item.id), "status": item.status, "message": "待办状态已更新。"})
    items = await service.list_todos(db, tenant_id, conversation_id=int(conversation_id) if conversation_id else None, contact_id=contact_id)
    return ToolResult(
        ok=True,
        skill_name="manage_todos",
        result={
            "todos": [{"id": str(item.id), "content": item.content, "status": item.status} for item in items],
            "count": len(items),
        },
    )
