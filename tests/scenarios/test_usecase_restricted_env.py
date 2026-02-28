"""Restricted environment use case: quota enforcement."""
import pytest
from dmemfs import MemoryFileSystem
from dmemfs._exceptions import MFSQuotaExceededError


def test_quota_prevents_overflow():
    """System enforces hard quota limit."""
    mfs = MemoryFileSystem(max_quota=1024)
    
    with pytest.raises(MFSQuotaExceededError) as exc_info:
        with mfs.open("/big.bin", "wb") as f:
            f.write(b"x" * 10000)
    
    assert exc_info.value.requested > 0
    assert exc_info.value.available >= 0


def test_quota_freed_after_delete():
    """After deleting files, quota is freed for reuse."""
    mfs = MemoryFileSystem(max_quota=2048, chunk_overhead_override=0)
    
    with mfs.open("/f.bin", "wb") as f:
        f.write(b"x" * 1000)
    
    mfs.remove("/f.bin")
    
    # Should now be able to write again
    with mfs.open("/f2.bin", "wb") as f:
        f.write(b"y" * 1000)
    
    with mfs.open("/f2.bin", "rb") as f:
        assert f.read() == b"y" * 1000


def test_partial_write_on_quota_exceeded():
    """On quota exceeded, no partial state left in file."""
    mfs = MemoryFileSystem(max_quota=500, chunk_overhead_override=0)
    
    # Write some data
    with mfs.open("/f.bin", "wb") as f:
        f.write(b"x" * 100)
    
    # Try to write more than remaining quota
    with pytest.raises(MFSQuotaExceededError):
        with mfs.open("/f.bin", "ab") as f:
            f.write(b"y" * 1000)
    
    # File should still have only original data
    with mfs.open("/f.bin", "rb") as f:
        data = f.read()
    assert data == b"x" * 100
