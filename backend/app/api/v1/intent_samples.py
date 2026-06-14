"""意图样本管理 API — 租户自定义意图样本 CRUD + 测试召回。

所有接口需要 manage_intent_samples 权限。
Skill 和 RiskLevel 必须后端枚举校验，禁止前端随便传字符串入库。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.recognition.types import RiskLevel, SkillName
from app.database import get_db
from app.dependencies import require_permission
from app.models.employee import Employee
from app.models.role import PermissionCode
from app.schemas.intent_sample import (
    IntentSampleBatchCreate,
    IntentSampleCreate,
    IntentSampleListResponse,
    IntentSampleResponse,
    IntentSampleTestSearch,
    IntentSampleTestSearchResponse,
    IntentSampleTestHit,
    IntentSampleUpdate,
    SkillOption,
    RiskLevelOption,
)
from app.services.intent_sample_service import IntentSampleService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ai/intent-samples", tags=["意图样本"])

_service = IntentSampleService()


def _to_response(sample) -> IntentSampleResponse:
    return IntentSampleResponse(
        id=sample.id,
        tenant_id=sample.tenant_id,
        intent=sample.intent,
        label=sample.label,
        skill=sample.skill,
        risk_level=sample.risk_level,
        example_text=sample.example_text,
        enabled=sample.enabled,
        source=sample.source,
        schema_version=sample.schema_version,
        qdrant_point_id=sample.qdrant_point_id,
        created_at=sample.created_at,
        updated_at=sample.updated_at,
    )


@router.get("", response_model=IntentSampleListResponse)
async def list_intent_samples(
    intent: str | None = Query(None, description="按 intent 过滤"),
    skill: str | None = Query(None, description="按 skill 过滤"),
    enabled: bool | None = Query(None, description="按启用状态过滤"),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    current_user: Employee = Depends(require_permission(PermissionCode.MANAGE_INTENT_SAMPLES)),
    db: AsyncSession = Depends(get_db),
):
    """获取当前租户的自定义意图样本列表"""
    items, total = await _service.list_samples(
        db,
        current_user.tenant_id,
        intent=intent,
        skill=skill,
        enabled=enabled,
        skip=skip,
        limit=limit,
    )
    return IntentSampleListResponse(
        items=[_to_response(item) for item in items],
        total=total,
    )


@router.post("", response_model=IntentSampleResponse, status_code=201)
async def create_intent_sample(
    body: IntentSampleCreate,
    current_user: Employee = Depends(require_permission(PermissionCode.MANAGE_INTENT_SAMPLES)),
    db: AsyncSession = Depends(get_db),
):
    """新增意图样本 → DB 写入 + Qdrant upsert"""
    sample = await _service.create_sample(db, current_user.tenant_id, body)
    return _to_response(sample)


@router.post("/batch", response_model=list[IntentSampleResponse], status_code=201)
async def batch_create_intent_samples(
    body: IntentSampleBatchCreate,
    current_user: Employee = Depends(require_permission(PermissionCode.MANAGE_INTENT_SAMPLES)),
    db: AsyncSession = Depends(get_db),
):
    """批量新增意图样本 — 共享 intent / label / skill / risk_level"""
    created = await _service.create_sample_batch(db, current_user.tenant_id, body)
    return [_to_response(s) for s in created]


@router.put("/{sample_id}", response_model=IntentSampleResponse)
async def update_intent_sample(
    sample_id: int,
    body: IntentSampleUpdate,
    current_user: Employee = Depends(require_permission(PermissionCode.MANAGE_INTENT_SAMPLES)),
    db: AsyncSession = Depends(get_db),
):
    """编辑意图样本 → DB 更新 + Qdrant re-upsert"""
    sample = await _service.get_sample(db, sample_id, current_user.tenant_id)
    if not sample:
        raise HTTPException(status_code=404, detail="样本不存在")
    sample = await _service.update_sample(db, sample, body)
    return _to_response(sample)


@router.patch("/{sample_id}/enabled", response_model=IntentSampleResponse)
async def toggle_intent_sample_enabled(
    sample_id: int,
    enabled: bool = Query(..., description="true=启用, false=停用"),
    current_user: Employee = Depends(require_permission(PermissionCode.MANAGE_INTENT_SAMPLES)),
    db: AsyncSession = Depends(get_db),
):
    """启用/停用意图样本 → DB 更新 + Qdrant 同步"""
    sample = await _service.get_sample(db, sample_id, current_user.tenant_id)
    if not sample:
        raise HTTPException(status_code=404, detail="样本不存在")
    sample = await _service.set_enabled(db, sample, enabled)
    return _to_response(sample)


@router.delete("/{sample_id}", status_code=204)
async def delete_intent_sample(
    sample_id: int,
    current_user: Employee = Depends(require_permission(PermissionCode.MANAGE_INTENT_SAMPLES)),
    db: AsyncSession = Depends(get_db),
):
    """删除意图样本 → DB 删除 + Qdrant 同步删除"""
    sample = await _service.get_sample(db, sample_id, current_user.tenant_id)
    if not sample:
        raise HTTPException(status_code=404, detail="样本不存在")
    await _service.delete_sample(db, sample)


@router.post("/test-search", response_model=IntentSampleTestSearchResponse)
async def test_search_intent_samples(
    body: IntentSampleTestSearch,
    current_user: Employee = Depends(require_permission(PermissionCode.MANAGE_INTENT_SAMPLES)),
    db: AsyncSession = Depends(get_db),
):
    """测试向量召回 — 输入一句 query，返回匹配的意图样本（含平台默认 + 租户自定义）"""
    # 解析 query 时触发向量搜索，不需要 db，为保持接口签名一致保留 db 参数
    results = await _service.test_search(db, body.query, current_user.tenant_id)
    return IntentSampleTestSearchResponse(
        query=body.query,
        results=[IntentSampleTestHit(**r) for r in results],
    )


@router.get("/skill-options", response_model=list[SkillOption])
async def list_skill_options():
    """获取 Skill 枚举选项（前端下拉列表用）"""
    return [
        SkillOption(value=s.value, label=_skill_label(s))
        for s in SkillName
    ]


@router.get("/risk-level-options", response_model=list[RiskLevelOption])
async def list_risk_level_options():
    """获取 RiskLevel 枚举选项（前端下拉列表用）"""
    return [
        RiskLevelOption(value=r.value, label=_risk_label(r))
        for r in RiskLevel
    ]


def _skill_label(s: SkillName) -> str:
    labels = {
        SkillName.TEMPLATE: "模板回复",
        SkillName.PRODUCT: "商品",
        SkillName.ORDER: "订单",
        SkillName.RAG: "知识库/RAG",
        SkillName.HUMAN: "转人工",
        SkillName.FALLBACK: "兜底",
    }
    return labels.get(s, s.value)


def _risk_label(r: RiskLevel) -> str:
    labels = {
        RiskLevel.READ_ONLY: "只读（查询类）",
        RiskLevel.LOW_RISK_WRITE: "低风险写",
        RiskLevel.HIGH_RISK_WRITE: "高风险写",
    }
    return labels.get(r, r.value)
