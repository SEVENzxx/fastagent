"""平台运维模型 —— 系统设置和数据库备份记录。

设计意图
--------
- SystemSetting：平台级全局配置键值表，用于存储文件上传上限、限流阈值、
  会话超时时间、备份保留天数等运维参数。用 key-value 而非固定字段以保持扩展性。
- BackupRecord：数据库备份作业的跟踪记录。备份文件由独立 worker 通过 pg_dump 生成，
  本表仅记录元数据（文件名、大小、类型、状态等），不存储备份数据本身。

关联关系
--------
- SystemSetting 为平台级资源，不绑定租户（tenant_id IS NULL）。
- BackupRecord 同样为平台级，不绑定租户。
"""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Integer, String, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.utils.id_generator import generate_id


class SystemSetting(Base):
    """平台全局系统设置键值表。

    用途：存储文件上传上限、API 限流阈值、会话超时时间、备份保留天数等
    不需要频繁改表结构的运维参数。每个 key 对应一条记录，前端以表单形式编辑。
    """

    __tablename__ = "system_settings"

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, default=generate_id,
        comment="主键"
    )
    key: Mapped[str] = mapped_column(
        String(100), unique=True, nullable=False,
        comment="设置键名，如 max_file_upload_mb、rate_limit_per_minute"
    )
    value: Mapped[str] = mapped_column(
        Text, nullable=False, default="",
        comment="设置值，统一存为文本，业务层自行转换类型"
    )
    description: Mapped[str | None] = mapped_column(
        String(500), nullable=True,
        comment="设置项的中文说明，前端用作表单标签和 placeholder"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(),
        comment="最后修改时间"
    )


class BackupRecord(Base):
    """数据库备份作业跟踪记录。

    约定：
    - 备份文件由独立的后端 Worker 通过 pg_dump 生成，存储到对象存储或本地磁盘。
    - 本表只记录元数据（文件名、大小、类型、状态），用于管理后台展示和操作。
    - 状态流转：running → completed / failed
    - 删除备份时同时删除磁盘文件和本表记录。
    """

    __tablename__ = "backup_records"

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, default=generate_id,
        comment="主键"
    )
    name: Mapped[str] = mapped_column(
        String(255), nullable=False,
        comment="备份文件名，如 backup_20260601_120000.dump"
    )
    file_path: Mapped[str | None] = mapped_column(
        String(1000), nullable=True,
        comment="备份文件存储路径（本地路径或对象存储 URL）"
    )
    size_bytes: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
        comment="备份文件大小（字节）"
    )
    type: Mapped[str] = mapped_column(
        String(20), nullable=False, default="full",
        comment="备份类型: full(全量) / schema(仅结构)"
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="running",
        comment="备份状态: running / completed / failed"
    )
    error_message: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="失败原因（status=failed 时填充）"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
        comment="备份创建时间"
    )
