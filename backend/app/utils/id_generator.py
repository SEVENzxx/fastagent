"""雪花算法 ID 生成器（纯 Python 实现，零依赖）"""

import socket
import threading
import time

# ── 全局唯一 work_id ──────────────────────────────────────────────────────
# 基于 hostname 取模，自动分配 0-31 的 work_id
_WORK_ID = abs(hash(socket.gethostname())) % 32
_DATACENTER_ID = 0

# 时间起始 (2024-01-01 00:00:00 UTC)
_EPOCH = 1704067200000
_WORKER_ID_BITS = 5
_DATACENTER_ID_BITS = 5
_SEQUENCE_BITS = 12

_MAX_WORKER_ID = (1 << _WORKER_ID_BITS) - 1
_MAX_DATACENTER_ID = (1 << _DATACENTER_ID_BITS) - 1
_MAX_SEQUENCE = (1 << _SEQUENCE_BITS) - 1

_WORKER_ID_SHIFT = _SEQUENCE_BITS
_DATACENTER_ID_SHIFT = _SEQUENCE_BITS + _WORKER_ID_BITS
_TIMESTAMP_SHIFT = _SEQUENCE_BITS + _WORKER_ID_BITS + _DATACENTER_ID_BITS


class SnowflakeGenerator:
    def __init__(self, datacenter_id: int = 0, worker_id: int = 0):
        if not (0 <= datacenter_id <= _MAX_DATACENTER_ID):
            raise ValueError(f"datacenter_id 必须在 0-{_MAX_DATACENTER_ID} 之间")
        if not (0 <= worker_id <= _MAX_WORKER_ID):
            raise ValueError(f"worker_id 必须在 0-{_MAX_WORKER_ID} 之间")

        self.datacenter_id = datacenter_id
        self.worker_id = worker_id
        self.sequence = 0
        self.last_timestamp = -1
        self._lock = threading.Lock()

    def _current_ms(self) -> int:
        return int(time.time() * 1000)

    def _wait_next_ms(self, last: int) -> int:
        ts = self._current_ms()
        while ts <= last:
            ts = self._current_ms()
        return ts

    def next_id(self) -> int:
        with self._lock:
            ts = self._current_ms()

            if ts < self.last_timestamp:
                raise RuntimeError("时钟回拨，拒绝生成 ID")

            if ts == self.last_timestamp:
                self.sequence = (self.sequence + 1) & _MAX_SEQUENCE
                if self.sequence == 0:
                    ts = self._wait_next_ms(self.last_timestamp)
            else:
                self.sequence = 0

            self.last_timestamp = ts

            return (
                ((ts - _EPOCH) << _TIMESTAMP_SHIFT)
                | (self.datacenter_id << _DATACENTER_ID_SHIFT)
                | (self.worker_id << _WORKER_ID_SHIFT)
                | self.sequence
            )

    def __next__(self) -> int:
        return self.next_id()

    def __iter__(self):
        return self


# 全局单例
_gen = SnowflakeGenerator(datacenter_id=_DATACENTER_ID, worker_id=_WORK_ID)


def generate_id() -> int:
    """生成雪花算法 ID"""
    return next(_gen)
