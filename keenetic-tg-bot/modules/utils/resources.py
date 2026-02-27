
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Resources:
    mem_total_mb: int
    cpu_cores: int
    opt_free_mb: int
    opt_total_mb: int


def _read_int_from_meminfo(key: str) -> Optional[int]:
    try:
        with open("/proc/meminfo", "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                if line.startswith(key):
                    parts = line.split()
                    # value in kB
                    return int(parts[1])
    except Exception:
        return None
    return None


def get_mem_total_mb() -> int:
    kb = _read_int_from_meminfo("MemTotal:")
    if not kb:
        return 0
    return int(kb / 1024)


def get_cpu_cores() -> int:
    # /proc/cpuinfo may have "processor" entries
    try:
        with open("/proc/cpuinfo", "r", encoding="utf-8", errors="ignore") as f:
            count = sum(1 for line in f if line.lower().startswith("processor"))
        if count > 0:
            return count
    except Exception:
        pass
    try:
        return os.cpu_count() or 1
    except Exception:
        return 1


def get_fs_free_mb(path: str) -> tuple[int, int]:
    try:
        st = os.statvfs(path)
        free = int(st.f_bavail * st.f_frsize / (1024 * 1024))
        total = int(st.f_blocks * st.f_frsize / (1024 * 1024))
        return free, total
    except Exception:
        return 0, 0


def detect_resources(opt_path: str = "/opt") -> Resources:
    mem = get_mem_total_mb()
    cores = get_cpu_cores()
    free, total = get_fs_free_mb(opt_path)
    return Resources(mem_total_mb=mem, cpu_cores=cores, opt_free_mb=free, opt_total_mb=total)


def recommend_threads(mem_total_mb: int, cpu_cores: int) -> int:
    """
    Conservative defaults for small routers.
    """
    if mem_total_mb <= 0:
        return 1
    if mem_total_mb < 128:
        return 1
    if mem_total_mb < 256:
        return 2
    # Enough RAM: bound by cores but not too high
    return max(2, min(4, cpu_cores or 2))
