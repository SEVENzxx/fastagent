"""租户设置 Schema。"""

from pydantic import Field, field_validator

from app.schemas.base import CamelModel


class TenantTemplateResponse(CamelModel):
    """租户属性模板响应"""

    template_json: list[str] = Field(description="属性模板字段名列表")


class TenantTemplateUpdate(CamelModel):
    """更新租户属性模板请求"""

    template_json: list[str] = Field(description="属性模板字段名列表")

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
