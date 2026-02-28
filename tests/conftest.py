import pytest
from dmemfs import MemoryFileSystem


@pytest.fixture
def mfs() -> MemoryFileSystem:
    """デフォルトの mfs フィクスチャ（max_quota=1MiB）。"""
    return MemoryFileSystem(max_quota=1 * 1024 * 1024)
