"""测试所有 LabeledEnum 枚举的 label 属性。

覆盖 PermissionCode / PendingAction / PendingDirective / SkillName / RiskLevel / VectorDomain / LLMUseCase。
每个枚举成员的 .label 必须返回非空字符串，不允许 KeyError。
"""

from app.ai.context.pending_state import PendingAction, PendingDirective
from app.ai.recognition.types import SkillName, RiskLevel
from app.ai.rag.vector_search import VectorDomain
from app.integrations.llm_client import LLMUseCase
from app.models.role import PermissionCode


_ENUM_CLASSES = [
    ("PermissionCode", PermissionCode),
    ("PendingAction", PendingAction),
    ("PendingDirective", PendingDirective),
    ("SkillName", SkillName),
    ("RiskLevel", RiskLevel),
    ("VectorDomain", VectorDomain),
    ("LLMUseCase", LLMUseCase),
]


def test_all_enums_have_non_empty_labels():
    """遍历所有 LabeledEnum，断言每个成员的 label 是非空字符串。"""
    for name, enum_cls in _ENUM_CLASSES:
        for member in enum_cls:
            label = member.label
            assert isinstance(label, str), f"{name}.{member.name}.label 不是字符串: {type(label)}"
            assert len(label) > 0, f"{name}.{member.name}.label 是空字符串"
            assert label != member.value, f"{name}.{member.name}.label 不应等于枚举值"


def test_permission_code_all_members_covered():
    """PermissionCode 每个成员必须都有专属 label 描述。"""
    covered = {m.label for m in PermissionCode}
    assert len(covered) == len(PermissionCode), (
        f"PermissionCode 有 {len(PermissionCode)} 个成员，但只有 {len(covered)} 个唯一 label"
    )
    # 验证无 KeyError
    for member in PermissionCode:
        _ = member.label


def test_permission_code_label_descriptions():
    """PermissionCode label 应包含有意义的中文描述。"""
    labels = {m.name: m.label for m in PermissionCode}
    assert "查看分配给我的会话" == labels["VIEW_ASSIGNED_CHATS"]
    assert "管理租户（平台专有）" == labels["MANAGE_TENANTS"]
    assert "导出平台数据（平台专有）" == labels["EXPORT_DATA"]
    assert "管理意图样本" == labels["MANAGE_INTENT_SAMPLES"]
    assert "管理敏感词" == labels["MANAGE_SENSITIVE_WORDS"]
