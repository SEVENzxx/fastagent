"""RAG 命中测试 API — Phase 11"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import require_tenant_user
from app.models.employee import Employee
from app.services.rag_service import RAGService

router = APIRouter(prefix="/rag", tags=["RAG命中测试"])

_rag_service = RAGService()


class HitTestRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=1000)
    top_k: int = Field(5, ge=1, le=20)


class HitTestResponse(BaseModel):
    query: str
    chunks: list[dict]
    qa_matches: list[dict]


@router.post("/hit-test", response_model=HitTestResponse)
async def hit_test(
    body: HitTestRequest,
    current_user: Employee = Depends(require_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    """RAG 命中测试：输入查询 → 返回匹配的 chunks + QA pairs"""
    result = await _rag_service.search(body.query, current_user.tenant_id, db)
    return HitTestResponse(
        query=body.query,
        chunks=result["chunks"],
        qa_matches=result["qa_matches"],
    )
