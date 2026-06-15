"""平台运维服务 — 系统设置、数据库健康监控、备份管理。"""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.system import BackupRecord, SystemSetting
from app.config import settings
from app.schemas.system import BackupRecordResponse, DbHealthResponse, SystemSettingsUpdate

logger = logging.getLogger(__name__)


# ── 系统设置默认值 ──
# key → value 的初始默认值，在 init_default_settings 中写入
# 仅在新安装（key 不存在时）才会创建，不会覆盖已有配置
_DEFAULT_SETTINGS: dict[str, tuple[str, str]] = {
    "max_file_upload_mb": ("10", "文件上传大小上限 (MB)"),
    "rate_limit_per_minute": ("60", "API 请求频率限制 (次/分钟)"),
    "session_idle_timeout_seconds": ("1800", "会话空闲超时时间 (秒)"),
    "backup_retention_days": ("7", "备份文件保留天数"),
    "auto_cleanup_enabled": ("false", "是否自动清理过期数据"),
}


async def init_default_settings(db: AsyncSession) -> None:
    """初始化系统设置默认值。"""
    for key, (value, description) in _DEFAULT_SETTINGS.items():
        exists = await db.scalar(select(SystemSetting.id).where(SystemSetting.key == key))
        if exists is None:
            db.add(SystemSetting(key=key, value=value, description=description))
    await db.commit()


async def get_all_settings(db: AsyncSession) -> dict[str, str]:
    """获取所有系统设置键值对。"""
    rows = (await db.execute(select(SystemSetting))).scalars().all()
    result = dict(_DEFAULT_SETTINGS)
    # 数据库中的值覆盖默认值（raw value 不带 description）
    for row in rows:
        result[row.key] = row.value
    return result


async def update_settings(db: AsyncSession, body: SystemSettingsUpdate) -> None:
    """批量更新系统设置。"""
    for key, value in body.settings.items():
        row = await db.scalar(select(SystemSetting).where(SystemSetting.key == key))
        if row is None:
            description = _DEFAULT_SETTINGS.get(key, ("", ""))[1]
            db.add(SystemSetting(key=key, value=value, description=description))
        else:
            row.value = value
    await db.commit()


async def get_db_health(db: AsyncSession) -> DbHealthResponse:
    """查询数据库健康状态。"""
    # ── 连接数 ──
    active = await db.scalar(text("SELECT count(*) FROM pg_stat_activity WHERE state = 'active'"))
    max_conn = await db.scalar(text("SELECT setting::int FROM pg_settings WHERE name = 'max_connections'"))

    # ── 数据库大小 (MB) ──
    db_size = await db.scalar(text("SELECT pg_database_size(current_database())"))

    # ── 运行时长 (通过 postmaster 启动时间计算) ──
    uptime_seconds = await db.scalar(text(
        "SELECT EXTRACT(EPOCH FROM (now() - pg_postmaster_start_time()))::bigint"
    ))

    # ── 慢查询统计 (pg_stat_statements，可能未安装扩展) ──
    try:
        slow_queries = await db.scalar(text(
            "SELECT count(*) FROM pg_stat_statements "
            "WHERE mean_exec_time > 1000 "  # 平均执行时间 > 1 秒
            "AND calls > 0"
        ))
    except Exception:
        slow_queries = 0  # pg_stat_statements 未安装时静默降级

    # ── 索引命中率 ──
    # 公式：(索引扫描次数 / (索引扫描 + 全表扫描)) × 100
    stats = (await db.execute(text(
        "SELECT COALESCE(SUM(idx_scan), 0) AS idx_scans, "
        "COALESCE(SUM(seq_scan), 0) AS seq_scans "
        "FROM pg_stat_user_tables"
    ))).one()
    total_scans = stats.idx_scans + stats.seq_scans
    hit_rate = round((stats.idx_scans / total_scans * 100) if total_scans > 0 else 100.0, 1)

    return DbHealthResponse(
        active_connections=active or 0,
        max_connections=max_conn or 100,
        db_size_mb=(db_size or 0) // (1024 * 1024),
        uptime_hours=(uptime_seconds or 0) // 3600,
        slow_queries_24h=slow_queries or 0,
        index_hit_rate=hit_rate,
    )


# ── 备份目录 ──
_BACKUP_DIR = Path(__file__).resolve().parent.parent.parent.parent / "backups"


async def list_backups(db: AsyncSession) -> list[dict]:
    """查询备份记录列表。"""
    rows = (await db.execute(
        select(BackupRecord).order_by(BackupRecord.created_at.desc())
    )).scalars().all()
    return [
        {
            "id": str(row.id), "name": row.name,
            "size_bytes": row.size_bytes,
            "size_mb": round(row.size_bytes / (1024 * 1024), 2),
            "type": row.type, "status": row.status,
            "error_message": row.error_message,
            "created_at": row.created_at,
        }
        for row in rows
    ]


