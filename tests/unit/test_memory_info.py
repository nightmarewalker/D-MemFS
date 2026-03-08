from __future__ import annotations

from unittest.mock import mock_open, patch

import dmemfs._memory_info as mi


def test_get_available_memory_returns_positive_int_or_none():
    result = mi.get_available_memory_bytes()
    if result is not None:
        assert isinstance(result, int)
        assert result > 0


def test_windows_reader_failure_returns_none():
    with patch.object(mi, "_SYSTEM", "Windows"):
        with patch.object(mi, "_windows_avail", side_effect=OSError("boom")):
            assert mi.get_available_memory_bytes() is None


def test_probe_linux_source_prefers_cgroup_v2():
    with patch.object(mi, "_is_cgroup_v2_limited", return_value=True):
        with patch.object(mi, "_is_cgroup_v1_limited", return_value=True):
            assert mi._probe_linux_source() is mi._read_cgroup_v2


def test_probe_linux_source_falls_back_to_cgroup_v1():
    with patch.object(mi, "_is_cgroup_v2_limited", return_value=False):
        with patch.object(mi, "_is_cgroup_v1_limited", return_value=True):
            assert mi._probe_linux_source() is mi._read_cgroup_v1


def test_probe_linux_source_falls_back_to_procmeminfo():
    with patch.object(mi, "_is_cgroup_v2_limited", return_value=False):
        with patch.object(mi, "_is_cgroup_v1_limited", return_value=False):
            with patch.object(mi, "_is_procmeminfo_available", return_value=True):
                assert mi._probe_linux_source() is mi._read_procmeminfo


def test_linux_probe_result_is_cached():
    original = mi._linux_reader
    mi._linux_reader = mi._UNPROBED
    try:
        with patch.object(mi, "_probe_linux_source", return_value=lambda: 42) as probe:
            assert mi._linux_avail() == 42
            assert mi._linux_avail() == 42
            probe.assert_called_once()
    finally:
        mi._linux_reader = original


def test_read_cgroup_v2_runtime_max_returns_none():
    def fake_open(path: str, *args, **kwargs):
        files = {
            "/sys/fs/cgroup/memory.max": "max",
            "/sys/fs/cgroup/memory.current": "1048576",
        }
        if path in files:
            return mock_open(read_data=files[path])()
        raise FileNotFoundError(path)

    with patch("builtins.open", side_effect=fake_open):
        assert mi._read_cgroup_v2() is None


def test_read_cgroup_v1_returns_limit_minus_usage():
    def fake_open(path: str, *args, **kwargs):
        files = {
            "/sys/fs/cgroup/memory/memory.limit_in_bytes": str(2 * 1024**3),
            "/sys/fs/cgroup/memory/memory.usage_in_bytes": str(512 * 1024**2),
        }
        if path in files:
            return mock_open(read_data=files[path])()
        raise FileNotFoundError(path)

    with patch("builtins.open", side_effect=fake_open):
        assert mi._read_cgroup_v1() == (2 * 1024**3) - (512 * 1024**2)
