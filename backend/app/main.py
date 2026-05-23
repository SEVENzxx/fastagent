from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.auth import router as auth_router
from app.api.v1.categories import router as categories_router
from app.api.v1.contacts import router as contacts_router
from app.api.v1.conversations import router as conversations_router
from app.api.v1.employees import router as employees_router
from app.api.v1.permissions import router as permissions_router
from app.api.v1.products import router as products_router
from app.api.v1.roles import router as roles_router
from app.api.v1.ws import router as ws_router
from app.config import settings
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


# ── 路由注册 ─────────────────────────────────────────────────────────────
app.include_router(auth_router, prefix="/api/v1")
app.include_router(categories_router, prefix="/api/v1")
app.include_router(contacts_router, prefix="/api/v1")
app.include_router(conversations_router, prefix="/api/v1")
app.include_router(permissions_router, prefix="/api/v1")
app.include_router(products_router, prefix="/api/v1")
app.include_router(roles_router, prefix="/api/v1")
app.include_router(employees_router, prefix="/api/v1")
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
        reload=True,  # 开发模式自动重载
    )