async def create_backup(db: AsyncSession, type: str = "full") -> BackupRecord:
    """创建一次新的数据库备份。"""
    now = datetime.now(timezone.utc)
    timestamp = now.strftime("%Y%m%d_%H%M%S")
    filename = f"backup_{timestamp}.dump"

    record = BackupRecord(
        name=filename, type=type, size_bytes=0, status="running",
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)

    # 启动后台异步任务执行 pg_dump
    record_id = record.id
    asyncio.create_task(_run_pg_dump(record_id, filename, type))
    return record


async def restore_backup(db: AsyncSession, backup_id: int) -> BackupRecord | None:
    """从指定备份恢复数据库。"""
    record = await db.get(BackupRecord, backup_id)
    if record is None or record.status != "completed":
        return None

    asyncio.create_task(_run_pg_restore(backup_id, record.file_path or record.name))
    return record


async def delete_backup(db: AsyncSession, backup_id: int) -> BackupRecord | None:
    """删除备份记录和对应的磁盘文件。"""
    record = await db.get(BackupRecord, backup_id)
    if record is None:
        return None

    # 尝试删除磁盘文件（失败不阻断，可能是文件已经被手动清理）
    file_path = record.file_path or _BACKUP_DIR / record.name
    try:
        if os.path.exists(str(file_path)):
            os.remove(str(file_path))
    except OSError:
        logger.warning("删除备份文件失败: path=%s", file_path)

    await db.delete(record)
    await db.commit()
    return record


async def _run_pg_dump(record_id: int, filename: str, type: str) -> None:
    """后台任务：执行 pg_dump 并更新备份记录状态。"""
    from app.integrations.database import AsyncSessionLocal

    _BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    file_path = str(_BACKUP_DIR / filename)
    db_url = settings.DATABASE_URL

    # 构建 pg_dump 命令参数
    cmd = ["pg_dump", "--format=custom", f"--file={file_path}"]
    if type == "schema":
        cmd.append("--schema-only")

    # 从 DATABASE_URL 提取连接参数
    # 格式: postgresql+asyncpg://user:pass@host:port/dbname
    try:
        url = db_url.replace("postgresql+asyncpg://", "").replace("postgresql://", "")
        user_pass, rest = url.split("@", 1) if "@" in url else ("", url)
        host_port, dbname = rest.split("/", 1) if "/" in rest else (rest, "fastagent")
        host = host_port.split(":")[0]
        port = host_port.split(":")[1] if ":" in host_port else "5432"
        user = user_pass.split(":")[0] if ":" in user_pass else ""
        password = user_pass.split(":")[1] if ":" in user_pass and ":" in user_pass else ""

        env = os.environ.copy()
        if password:
            env["PGPASSWORD"] = password
        cmd.extend([f"--host={host}", f"--port={port}", f"--username={user}", f"--dbname={dbname}"])

        result = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=600)

        async with AsyncSessionLocal() as db:
            record = await db.get(BackupRecord, record_id)
            if record:
                if result.returncode == 0:
                    file_size = os.path.getsize(file_path) if os.path.exists(file_path) else 0
                    record.size_bytes = file_size
                    record.file_path = file_path
                    record.status = "completed"
                else:
                    record.status = "failed"
                    record.error_message = result.stderr[:500] if result.stderr else "pg_dump 执行失败"
                await db.commit()
    except Exception as exc:
        async with AsyncSessionLocal() as db:
            record = await db.get(BackupRecord, record_id)
            if record:
                record.status = "failed"
                record.error_message = str(exc)[:500]
                await db.commit()


async def _run_pg_restore(backup_id: int, file_path_or_name: str) -> None:
    """后台任务：从备份文件恢复数据库。"""
    from app.integrations.database import AsyncSessionLocal

    full_path = file_path_or_name
    if not os.path.isabs(str(full_path)):
        full_path = str(_BACKUP_DIR / file_path_or_name)

    if not os.path.exists(str(full_path)):
        async with AsyncSessionLocal() as db:
            record = await db.get(BackupRecord, backup_id)
            if record:
                record.status = "failed"
                record.error_message = f"备份文件不存在: {full_path}"
                await db.commit()
        return

    db_url = settings.DATABASE_URL
    try:
        url = db_url.replace("postgresql+asyncpg://", "").replace("postgresql://", "")
        user_pass, rest = url.split("@", 1) if "@" in url else ("", url)
        host_port, dbname = rest.split("/", 1) if "/" in rest else (rest, "fastagent")
        host = host_port.split(":")[0]
        port = host_port.split(":")[1] if ":" in host_port else "5432"
        user = user_pass.split(":")[0] if ":" in user_pass else ""
        password = user_pass.split(":")[1] if ":" in user_pass and ":" in user_pass else ""

        env = os.environ.copy()
        if password:
            env["PGPASSWORD"] = password

        cmd = [
            "pg_restore", "--clean", "--if-exists", f"--host={host}",
            f"--port={port}", f"--username={user}", f"--dbname={dbname}",
            "--no-owner", "--no-privileges", str(full_path),
        ]
        subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=600)
    except Exception:
        logger.warning("恢复备份失败: backup_id=%s", backup_id)
