"""平台运维 Schema — 系统设置、数据库健康、备份记录。"""

from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.base import CamelModel


class SystemSettingItem(BaseModel):
    """单个系统设置项（key-value）。"""
    key: str
    value: str
    description: str | None = None


class SystemSettingsResponse(CamelModel):
    """系统设置列表响应。"""
    settings: list[SystemSettingItem]


class SystemSettingsUpdate(BaseModel):
    """批量更新系统设置请求体。

    key 对应的 value，未传的 key 保持不变。
    """
    settings: dict[str, str] = Field(..., description="键值对，如 {'max_file_upload_mb': '20'}")


class DbHealthResponse(CamelModel):
    """数据库健康状态快照。"""
    active_connections: int = Field(..., description="当前活跃连接数")
    max_connections: int = Field(..., description="最大连接数上限")
    db_size_mb: int = Field(..., description="数据库占用磁盘大小 (MB)")
    uptime_hours: int = Field(..., description="数据库进程运行时长 (小时)")
    slow_queries_24h: int = Field(..., description="最近 24 小时慢查询数")
    index_hit_rate: float = Field(..., description="索引命中率 (0-100)")


class BackupRecordResponse(CamelModel):
    """备份记录响应。"""
    id: str
    name: str
    size_bytes: int
    size_mb: float = Field(..., description="备份文件大小 (MB)，前端展示用")
    type: str
    status: str
    error_message: str | None = None
    created_at: datetime
