"""ScenarioExtractor 基类 — 按场景用 LLM 抽取结构化参数。

每个场景一个 Extractor，职责：
  1. 用 LLM 从用户原文抽取业务参数
  2. 从 SessionContext 回填缺失参数
  3. 校验参数合法性
  4. 标记缺失的必填字段

使用方式（Handler 内）：
  extractor = ProductDetailExtractor()
  result = await extractor.extract(text=text, context=ctx, tenant_id=tenant_id)
  if result.missing_fields:
      # → Pending 追问
  entities = result.entities  # 安全传递给 Skill
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, Field

from app.ai.context.session_context import SessionContext


class ExtractionResult(BaseModel):
    """抽取结果。

    entities:        抽到的结构化参数字典，可安全传给 Skill
    missing_fields:  缺失的必填字段名列表
    need_clarification: 是否需要追问用户
    reason:          描述本次抽取结果的原因/过程
    candidates:      多候选列表（歧义时使用）
    """
    entities: dict[str, Any] = Field(default_factory=dict)
    missing_fields: list[str] = Field(default_factory=list)
    need_clarification: bool = False
    reason: str = ""
    candidates: list[dict[str, Any]] = Field(default_factory=list)


class ScenarioExtractor(ABC):
    """场景参数抽取器基类。"""

    @abstractmethod
    async def extract(
        self,
        text: str,
        context: SessionContext,
        tenant_id: int,
        **kwargs: Any,
    ) -> ExtractionResult:
        """从用户原文抽取结构化参数。"""

    # ── 工具方法 ──

    @staticmethod
    def _backfill_from_context(
        entities: dict[str, Any],
        context: SessionContext,
        field_map: dict[str, str],
    ) -> list[str]:
        """从 SessionContext 回填缺失字段。

        Args:
            entities:  当前已抽取的参数字典（会被回填修改）
            context:   会话上下文
            field_map: {entity_key: context_attr_name} 映射

        Returns:
            回填后仍然缺失的字段 key 列表
        """
        missing: list[str] = []
        for entity_key, ctx_attr in field_map.items():
            if entity_key in entities and entities.get(entity_key) is not None:
                continue
            val = getattr(context, ctx_attr, None)
            if val is not None:
                entities[entity_key] = val
            else:
                missing.append(entity_key)
        return missing

    @staticmethod
    def _mark_missing(
        result: ExtractionResult,
        required: list[str],
    ) -> ExtractionResult:
        """标记缺失的必填字段。"""
        result.missing_fields = [
            f for f in required
            if f not in result.entities or result.entities.get(f) is None
        ]
        if result.missing_fields:
            result.need_clarification = True
            result.reason = f"缺少必填字段: {', '.join(result.missing_fields)}"
        return result
