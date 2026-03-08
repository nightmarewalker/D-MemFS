from __future__ import annotations

from unittest.mock import patch

import pytest

from dmemfs._memory_guard import NullGuard, create_memory_guard


def test_create_memory_guard_invalid_mode_raises():
    with pytest.raises(ValueError, match="Invalid memory_guard"):
        create_memory_guard("bad")


def test_create_memory_guard_invalid_action_raises():
    with pytest.raises(ValueError, match="Invalid memory_guard_action"):
        create_memory_guard("init", action="bad")


def test_null_guard_is_noop():
    guard = NullGuard()
    guard.check_init(10)
    guard.check_before_write(10)


def test_init_guard_warns_when_quota_exceeds_available_memory():
    with patch("dmemfs._memory_guard.get_available_memory_bytes", return_value=100):
        guard = create_memory_guard("init", action="warn")
        with pytest.warns(ResourceWarning, match="exceeds available physical RAM"):
            guard.check_init(200)


def test_init_guard_raises_when_configured():
    with patch("dmemfs._memory_guard.get_available_memory_bytes", return_value=100):
        guard = create_memory_guard("init", action="raise")
        with pytest.raises(MemoryError, match="exceeds available physical RAM"):
            guard.check_init(200)


def test_per_write_guard_uses_cached_value_within_interval():
    with patch("dmemfs._memory_guard.get_available_memory_bytes", return_value=1000) as get_mem:
        guard = create_memory_guard("per_write", interval=60.0)
        guard.check_init(100)
        guard.check_before_write(10)
        guard.check_before_write(10)
        assert get_mem.call_count == 1


def test_per_write_guard_warns_on_insufficient_memory():
    with patch("dmemfs._memory_guard.get_available_memory_bytes", return_value=100):
        guard = create_memory_guard("per_write", action="warn", interval=60.0)
        guard.check_init(10)
        with pytest.warns(ResourceWarning, match="Write of 200 bytes requested"):
            guard.check_before_write(200)


def test_per_write_guard_raises_on_insufficient_memory():
    with patch("dmemfs._memory_guard.get_available_memory_bytes", return_value=100):
        guard = create_memory_guard("per_write", action="raise", interval=60.0)
        guard.check_init(10)
        with pytest.raises(MemoryError, match="Write of 200 bytes requested"):
            guard.check_before_write(200)
