import io
import pytest
from dmemfs import MemoryFileSystem
from dmemfs._exceptions import MFSQuotaExceededError


def test_rb_reads_existing():
    """rb モードで既存ファイルの内容を正しく取得できる（FS API契約）。"""
    mfs = MemoryFileSystem()
    with mfs.open("/f.bin", "wb") as f:
        f.write(b"data")
    with mfs.open("/f.bin", "rb") as f:
        assert f.read() == b"data"


def test_rb_nonexistent_raises():
    mfs = MemoryFileSystem()
    with pytest.raises(FileNotFoundError):
        mfs.open("/nope.bin", "rb")


def test_wb_creates_file():
    mfs = MemoryFileSystem()
    with mfs.open("/new.bin", "wb") as f:
        f.write(b"created")
    assert mfs.exists("/new.bin")


def test_wb_overwrites_existing():
    """wb で開くと既存ファイルが上書きされ FS の状態が更新される。"""
    mfs = MemoryFileSystem()
    with mfs.open("/f.bin", "wb") as f:
        f.write(b"original content")
    with mfs.open("/f.bin", "wb") as f:
        f.write(b"new")
    with mfs.open("/f.bin", "rb") as f:
        assert f.read() == b"new"


def test_ab_creates_if_not_exists():
    mfs = MemoryFileSystem()
    with mfs.open("/f.bin", "ab") as f:
        f.write(b"first")
    with mfs.open("/f.bin", "rb") as f:
        assert f.read() == b"first"


def test_ab_appends_to_existing():
    """ab モードで既存ファイルへの追記が FS レベルで反映される。"""
    mfs = MemoryFileSystem()
    with mfs.open("/f.bin", "wb") as f:
        f.write(b"hello")
    with mfs.open("/f.bin", "ab") as f:
        f.write(b" world")
    with mfs.open("/f.bin", "rb") as f:
        assert f.read() == b"hello world"


def test_rplusb_reads_and_writes():
    """r+b モードで読み書き後の FS 上のデータが正しく更新される。"""
    mfs = MemoryFileSystem()
    with mfs.open("/f.bin", "wb") as f:
        f.write(b"hello world")
    with mfs.open("/f.bin", "r+b") as f:
        f.seek(0)
        data = f.read(5)
        assert data == b"hello"
        f.seek(6)
        f.write(b"MFS  ")
    with mfs.open("/f.bin", "rb") as f:
        assert f.read() == b"hello MFS  "


def test_rplusb_nonexistent_raises():
    mfs = MemoryFileSystem()
    with pytest.raises(FileNotFoundError):
        mfs.open("/nope.bin", "r+b")


def test_xb_exclusive_create():
    """xb モードでの排他新規作成が FS に正しく反映される。"""
    mfs = MemoryFileSystem()
    with mfs.open("/f.bin", "xb") as f:
        f.write(b"exclusive")
    with mfs.open("/f.bin", "rb") as f:
        assert f.read() == b"exclusive"


def test_xb_raises_if_exists():
    """xb モードで既存ファイルを開くと FS レベルで FileExistsError が送出される。"""
    mfs = MemoryFileSystem()
    with mfs.open("/f.bin", "wb") as f:
        f.write(b"exists")
    with pytest.raises(FileExistsError):
        mfs.open("/f.bin", "xb")


def test_invalid_mode_raises():
    mfs = MemoryFileSystem()
    with pytest.raises(ValueError):
        mfs.open("/f.bin", "r")


def test_open_directory_raises():
    mfs = MemoryFileSystem()
    mfs.mkdir("/mydir")
    with pytest.raises(IsADirectoryError):
        mfs.open("/mydir", "rb")


def test_write_quota_exceeded(mfs):
    mfs2 = MemoryFileSystem(max_quota=10)
    with pytest.raises(MFSQuotaExceededError):
        with mfs2.open("/f.bin", "wb") as f:
            f.write(b"x" * 100)


def test_multiple_readers_concurrent():
    import threading

    mfs = MemoryFileSystem()
    with mfs.open("/f.bin", "wb") as f:
        f.write(b"shared data")

    results = []
    lock = threading.Lock()

    def reader():
        with mfs.open("/f.bin", "rb") as f:
            data = f.read()
            with lock:
                results.append(data)

    threads = [threading.Thread(target=reader) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert all(d == b"shared data" for d in results)


def test_write_to_parent_not_exists_raises():
    mfs = MemoryFileSystem()
    with pytest.raises(FileNotFoundError):
        mfs.open("/nodir/f.bin", "wb")


def test_wb_quota_freed_after_truncate(mfs):
    """Opening in wb mode should free old file quota."""
    with mfs.open("/f.bin", "wb") as f:
        f.write(b"x" * 500)
    used_after_first = mfs.stats()["used_bytes"]
    with mfs.open("/f.bin", "wb") as f:
        f.write(b"small")
    used_after_second = mfs.stats()["used_bytes"]
    assert used_after_second < used_after_first


def test_preallocate_allocates_space(mfs):
    """preallocate 指定で FS のクォータ使用量が即座に増加する。"""
    with mfs.open("/f.bin", "wb", preallocate=1000) as f:
        pass
    assert mfs.stats()["used_bytes"] >= 1000


def test_read_empty_file():
    mfs = MemoryFileSystem()
    with mfs.open("/f.bin", "wb") as f:
        pass
    with mfs.open("/f.bin", "rb") as f:
        assert f.read() == b""


def test_multiple_writes_and_reads(mfs):
    with mfs.open("/f.bin", "wb") as f:
        for i in range(10):
            f.write(bytes([i]) * 100)
    with mfs.open("/f.bin", "rb") as f:
        data = f.read()
    assert len(data) == 1000


# --- v10: wb truncate lock order tests ---


def test_wb_truncate_after_lock_acquisition(mfs):
    """v10: wb truncate はロック取得後に実行される。"""
    with mfs.open("/f.bin", "wb") as f:
        f.write(b"original data")
    # wb で再度開くと lock 取得後に truncate が実行される
    with mfs.open("/f.bin", "wb") as f:
        pass  # close = truncate 済み (size=0 のまま)
    with mfs.open("/f.bin", "rb") as f:
        assert f.read() == b""


def test_wb_truncate_does_not_corrupt_concurrent_reader(mfs):
    """v10: reader が rb ロック保有中に wb で開こうとすると BlockingIOError。"""
    import threading

    with mfs.open("/f.bin", "wb") as f:
        f.write(b"original data")

    reader_data = [None]
    reader_ready = threading.Event()
    writer_proceed = threading.Event()

    def reader():
        with mfs.open("/f.bin", "rb") as f:
            reader_ready.set()
            writer_proceed.wait(timeout=5.0)
            reader_data[0] = f.read()

    t = threading.Thread(target=reader, daemon=True)
    t.start()
    reader_ready.wait(timeout=5.0)

    # reader が rb ロックを保有中に wb で開こうとすると即座に失敗
    with pytest.raises(BlockingIOError):
        mfs.open("/f.bin", "wb", lock_timeout=0.0)

    writer_proceed.set()
    t.join(timeout=5.0)
    assert reader_data[0] == b"original data"
