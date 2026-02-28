import pytest
from dmemfs._file import RandomAccessMemoryFile
from dmemfs._quota import QuotaManager
from dmemfs._exceptions import MFSQuotaExceededError


def make_qm(size=10 * 1024 * 1024):
    return QuotaManager(size)


def test_initial_state():
    f = RandomAccessMemoryFile()
    assert f.get_size() == 0


def test_write_and_read():
    f = RandomAccessMemoryFile()
    qm = make_qm()
    f.write_at(0, b"hello", qm)
    assert f.read_at(0, 5) == b"hello"


def test_overwrite_inplace():
    f = RandomAccessMemoryFile()
    qm = make_qm()
    f.write_at(0, b"hello", qm)
    initial_used = qm.used
    f.write_at(0, b"world", qm)
    assert f.read_at(0, 5) == b"world"
    assert qm.used == initial_used  # pure overwrite, no new quota consumed


def test_write_gap_fills_zeros():
    f = RandomAccessMemoryFile()
    qm = make_qm()
    f.write_at(0, b"hello", qm)
    f.write_at(10, b"world", qm)
    assert f.get_size() == 15
    assert f.read_at(5, 5) == b"\x00\x00\x00\x00\x00"


def test_truncate():
    f = RandomAccessMemoryFile()
    qm = make_qm()
    f.write_at(0, b"hello world", qm)
    f.truncate(5, qm)
    assert f.get_size() == 5
    assert f.read_at(0, 5) == b"hello"


def test_write_exceeds_quota():
    f = RandomAccessMemoryFile()
    qm = QuotaManager(3)
    with pytest.raises(MFSQuotaExceededError):
        f.write_at(0, b"hello", qm)
    assert f.get_size() == 0


# --- v11: bytearray shrink tests ---


def test_truncate_shrinks_buffer_below_threshold():
    """サイズが元の25%以下に縮小した場合、バッファが再割り当てされる。"""
    f = RandomAccessMemoryFile()
    qm = make_qm()
    f.write_at(0, b"\x00" * 10000, qm)
    old_buf_id = id(f._buf)
    f.truncate(100, qm)  # 100 / 10000 = 1% → shrink
    assert f.get_size() == 100
    assert id(f._buf) != old_buf_id  # バッファが再割り当てされた


def test_truncate_no_shrink_above_threshold():
    """サイズが25%超に留まる場合は再割り当てされない。"""
    f = RandomAccessMemoryFile()
    qm = make_qm()
    f.write_at(0, b"\x00" * 100, qm)
    old_buf_id = id(f._buf)
    f.truncate(50, qm)  # 50 / 100 = 50% → no shrink
    assert f.get_size() == 50
    assert id(f._buf) == old_buf_id


def test_shrink_preserves_data():
    """shrink後もデータが正しく読み取れる。"""
    f = RandomAccessMemoryFile()
    qm = make_qm()
    data = b"ABCDEFGHIJ" * 100  # 1000 bytes
    f.write_at(0, data, qm)
    f.truncate(50, qm)  # 50 / 1000 = 5% → shrink
    assert f.read_at(0, 50) == data[:50]


def test_shrink_quota_consistency():
    """shrink前後でクォータ計上値が正しい。"""
    f = RandomAccessMemoryFile()
    qm = QuotaManager(20000)
    f.write_at(0, b"\x00" * 10000, qm)
    assert qm.used == 10000
    f.truncate(100, qm)  # shrink triggers
    assert qm.used == 100
    assert f.get_quota_usage() == 100


def test_truncate_to_zero_shrinks():
    """サイズ0への truncate で shrink が実行される。"""
    f = RandomAccessMemoryFile()
    qm = make_qm()
    f.write_at(0, b"\x00" * 1000, qm)
    old_buf_id = id(f._buf)
    f.truncate(0, qm)
    assert f.get_size() == 0
    assert id(f._buf) != old_buf_id


def test_read_at_negative_size_returns_all():
    """read_at に size=-1 を渡すと offset 以降の全バイトを返す。"""
    f = RandomAccessMemoryFile()
    qm = make_qm()
    f.write_at(0, b"hello world", qm)
    assert f.read_at(6, -1) == b"world"


def test_write_at_empty_data_is_noop():
    """write_at に空バイト列を渡すとクォータを消費しない。"""
    f = RandomAccessMemoryFile()
    qm = make_qm()
    f.write_at(0, b"hello", qm)
    used_before = qm.used
    result_n, _, _ = f.write_at(0, b"", qm)
    assert result_n == 0
    assert qm.used == used_before


def test_truncate_same_size_is_noop():
    """truncate に同サイズを渡しても何も変化しない。"""
    f = RandomAccessMemoryFile()
    qm = make_qm()
    f.write_at(0, b"hello", qm)
    used_before = qm.used
    f.truncate(5, qm)  # same size
    assert f.get_size() == 5
    assert qm.used == used_before
    assert qm.used == used_before


def test_truncate_extends_with_zeros():
    """truncate(size > current) はゼロバイトで拡張する（POSIX互換）。"""
    f = RandomAccessMemoryFile()
    qm = make_qm()
    f.write_at(0, b"hello", qm)
    f.truncate(10, qm)
    assert f.get_size() == 10
    assert f.read_at(0, 10) == b"hello\x00\x00\x00\x00\x00"


def test_truncate_extend_consumes_quota():
    """truncate による拡張はクォータを消費する。"""
    f = RandomAccessMemoryFile()
    qm = QuotaManager(100)
    f.write_at(0, b"hello", qm)
    assert qm.used == 5
    f.truncate(10, qm)
    assert qm.used == 10


def test_truncate_extend_exceeds_quota():
    """truncate による拡張がクォータを超えると例外。"""
    f = RandomAccessMemoryFile()
    qm = QuotaManager(7)
    f.write_at(0, b"hello", qm)
    with pytest.raises(MFSQuotaExceededError):
        f.truncate(10, qm)
    assert f.get_size() == 5