"""ORM 模型包 —— 导入所有模型以确保 Alembic autogenerate 能检测到"""

from app.models.base import Base
from app.models.category import Category
from app.models.contact import Contact
from app.models.conversation import Conversation, Message
from app.models.plan import Plan
from app.models.platform import Platform
from app.models.image import Image
from app.models.knowledge_chunk import KnowledgeChunk
from app.models.knowledge_doc import KnowledgeDoc
from app.models.llm_config import LLMConfig
from app.models.marketing_document import MarketingDocument
from app.models.order import Order, OrderItem
from app.models.operations import AuditLog, LoginHistory, SensitiveWord, SystemNotification
from app.models.product import Product
from app.models.qa_pair import QAPair
from app.models.sales_memory import SalesMemory
from app.models.sales_intelligence import ContactProductContext, ConversationTodo, FollowupPlan, SalesContext
from app.models.tenant import Tenant
from app.models.usage import LLMUsageLog
from app.models.system import BackupRecord, SystemSetting
from app.models.employee import Employee
from app.models.role import Role, Permission, RolePermission, EmployeeRole, PermissionCode
from app.models.intent_sample import IntentSample

__all__ = [
    "Base",
    "Category",
    "Contact",
    "Conversation",
    "Message",
    "Plan",
    "Platform",
    "Product",
    "Order",
    "Image",
    "KnowledgeChunk",
    "KnowledgeDoc",
    "LLMConfig",
    "MarketingDocument",
    "OrderItem",
    "AuditLog",
    "LoginHistory",
    "SensitiveWord",
    "SystemNotification",
    "QAPair",
    "SalesMemory",
    "SalesContext",
    "ContactProductContext",
    "FollowupPlan",
    "ConversationTodo",
    "Tenant",
    "LLMUsageLog",
    "SystemSetting",
    "BackupRecord",
    "Employee",
    "Role",
    "Permission",
    "PermissionCode",
    "RolePermission",
    "EmployeeRole",
    "IntentSample",
]
