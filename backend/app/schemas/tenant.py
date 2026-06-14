"""Tenant settings schemas."""

from pydantic import field_validator

from app.schemas.base import CamelModel


class TenantTemplateResponse(CamelModel):
    template_json: list[str]


class TenantTemplateUpdate(CamelModel):
    template_json: list[str]

    @field_validator("template_json")
    @classmethod
    def validate_template_json(cls, value: list[str]) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for item in value:
            if not isinstance(item, str):
                raise ValueError("template_json 只能包含字符串字段名")
            field = item.strip()
            if not field:
                raise ValueError("template_json 不能包含空字段名")
            if field not in seen:
                seen.add(field)
                result.append(field)
        return result
