import pytest
from dmemfs._file import (
    SequentialMemoryFile,
    RandomAccessMemoryFile,
    CHUNK_OVERHEAD_ESTIMATE,
)
from dmemfs._quota import QuotaManager
from dmemfs._exceptions import MFSQuotaExceededError


def make_qm(size=10 * 1024 * 1024):
    return QuotaManager(size)


def test_initial_state():
    f = SequentialMemoryFile(chunk_overhead=0)
    assert f.get_size() == 0


def test_sequential_write_and_read():
    f = SequentialMemoryFile(chunk_overhead=0)
    qm = make_qm()
    f.write_at(0, b"hello", qm)
    f.write_at(5, b" world", qm)
    assert f.get_size() == 11
    assert f.read_at(0, 11) == b"hello world"


def test_write_advances_size():
    f = SequentialMemoryFile(chunk_overhead=0)
    qm = make_qm()
    f.write_at(0, b"abc", qm)
    assert f.get_size() == 3


def test_read_partial():
    f = SequentialMemoryFile(chunk_overhead=0)
    qm = make_qm()
    f.write_at(0, b"hello world", qm)
    assert f.read_at(6, 5) == b"world"


def test_read_beyond_size_returns_empty():
    f = SequentialMemoryFile(chunk_overhead=0)
    qm = make_qm()
    f.write_at(0, b"abc", qm)
    assert f.read_at(10, 5) == b""


def test_write_quota_consumed():
    f = SequentialMemoryFile(chunk_overhead=0)
    qm = QuotaManager(5)
    f.write_at(0, b"hello", qm)
    assert qm.used == 5


def test_write_exceeds_quota():
    f = SequentialMemoryFile(chunk_overhead=0)
    qm = QuotaManager(4)
    with pytest.raises(MFSQuotaExceededError):
        f.write_at(0, b"hello", qm)
    assert f.get_size() == 0


def test_truncate_reduces_size():
    f = SequentialMemoryFile(chunk_overhead=0)
    qm = make_qm()
    f.write_at(0, b"hello world", qm)
    f.truncate(5, qm)
    assert f.get_size() == 5
    assert f.read_at(0, 5) == b"hello"


def test_truncate_releases_quota():
    f = SequentialMemoryFile(chunk_overhead=0)
    qm = QuotaManager(100)
    f.write_at(0, b"hello world", qm)
    used_after_write = qm.used
    f.truncate(5, qm)
    assert qm.used < used_after_write


def test_non_sequential_write_triggers_promotion():
    """Non-tail write returns (written, promoted_file, old_data_size) tuple."""
    f = SequentialMemoryFile(chunk_overhead=0)
    qm = make_qm()
    f.write_at(0, b"hello", qm)
    written, promoted, old_data_size = f.write_at(0, b"X", qm)  # offset != size
    assert isinstance(promoted, RandomAccessMemoryFile)
    assert written == 1
    assert old_data_size == 5  # old sequential data size


def test_chunk_overhead_accounted():
    overhead = 100
    f = SequentialMemoryFile(chunk_overhead=overhead)
    qm = QuotaManager(200)
    f.write_at(0, b"abc", qm)  # 3 data + 100 overhead = 103
    assert qm.used == 103


def test_truncate_extends_with_zeros():
    """truncate(size > current) はゼロバイトで拡張する（POSIX互換）。"""
    f = SequentialMemoryFile(chunk_overhead=0)
    qm = make_qm()
    f.write_at(0, b"hello", qm)
    f.truncate(10, qm)
    assert f.get_size() == 10
    assert f.read_at(0, 10) == b"hello\x00\x00\x00\x00\x00"


def test_truncate_extend_consumes_quota():
    """truncate による拡張はクォータを消費する。"""
    f = SequentialMemoryFile(chunk_overhead=0)
    qm = QuotaManager(100)
    f.write_at(0, b"hello", qm)
    assert qm.used == 5
    f.truncate(10, qm)
    assert qm.used == 10


def test_truncate_extend_exceeds_quota():
    """truncate による拡張がクォータを超えると例外。"""
    f = SequentialMemoryFile(chunk_overhead=0)
    qm = QuotaManager(7)
    f.write_at(0, b"hello", qm)
    with pytest.raises(MFSQuotaExceededError):
        f.truncate(10, qm)
    # サイズは変化しない
    assert f.get_size() == 5


def test_promotion_hard_limit_raises():
    """512MB を超えたシーケンシャルファイルへの非末尾書き込みは UnsupportedOperation。"""
    import io

    f = SequentialMemoryFile(chunk_overhead=0)
    qm = make_qm(size=2 * 1024 * 1024 * 1024)  # 2GB クォータ
    # 内部サイズを DEFAULT_PROMOTION_HARD_LIMIT 超えに偽装（実メモリは確保しない）
    f._size = SequentialMemoryFile.DEFAULT_PROMOTION_HARD_LIMIT + 1
    # offset != _size → _promote_and_write → ハードリミット判定
    with pytest.raises(io.UnsupportedOperation):
        f.write_at(0, b"x", qm)
