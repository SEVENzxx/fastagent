import logging
import time

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings

for handler in logging.root.handlers[:]:
    logging.root.removeHandler(handler)

logging.basicConfig(
    level=logging.DEBUG if settings.APP_DEBUG else logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s | %(message)s",
)

logger = logging.getLogger(__name__)

from app.api.v1.auth import router as auth_router
from app.api.v1.ai_stream import router as ai_stream_router
from app.api.v1.categories import router as categories_router
from app.api.v1.contacts import router as contacts_router
from app.api.v1.conversations import router as conversations_router
from app.api.v1.employees import router as employees_router
from app.api.v1.permissions import router as permissions_router
from app.api.v1.platforms import router as platforms_router
from app.api.v1.products import router as products_router
from app.api.v1.roles import router as roles_router
from app.api.v1.webhooks import router as webhooks_router
from app.api.v1.ws import router as ws_router
from app.database import check_db_connection
from app.redis_client import check_redis_connection
import uvicorn

app = FastAPI(
    title=settings.APP_NAME,
    debug=settings.APP_DEBUG,
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


# ── 路由注册 ─────────────────────────────────────────────────────────────
app.include_router(auth_router, prefix="/api/v1")
app.include_router(ai_stream_router, prefix="/api/v1")
app.include_router(categories_router, prefix="/api/v1")
app.include_router(contacts_router, prefix="/api/v1")
app.include_router(conversations_router, prefix="/api/v1")
app.include_router(permissions_router, prefix="/api/v1")
app.include_router(platforms_router, prefix="/api/v1")
app.include_router(products_router, prefix="/api/v1")
app.include_router(roles_router, prefix="/api/v1")
app.include_router(employees_router, prefix="/api/v1")
app.include_router(webhooks_router, prefix="/api/v1")
app.include_router(ws_router)

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
    )
