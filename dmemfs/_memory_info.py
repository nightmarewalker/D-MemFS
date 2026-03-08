"""OS-specific available physical memory detection.

Internal module - not part of the public API.
Uses only Python standard library.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import platform
from collections.abc import Callable
from typing import cast

_SYSTEM = platform.system()
_UNPROBED = object()
_linux_reader: Callable[[], int | None] | None | object = _UNPROBED


def get_available_memory_bytes() -> int | None:
    """Return available physical memory in bytes, or None if unavailable."""
    try:
        if _SYSTEM == "Windows":
            return _windows_avail()
        if _SYSTEM == "Linux":
            return _linux_avail()
        if _SYSTEM == "Darwin":
            return _macos_avail()
    except Exception:
        return None
    return None


def _windows_avail() -> int:
    class MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [
            ("dwLength", ctypes.c_ulong),
            ("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]

    stat = MEMORYSTATUSEX()
    stat.dwLength = ctypes.sizeof(stat)
    result = ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
    if not result:
        raise OSError("GlobalMemoryStatusEx failed")
    return int(stat.ullAvailPhys)


def _linux_avail() -> int | None:
    global _linux_reader
    if _linux_reader is _UNPROBED:
        _linux_reader = _probe_linux_source()
    if _linux_reader is None:
        return None
    return cast(Callable[[], int | None], _linux_reader)()


def _probe_linux_source() -> Callable[[], int | None] | None:
    if _is_cgroup_v2_limited():
        return _read_cgroup_v2
    if _is_cgroup_v1_limited():
        return _read_cgroup_v1
    if _is_procmeminfo_available():
        return _read_procmeminfo
    return None


def _is_cgroup_v2_limited() -> bool:
    try:
        with open("/sys/fs/cgroup/memory.max", encoding="utf-8") as handle:
            return handle.read().strip() != "max"
    except (FileNotFoundError, PermissionError):
        return False


def _is_cgroup_v1_limited() -> bool:
    try:
        with open("/sys/fs/cgroup/memory/memory.limit_in_bytes", encoding="utf-8") as handle:
            limit = int(handle.read().strip())
        host_total = _read_procmeminfo_total()
        if host_total is not None and limit >= host_total:
            return False
        return True
    except (FileNotFoundError, PermissionError, ValueError):
        return False


def _is_procmeminfo_available() -> bool:
    try:
        with open("/proc/meminfo", encoding="utf-8") as handle:
            handle.readline()
        return True
    except (FileNotFoundError, PermissionError):
        return False


def _read_cgroup_v2() -> int | None:
    with open("/sys/fs/cgroup/memory.max", encoding="utf-8") as handle:
        value = handle.read().strip()
    if value == "max":
        return None
    max_mem = int(value)
    with open("/sys/fs/cgroup/memory.current", encoding="utf-8") as handle:
        current = int(handle.read().strip())
    return max(0, max_mem - current)


def _read_cgroup_v1() -> int:
    with open("/sys/fs/cgroup/memory/memory.limit_in_bytes", encoding="utf-8") as handle:
        limit = int(handle.read().strip())
    with open("/sys/fs/cgroup/memory/memory.usage_in_bytes", encoding="utf-8") as handle:
        usage = int(handle.read().strip())
    return max(0, limit - usage)


def _read_procmeminfo_total() -> int | None:
    try:
        with open("/proc/meminfo", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("MemTotal:"):
                    return int(line.split()[1]) * 1024
    except Exception:
        return None
    return None


def _read_procmeminfo() -> int:
    with open("/proc/meminfo", encoding="utf-8") as handle:
        content = handle.read()

    mem_data: dict[str, int] = {}
    for line in content.splitlines():
        parts = line.split()
        if len(parts) >= 2:
            mem_data[parts[0].rstrip(":")] = int(parts[1])

    free_kb = mem_data.get("MemAvailable", mem_data.get("MemFree", 0))
    return free_kb * 1024


def _read_proc_meminfo() -> int:
    return _read_procmeminfo()


def _macos_avail() -> int:
    libc_path = ctypes.util.find_library("c") or "/usr/lib/libSystem.B.dylib"
    libc = ctypes.CDLL(libc_path)

    host_vm_info64 = 4
    host_vm_info64_count = 48

    class VMStatistics64(ctypes.Structure):
        _fields_ = [
            ("free_count", ctypes.c_uint64),
            ("active_count", ctypes.c_uint64),
            ("inactive_count", ctypes.c_uint64),
            ("wire_count", ctypes.c_uint64),
            ("zero_fill_count", ctypes.c_uint64),
            ("reactivations", ctypes.c_uint64),
            ("pageins", ctypes.c_uint64),
            ("pageouts", ctypes.c_uint64),
            ("faults", ctypes.c_uint64),
            ("cow_faults", ctypes.c_uint64),
            ("lookups", ctypes.c_uint64),
            ("hits", ctypes.c_uint64),
            ("purges", ctypes.c_uint64),
            ("purgeable_count", ctypes.c_uint64),
            ("speculative_count", ctypes.c_uint64),
            ("decompressions", ctypes.c_uint64),
            ("compressions", ctypes.c_uint64),
            ("swapins", ctypes.c_uint64),
            ("swapouts", ctypes.c_uint64),
            ("compressor_page_count", ctypes.c_uint64),
            ("throttled_count", ctypes.c_uint64),
            ("external_page_count", ctypes.c_uint64),
            ("internal_page_count", ctypes.c_uint64),
            ("total_uncompressed_pages_in_compressor", ctypes.c_uint64),
        ]

    libc.mach_host_self.restype = ctypes.c_uint
    libc.host_page_size.argtypes = [ctypes.c_uint, ctypes.POINTER(ctypes.c_uint)]
    libc.host_page_size.restype = ctypes.c_int
    libc.host_statistics64.argtypes = [
        ctypes.c_uint,
        ctypes.c_int,
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_uint),
    ]
    libc.host_statistics64.restype = ctypes.c_int

    host = libc.mach_host_self()
    page_size = ctypes.c_uint()
    if libc.host_page_size(host, ctypes.byref(page_size)) != 0:
        raise OSError("host_page_size failed")

    vm_stat = VMStatistics64()
    count = ctypes.c_uint(host_vm_info64_count)
    ret = libc.host_statistics64(
        host,
        host_vm_info64,
        ctypes.byref(vm_stat),
        ctypes.byref(count),
    )
    if ret != 0:
        raise OSError(f"host_statistics64 failed with code {ret}")
    free_pages = vm_stat.free_count + vm_stat.speculative_count
    return int(free_pages * page_size.value)
