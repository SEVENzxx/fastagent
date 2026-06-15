"""平台运维模型 —— 系统设置和数据库备份记录。"""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.utils.id_generator import generate_id


class SystemSetting(Base):
    """平台全局系统设置键值表。"""

    __tablename__ = "system_settings"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, default=generate_id, comment="主键")
    key: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, comment="设置键名")
    value: Mapped[str] = mapped_column(Text, nullable=False, default="", comment="设置值（统一存文本，业务层自行转换）")
    description: Mapped[str | None] = mapped_column(String(500), nullable=True, comment="设置项说明")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), comment="最后修改时间")


class BackupRecord(Base):
    """数据库备份作业跟踪记录。"""

    __tablename__ = "backup_records"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, default=generate_id, comment="主键")
    name: Mapped[str] = mapped_column(String(255), nullable=False, comment="备份文件名")
    file_path: Mapped[str | None] = mapped_column(String(1000), nullable=True, comment="备份文件存储路径")
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="备份文件大小（字节）")
    type: Mapped[str] = mapped_column(String(20), nullable=False, default="full", comment="备份类型: full(全量) / schema(仅结构)")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="running", comment="备份状态: running / completed / failed")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True, comment="失败原因")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), comment="备份创建时间")
