from __future__ import annotations

from unittest.mock import patch

import pytest

from dmemfs import AsyncMemoryFileSystem, MemoryFileSystem


def test_memory_guard_none_preserves_legacy_behavior():
    with patch("dmemfs._memory_guard.get_available_memory_bytes", return_value=1):
        mfs = MemoryFileSystem(max_quota=1024**3, memory_guard="none")
    assert mfs is not None


def test_memory_guard_init_warns_during_filesystem_init():
    with patch("dmemfs._memory_guard.get_available_memory_bytes", return_value=100):
        with pytest.warns(ResourceWarning, match="exceeds available physical RAM"):
            MemoryFileSystem(max_quota=200, memory_guard="init")


def test_memory_guard_init_raises_during_filesystem_init():
    with patch("dmemfs._memory_guard.get_available_memory_bytes", return_value=100):
        with pytest.raises(MemoryError, match="exceeds available physical RAM"):
            MemoryFileSystem(
                max_quota=200,
                memory_guard="init",
                memory_guard_action="raise",
            )


def test_memory_guard_per_write_checks_open_preallocate():
    mfs = MemoryFileSystem(max_quota=1024, memory_guard="per_write")
    with patch.object(mfs._memory_guard, "check_before_write") as check:
        with mfs.open("/f.bin", "wb", preallocate=8):
            pass
    check.assert_called_once()


def test_memory_guard_per_write_checks_handle_write_growth():
    mfs = MemoryFileSystem(max_quota=1024, memory_guard="per_write")
    with patch.object(mfs._memory_guard, "check_before_write") as check:
        with mfs.open("/f.bin", "wb") as f:
            f.write(b"abc")
    check.assert_called_once()


def test_memory_guard_per_write_checks_import_tree():
    mfs = MemoryFileSystem(max_quota=1024, memory_guard="per_write")
    with patch.object(mfs._memory_guard, "check_before_write") as check:
        mfs.import_tree({"/a.bin": b"abc"})
    check.assert_called_once()


def test_memory_guard_per_write_checks_copy_tree():
    mfs = MemoryFileSystem(max_quota=4096, memory_guard="per_write")
    mfs.mkdir("/src")
    with mfs.open("/src/a.bin", "wb") as f:
        f.write(b"abc")
    with patch.object(mfs._memory_guard, "check_before_write") as check:
        mfs.copy_tree("/src", "/dst")
    check.assert_called_once()


@pytest.mark.asyncio
async def test_async_memory_guard_parameters_are_forwarded():
    mfs = AsyncMemoryFileSystem(
        max_quota=1024,
        memory_guard="init",
        memory_guard_action="raise",
        memory_guard_interval=2.5,
    )
    assert mfs._sync._memory_guard.__class__.__name__ == "InitGuard"


def test_sequential_write_memoryerror_message_is_contextualized():
    class FailingList(list):
        def append(self, item):
            raise MemoryError

    mfs = MemoryFileSystem(max_quota=1024)
    with mfs.open("/f.bin", "wb") as f:
        storage = f._fnode.storage
        storage._chunks = FailingList()
        with pytest.raises(MemoryError, match="OS memory allocation failed while writing 3 bytes"):
            f.write(b"abc")


def test_randomaccess_truncate_expand_memoryerror_message_is_contextualized():
    class FailingBytearray(bytearray):
        def extend(self, data):
            raise MemoryError

    mfs = MemoryFileSystem(max_quota=1024, default_storage="random_access")
    with mfs.open("/f.bin", "wb") as f:
        storage = f._fnode.storage
        storage._buf = FailingBytearray(storage._buf)
        with pytest.raises(MemoryError, match="extending file to 10 bytes"):
            f.truncate(10)


def test_promotion_memoryerror_message_suggests_memory_guard():
    mfs = MemoryFileSystem(max_quota=1024)
    with mfs.open("/f.bin", "wb") as f:
        f.write(b"hello")
    with patch("dmemfs._file.bytearray", side_effect=MemoryError):
        with mfs.open("/f.bin", "r+b") as f:
            with pytest.raises(MemoryError, match="memory_guard='init'"):
                f.write(b"X")


def test_import_tree_memoryerror_message_includes_path():
    mfs = MemoryFileSystem(
        max_quota=1024,
        memory_guard="none",
        default_storage="random_access",
    )
    with patch("dmemfs._file.RandomAccessMemoryFile._bulk_load", side_effect=MemoryError):
        with pytest.raises(MemoryError, match="/a.bin"):
            mfs.import_tree({"/a.bin": b"abc"})
