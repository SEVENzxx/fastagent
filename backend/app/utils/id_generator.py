"""雪花算法 ID 生成器"""

from snowflake import SnowflakeGenerator

# 全局生成器（datacenter_id=0, worker_id=0）
_gen = SnowflakeGenerator(0, 0)


def generate_id() -> int:
    """生成雪花算法 ID"""
    return next(_gen)
