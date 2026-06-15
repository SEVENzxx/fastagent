"""知识文档 API — Phase 11"""

from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException, Query, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.database import AsyncSessionLocal, get_db
from app.dependencies import require_permission
from app.models.employee import Employee
from app.models.role import PermissionCode
from app.schemas.knowledge import (
    KnowledgeDocDetailResponse,
    KnowledgeDocListResponse,
    KnowledgeDocResponse,
    KnowledgeChunkResponse,
)
from app.services.knowledge_service import KnowledgeService

router = APIRouter(prefix="/knowledge", tags=["知识库"])

_knowledge_service = KnowledgeService()


async def _process_knowledge_doc_background(doc_id: int, tenant_id: int) -> None:
    async with AsyncSessionLocal() as db:
        await KnowledgeService().process_doc(db, doc_id, tenant_id)


def _to_doc_response(doc) -> KnowledgeDocResponse:
    return KnowledgeDocResponse(
        id=doc.id,
        title=doc.title,
        file_type=doc.file_type,
        storage_path=doc.storage_path,
        status=doc.status,
        chunk_count=doc.chunk_count,
        product_id=doc.product_id,
        error_message=doc.error_message,
        created_by_employee_id=doc.created_by_employee_id,
        created_at=doc.created_at,
        updated_at=doc.updated_at,
    )


def _to_chunk_response(chunk) -> KnowledgeChunkResponse:
    return KnowledgeChunkResponse(
        id=chunk.id,
        doc_id=chunk.doc_id,
        chunk_index=chunk.chunk_index,
        content=chunk.content,
        token_count=chunk.token_count,
        metadata=chunk.metadata_,
        created_at=chunk.created_at,
    )


@router.get("", response_model=KnowledgeDocListResponse)
async def list_knowledge_docs(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    product_id: int | None = Query(None, description="按关联商品过滤"),
    current_user: Employee = Depends(require_permission(PermissionCode.VIEW_KB)),
    db: AsyncSession = Depends(get_db),
):
    """获取知识文档列表"""
    items, total = await _knowledge_service.list_docs(
        db, current_user.tenant_id, skip, limit, product_id=product_id,
    )
    return KnowledgeDocListResponse(
        items=[_to_doc_response(item) for item in items],
        total=total,
    )


@router.get("/{doc_id}", response_model=KnowledgeDocDetailResponse)
async def get_knowledge_doc(
    doc_id: int,
    current_user: Employee = Depends(require_permission(PermissionCode.VIEW_KB)),
    db: AsyncSession = Depends(get_db),
):
    """获取知识文档详情（含分块列表）"""
    doc = await _knowledge_service.get_doc(db, doc_id, current_user.tenant_id)
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")
    chunks = await _knowledge_service.get_doc_chunks(db, doc_id, current_user.tenant_id)
    return KnowledgeDocDetailResponse(
        id=doc.id,
        title=doc.title,
        file_type=doc.file_type,
        storage_path=doc.storage_path,
        status=doc.status,
        chunk_count=doc.chunk_count,
        error_message=doc.error_message,
        created_by_employee_id=doc.created_by_employee_id,
        created_at=doc.created_at,
        updated_at=doc.updated_at,
        chunks=[_to_chunk_response(c) for c in chunks],
    )


@router.post("/upload", response_model=KnowledgeDocResponse, status_code=201)
async def upload_knowledge_doc(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    product_id: int | None = Form(None),
    current_user: Employee = Depends(require_permission(PermissionCode.MANAGE_KB)),
    db: AsyncSession = Depends(get_db),
):
    """上传知识文档（自动解析、分块、向量化）。product_id 可选，用于关联商品。"""
    doc = await _knowledge_service.create_upload_doc(
        db, file, current_user.tenant_id, current_user.id, product_id=product_id,
    )
    background_tasks.add_task(
        _process_knowledge_doc_background,
        doc.id,
        current_user.tenant_id,
    )
    return _to_doc_response(doc)


@router.delete("/{doc_id}", status_code=204)
async def delete_knowledge_doc(
    doc_id: int,
    current_user: Employee = Depends(require_permission(PermissionCode.MANAGE_KB)),
    db: AsyncSession = Depends(get_db),
):
    """删除知识文档及其所有分块"""
    ok = await _knowledge_service.delete_doc(db, doc_id, current_user.tenant_id)
    if not ok:
        raise HTTPException(status_code=404, detail="文档不存在")
