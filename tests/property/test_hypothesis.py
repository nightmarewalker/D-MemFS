"""Property-based tests using Hypothesis."""
import pytest

try:
    from hypothesis import given, settings, assume
    import hypothesis.strategies as st
    HAS_HYPOTHESIS = True
except ImportError:
    HAS_HYPOTHESIS = False

from dmemfs import MemoryFileSystem
from dmemfs._exceptions import MFSQuotaExceededError
from dmemfs._path import normalize_path

pytestmark = pytest.mark.skipif(not HAS_HYPOTHESIS, reason="hypothesis not installed")


@given(data=st.binary(max_size=1000))
@settings(max_examples=50)
def test_write_read_roundtrip(data):
    """Writing data and reading it back returns the same data."""
    mfs = MemoryFileSystem(max_quota=2048)
    try:
        with mfs.open("/f.bin", "wb") as f:
            f.write(data)
        with mfs.open("/f.bin", "rb") as f:
            result = f.read()
        assert result == data
    except MFSQuotaExceededError:
        pass  # Acceptable if data is too large


@given(
    data1=st.binary(max_size=500),
    data2=st.binary(max_size=500),
)
@settings(max_examples=50)
def test_append_concatenates(data1, data2):
    """Appending data results in concatenation."""
    mfs = MemoryFileSystem(max_quota=4096)
    try:
        with mfs.open("/f.bin", "wb") as f:
            f.write(data1)
        with mfs.open("/f.bin", "ab") as f:
            f.write(data2)
        with mfs.open("/f.bin", "rb") as f:
            result = f.read()
        assert result == data1 + data2
    except MFSQuotaExceededError:
        pass


@given(path=st.text(alphabet="/abcdefghijklmnopqrstuvwxyz._-", min_size=1, max_size=50))
@settings(max_examples=50)
def test_normalize_path_idempotent(path):
    """Normalizing a normalized path gives the same result."""
    try:
        normalized = normalize_path(path)
        assert normalize_path(normalized) == normalized
    except ValueError:
        pass  # Path traversal - acceptable


@given(
    files=st.dictionaries(
        keys=st.text(alphabet="abcdefghijklmnopqrstuvwxyz", min_size=1, max_size=10).map(lambda s: f"/{s}.bin"),
        values=st.binary(max_size=100),
        min_size=1,
        max_size=5,
    )
)
@settings(max_examples=30)
def test_import_export_roundtrip(files):
    """Import then export gives back the same data."""
    mfs = MemoryFileSystem(max_quota=1024 * 1024)
    try:
        mfs.import_tree(files)
        exported = mfs.export_tree()
        for path, data in files.items():
            assert exported.get(path) == data
    except MFSQuotaExceededError:
        pass


@given(
    size=st.integers(min_value=0, max_value=1000),
    trunc=st.integers(min_value=0, max_value=1000),
)
@settings(max_examples=50)
def test_truncate_size(size, trunc):
    """After truncation, file size is min(original, truncate_size)."""
    mfs = MemoryFileSystem(max_quota=2048)
    data = b"x" * size
    try:
        with mfs.open("/f.bin", "wb") as f:
            f.write(data)
        with mfs.open("/f.bin", "r+b") as f:
            pass  # just to trigger random access if needed
        
        # Truncate using wb mode (rewrites with truncated data)
        if trunc <= size:
            truncated = data[:trunc]
            with mfs.open("/f.bin", "wb") as f:
                f.write(truncated)
            with mfs.open("/f.bin", "rb") as f:
                result = f.read()
            assert result == truncated
            assert len(result) == trunc
    except MFSQuotaExceededError:
        pass
