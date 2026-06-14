from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy import event, text

from app.config import settings
from app.ai.observability import begin_sql_observation, end_sql_observation

engine = create_async_engine(
    settings.DATABASE_URL,
    pool_size=20,
    max_overflow=10,
)


@event.listens_for(engine.sync_engine, "before_cursor_execute")
def _before_cursor_execute(conn, cursor, statement, parameters, context, executemany) -> None:
    context._fastagent_observation = begin_sql_observation(statement)


@event.listens_for(engine.sync_engine, "after_cursor_execute")
def _after_cursor_execute(conn, cursor, statement, parameters, context, executemany) -> None:
    end_sql_observation(
        getattr(context, "_fastagent_observation", None),
        rowcount=getattr(cursor, "rowcount", None),
    )


@event.listens_for(engine.sync_engine, "handle_error")
def _handle_cursor_error(exception_context) -> None:
    execution_context = getattr(exception_context, "execution_context", None)
    end_sql_observation(
        getattr(execution_context, "_fastagent_observation", None),
        error=exception_context.original_exception,
    )

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db() -> AsyncSession:  # type: ignore[misc]
    """FastAPI 依赖注入：提供异步数据库会话。"""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


async def check_db_connection() -> bool:
    """通过执行 SELECT 1 检测数据库是否连通。"""
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
