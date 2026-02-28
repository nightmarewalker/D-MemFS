"""Tests for the default_storage parameter of MemoryFileSystem."""

import io
import pytest
from dmemfs import MemoryFileSystem
from dmemfs._file import SequentialMemoryFile, RandomAccessMemoryFile


def _get_storage(mfs, path):
    """Helper to introspect the storage object of a file node."""
    npath = mfs._np(path)
    fnode = mfs._resolve_path(npath)
    return fnode.storage


# ---------------------------------------------------------------------------
# "auto" mode (default) -- Sequential with promotion enabled
# ---------------------------------------------------------------------------

def test_auto_is_default():
    mfs = MemoryFileSystem()
    assert mfs._default_storage == "auto"


def test_auto_creates_sequential_file():
    mfs = MemoryFileSystem(default_storage="auto")
    with mfs.open("/f.bin", "wb") as h:
        h.write(b"hello")
    storage = _get_storage(mfs, "/f.bin")
    assert isinstance(storage, SequentialMemoryFile)


def test_auto_promotes_on_seek_write():
    """In 'auto' mode, a seek+write should promote to RandomAccessMemoryFile."""
    mfs = MemoryFileSystem(default_storage="auto")
    with mfs.open("/f.bin", "wb") as h:
        h.write(b"hello world")
    with mfs.open("/f.bin", "r+b") as h:
        h.seek(0)
        h.write(b"HELLO")
    storage = _get_storage(mfs, "/f.bin")
    assert isinstance(storage, RandomAccessMemoryFile)


# ---------------------------------------------------------------------------
# "sequential" mode -- Sequential with promotion disabled
# ---------------------------------------------------------------------------

def test_sequential_creates_sequential_file():
    mfs = MemoryFileSystem(default_storage="sequential")
    with mfs.open("/f.bin", "wb") as h:
        h.write(b"hello")
    storage = _get_storage(mfs, "/f.bin")
    assert isinstance(storage, SequentialMemoryFile)
    assert not storage._allow_promotion


def test_sequential_no_promotion_on_seek_write():
    """In 'sequential' mode, a seek+write should raise UnsupportedOperation."""
    mfs = MemoryFileSystem(default_storage="sequential")
    with mfs.open("/f.bin", "wb") as h:
        h.write(b"hello world")
    with mfs.open("/f.bin", "r+b") as h:
        h.seek(0)
        with pytest.raises(io.UnsupportedOperation):
            h.write(b"HELLO")


def test_sequential_append_write_works():
    """In 'sequential' mode, append-only writes work fine."""
    mfs = MemoryFileSystem(default_storage="sequential")
    with mfs.open("/f.bin", "wb") as h:
        h.write(b"hello")
    with mfs.open("/f.bin", "ab") as h:
        h.write(b" world")
    with mfs.open("/f.bin", "rb") as h:
        assert h.read() == b"hello world"


# ---------------------------------------------------------------------------
# "random_access" mode -- always RandomAccessMemoryFile
# ---------------------------------------------------------------------------

def test_random_access_creates_random_access_file():
    mfs = MemoryFileSystem(default_storage="random_access")
    with mfs.open("/f.bin", "wb") as h:
        h.write(b"hello")
    storage = _get_storage(mfs, "/f.bin")
    assert isinstance(storage, RandomAccessMemoryFile)


def test_random_access_seek_write_works():
    """In 'random_access' mode, seek+write works without promotion."""
    mfs = MemoryFileSystem(default_storage="random_access")
    with mfs.open("/f.bin", "wb") as h:
        h.write(b"hello world")
    with mfs.open("/f.bin", "r+b") as h:
        h.seek(0)
        h.write(b"HELLO")
    with mfs.open("/f.bin", "rb") as h:
        assert h.read() == b"HELLO world"


# ---------------------------------------------------------------------------
# Invalid value
# ---------------------------------------------------------------------------

def test_invalid_default_storage_raises_value_error():
    with pytest.raises(ValueError, match="Invalid default_storage"):
        MemoryFileSystem(default_storage="invalid")
