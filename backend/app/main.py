import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.common.trace.middleware import TraceIdMiddleware
from app.config import settings
from app.logging_config import setup_logging

setup_logging()

logger = logging.getLogger(__name__)

from app.api.v1.auth import router as auth_router
from app.api.v1.admin import router as admin_router
from app.api.v1.categories import router as categories_router
from app.api.v1.contacts import router as contacts_router
from app.api.v1.conversations import router as conversations_router
from app.api.v1.employees import router as employees_router
from app.api.v1.images import router as images_router
from app.api.v1.knowledge import router as knowledge_router
from app.api.v1.marketing import router as marketing_router
from app.api.v1.orders import router as orders_router
from app.api.v1.operations import router as operations_router
from app.api.v1.permissions import router as permissions_router
from app.api.v1.platforms import router as platforms_router
from app.api.v1.products import router as products_router
from app.api.v1.qa_pairs import router as qa_pairs_router
from app.api.v1.rag import router as rag_router
from app.api.v1.sales_intelligence import router as sales_intelligence_router
from app.api.v1.roles import router as roles_router
from app.api.v1.tenant_settings import router as tenant_settings_router
from app.api.v1.webhooks import router as webhooks_router
from app.api.v1.usage import router as usage_router
from app.api.v1.intent_samples import router as intent_samples_router
from app.api.v1.ws import router as ws_router
from app.integrations.database import check_db_connection
from app.integrations.redis_client import check_redis_connection
import uvicorn


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动后台用量日志 flush worker，关闭时取消。"""
    from app.services.usage_service import start_usage_flush_worker
    await start_usage_flush_worker()
    yield
    # 应用关闭时清理模块级 Redis 连接
    from app.ai.context.session_store import close_cached_redis_client
    await close_cached_redis_client()
    from app.ai.context.pending_service import close_cached_pending_redis_client
    await close_cached_pending_redis_client()
    # 关闭 graph SQLite checkpointer 连接
    from app.ai.graphs import close_order_graph_checkpointers
    await close_order_graph_checkpointers()


app = FastAPI(
    title=settings.APP_NAME,
    debug=settings.APP_DEBUG,
    lifespan=lifespan,
)

# ── 跨域配置 ─────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── 请求日志中间件 ──────────────────────────────────────────────────────
@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.time()
    response = await call_next(request)
    elapsed = (time.time() - start) * 1000  # ms

    # 跳过 WebSocket 升级和健康检查
    if request.url.path == "/health" or request.scope.get("type") == "websocket":
        return response

    logger.info("%s %s → %s (%.0fms)", request.method, request.url.path, response.status_code, elapsed)
    return response


# ── trace_id 中间件（最外层：在 log_requests 之前设置 trace_id）─────────────
app.add_middleware(TraceIdMiddleware)


# ── 路由注册 ─────────────────────────────────────────────────────────────
app.include_router(auth_router, prefix="/api/v1")
app.include_router(admin_router, prefix="/api/v1")
app.include_router(categories_router, prefix="/api/v1")
app.include_router(contacts_router, prefix="/api/v1")
app.include_router(conversations_router, prefix="/api/v1")
app.include_router(permissions_router, prefix="/api/v1")
app.include_router(platforms_router, prefix="/api/v1")
app.include_router(products_router, prefix="/api/v1")
app.include_router(orders_router, prefix="/api/v1")
app.include_router(operations_router, prefix="/api/v1")
app.include_router(roles_router, prefix="/api/v1")
app.include_router(knowledge_router, prefix="/api/v1")
app.include_router(qa_pairs_router, prefix="/api/v1")
app.include_router(marketing_router, prefix="/api/v1")
app.include_router(images_router, prefix="/api/v1")
app.include_router(rag_router, prefix="/api/v1")
app.include_router(sales_intelligence_router, prefix="/api/v1")
app.include_router(employees_router, prefix="/api/v1")
app.include_router(webhooks_router, prefix="/api/v1")
app.include_router(usage_router, prefix="/api/v1")
app.include_router(tenant_settings_router, prefix="/api/v1")
app.include_router(intent_samples_router, prefix="/api/v1")
app.include_router(ws_router)

# Internal / debug API — 仅在 development/test 环境注册
if settings.APP_ENV in ("development", "test"):
    from app.api.v1.internal.harness import router as harness_router
    from app.api.v1.internal.web_test import router as web_test_router
    app.include_router(harness_router, prefix="/api/v1")
    app.include_router(web_test_router, prefix="/api/v1")
    logger.info("Internal API（Harness/WebTest）已注册（APP_ENV=%s）", settings.APP_ENV)

# ── 健康检查 ─────────────────────────────────────────────────────────────
@app.get("/health")
async def health():
    db_ok = await check_db_connection()
    redis_ok = await check_redis_connection()

    return {
        "status": "ok" if (db_ok and redis_ok) else "degraded",
        "db": "connected" if db_ok else "disconnected",
        "redis": "connected" if redis_ok else "disconnected",
    }

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        access_log=False,  # 关闭 uvicorn 自带的 access log，改用自定义中间件
        log_config=None,  # 避免 uvicorn 二次覆盖应用日志配置
    )
