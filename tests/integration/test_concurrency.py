import threading
import pytest
from dmemfs import MemoryFileSystem
from tests.helpers.concurrency import ThreadedLockHolder, run_concurrent


@pytest.fixture
def mfs():
    return MemoryFileSystem(max_quota=16 * 1024 * 1024)


def test_concurrent_reads(mfs):
    """Multiple threads can read the same file simultaneously."""
    with mfs.open("/shared.bin", "wb") as f:
        f.write(b"shared data " * 100)
    
    results = []
    errors = []
    lock = threading.Lock()
    
    def reader(_):
        try:
            with mfs.open("/shared.bin", "rb") as f:
                data = f.read()
            with lock:
                results.append(len(data))
        except Exception as e:
            with lock:
                errors.append(e)
    
    results, errors = run_concurrent(reader, n_threads=10)
    assert not any(e for e in errors)
    assert all(r == len(b"shared data " * 100) for r in results if r is not None)


def test_write_blocks_concurrent_write(mfs):
    """While one thread holds write lock, another writer should get BlockingIOError with timeout=0."""
    with mfs.open("/f.bin", "wb") as f:
        f.write(b"initial")
    
    with ThreadedLockHolder(mfs, "/f.bin", "wb") as holder:
        with pytest.raises(BlockingIOError):
            mfs.open("/f.bin", "wb", lock_timeout=0.0)


# --- v11 §19: PEP 703 stress tests ---


def test_concurrent_writes_no_data_corruption_stress(mfs):
    """複数スレッドが別々のファイルに書き込み、データ破壊が起きないことを検証。"""
    errors = []
    iterations = 100

    def writer(thread_id):
        try:
            for i in range(iterations):
                path = f"/file_{thread_id}.bin"
                with mfs.open(path, "wb") as f:
                    data = bytes([thread_id & 0xFF]) * 100
                    f.write(data)
                with mfs.open(path, "rb") as f:
                    result = f.read()
                assert result == bytes([thread_id & 0xFF]) * 100
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=writer, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30.0)
    assert not errors, f"Data corruption detected: {errors}"


def test_concurrent_stat_during_writes(mfs):
    """stat() と write() の並行実行でクラッシュしない。"""
    with mfs.open("/target.bin", "wb") as f:
        f.write(b"initial")

    errors = []
    stop = threading.Event()

    def writer():
        try:
            for i in range(50):
                if stop.is_set():
                    break
                with mfs.open("/target.bin", "wb") as f:
                    f.write(b"x" * (i + 1))
        except Exception as e:
            errors.append(e)

    def stat_reader():
        try:
            for _ in range(50):
                if stop.is_set():
                    break
                try:
                    info = mfs.stat("/target.bin")
                    assert "size" in info
                    assert "created_at" in info
                    assert "modified_at" in info
                except FileNotFoundError:
                    pass
        except Exception as e:
            errors.append(e)

    threads = [
        threading.Thread(target=writer, daemon=True),
        threading.Thread(target=stat_reader, daemon=True),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10.0)
    stop.set()
    assert not errors, f"Concurrent stat/write errors: {errors}"

