"""ORM 模型包 —— 导入所有模型以确保 Alembic autogenerate 能检测到"""

from app.models.base import Base
from app.models.category import Category
from app.models.contact import Contact
from app.models.conversation import Conversation, Message
from app.models.plan import Plan
from app.models.platform import Platform
from app.models.product import Product
from app.models.tenant import Tenant
from app.models.employee import Employee
from app.models.role import Role, Permission, RolePermission, EmployeeRole, PermissionCode

__all__ = [
    "Base",
    "Category",
    "Contact",
    "Conversation",
    "Message",
    "Plan",
    "Platform",
    "Product",
    "Tenant",
    "Employee",
    "Role",
    "Permission",
    "PermissionCode",
    "RolePermission",
    "EmployeeRole",
]
