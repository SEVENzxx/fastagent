"""租户设置 Schema。"""

from typing import Literal

from pydantic import Field, field_validator, model_validator

from app.schemas.base import CamelModel


class AttributeDef(CamelModel):
    """单个属性定义。

    租户配置商品属性的最小单元，平台据此构建 LLM 抽取 prompt 和 SQL 查询。
    """

    key: str = Field(
        description="属性唯一标识，对应 attrs_json 中的字段名，如 is_waterproof",
        min_length=1,
        max_length=64,
    )
    label: str = Field(
        description="前端展示名，如『防水』",
        min_length=1,
        max_length=32,
    )
    type: Literal["boolean", "number", "enum", "text"] = Field(
        description="属性值类型",
    )
    aliases: list[str] = Field(
        default_factory=list,
        description="同义表达列表，如 ['防水', '防泼水', '可防水']，用于 LLM 语义匹配",
    )
    description: str = Field(
        default="",
        description="属性说明，LLM 抽取时作为判断依据",
    )
    query_path: list[str] = Field(
        default_factory=list,
        description="attrs_json 中的 JSON 路径，如 ['attr', 'is_waterproof']",
    )
    query_strategy: Literal["jsonb_bool", "jsonb_number", "jsonb_text", "jsonb_equals", "jsonb_contains"] = Field(
        default="jsonb_text",
        description="SQL 查询策略：jsonb_bool / jsonb_number / jsonb_text / jsonb_equals / jsonb_contains",
    )
    unit: str | None = Field(
        default=None,
        description="数值单位，如『天』『小时』，LLM 抽取时用于换算提示",
    )
    allowed_values: list[str] = Field(
        default_factory=list,
        description="enum 类型的可选值列表",
    )

    @field_validator("key")
    @classmethod
    def key_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("属性 key 不能为空")
        return v

    @field_validator("label")
    @classmethod
    def label_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("属性 label 不能为空")
        return v

    @model_validator(mode="after")
    def enum_requires_allowed_values(self):
        if self.type == "enum" and not self.allowed_values:
            raise ValueError(f"enum 类型属性 '{self.key}' 必须配置 allowed_values")
        return self


class TenantAttributeSchema(CamelModel):
    """租户完整属性配置 Schema。

    存储于 Tenant.template_json 列（JSONB），按产品分类组织：
    {
      "category_attributes": {
        "123": [
          { "key": "is_waterproof", "label": "防水", "type": "boolean", ... },
          ...
        ],
        "456": [...]
      }
    }
    """

    category_attributes: dict[str, list[AttributeDef]] = Field(
        default_factory=dict,
        description="按分类 ID 组织的属性定义映射",
    )


# ── API 响应/请求模型 ──

class TenantTemplateResponse(CamelModel):
    """租户属性模板响应（按分类）。"""

    category_id: str = Field(default="", description="分类 ID，空表示未分类")
    category_name: str = Field(default="", description="分类名称")
    attributes: list[AttributeDef] = Field(
        default_factory=list,
        description="属性定义列表",
    )


class TenantTemplateUpdate(CamelModel):
    """更新租户属性模板请求。"""

    category_id: str = Field(default="", description="分类 ID")
    attributes: list[AttributeDef] = Field(
        default_factory=list,
        description="属性定义列表",
    )


class CategoryAttrOption(CamelModel):
    """分类属性配置选项（下拉列表用）。"""

    category_id: str = Field(description="分类 ID")
    category_name: str = Field(description="分类名称")
    attr_count: int = Field(default=0, description="已配置属性数")
