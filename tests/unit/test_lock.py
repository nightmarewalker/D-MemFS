import threading
import pytest
from dmemfs._lock import ReadWriteLock


def test_read_lock_basic():
    lock = ReadWriteLock()
    lock.acquire_read()
    assert lock.is_locked
    lock.release_read()
    assert not lock.is_locked


def test_write_lock_basic():
    lock = ReadWriteLock()
    lock.acquire_write()
    assert lock.is_locked
    lock.release_write()
    assert not lock.is_locked


def test_multiple_readers_allowed():
    """Three threads can concurrently hold read locks (simultaneous acquisition)."""
    lock = ReadWriteLock()
    acquired: list[bool] = []
    barrier = threading.Barrier(3)

    def reader():
        lock.acquire_read()
        barrier.wait()  # all three must have the lock before any records
        acquired.append(True)
        lock.release_read()

    threads = [threading.Thread(target=reader) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5.0)
    assert len(acquired) == 3  # none were blocked


def test_write_blocks_while_read_held():
    lock = ReadWriteLock()
    lock.acquire_read()
    with pytest.raises(BlockingIOError):
        lock.acquire_write(timeout=0.0)
    lock.release_read()


def test_read_blocks_while_write_held():
    lock = ReadWriteLock()
    lock.acquire_write()
    with pytest.raises(BlockingIOError):
        lock.acquire_read(timeout=0.0)
    lock.release_write()


def test_write_blocks_while_write_held():
    lock = ReadWriteLock()
    lock.acquire_write()
    with pytest.raises(BlockingIOError):
        lock.acquire_write(timeout=0.0)
    lock.release_write()


def test_read_released_allows_write():
    lock = ReadWriteLock()
    lock.acquire_read()
    lock.release_read()
    lock.acquire_write()  # Should not raise
    lock.release_write()


def test_write_released_allows_read():
    lock = ReadWriteLock()
    lock.acquire_write()
    lock.release_write()
    lock.acquire_read()  # Should not raise
    lock.release_read()


def test_concurrent_read_write():
    """Multiple readers can hold lock simultaneously, writer waits."""
    lock = ReadWriteLock()
    results = []
    barrier = threading.Barrier(3)

    def reader(idx):
        lock.acquire_read()
        barrier.wait()
        results.append(f"read{idx}")
        lock.release_read()

    def writer():
        barrier.wait()
        lock.acquire_write(timeout=2.0)
        results.append("write")
        lock.release_write()

    threads = [
        threading.Thread(target=reader, args=(1,)),
        threading.Thread(target=reader, args=(2,)),
        threading.Thread(target=writer),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5.0)

    assert "write" in results
    assert "read1" in results
    assert "read2" in results


def test_lock_timeout_raises():
    lock = ReadWriteLock()
    lock.acquire_write()
    with pytest.raises(BlockingIOError):
        lock.acquire_read(timeout=0.05)
    lock.release_write()


def test_acquire_write_timeout_raises():
    """acquire_write が有限タイムアウトで BlockingIOError を送出する。"""
    lock = ReadWriteLock()
    lock.acquire_read()
    with pytest.raises(BlockingIOError):
        lock.acquire_write(timeout=0.05)
    lock.release_read()


def test_acquire_read_with_none_timeout_waits():
    """timeout=None で acquire_read が write 解放後に成功する（_remaining None 分岐）。"""
    lock = ReadWriteLock()
    lock.acquire_write()
    acquired = threading.Event()

    def waiter():
        lock.acquire_read(timeout=None)  # 無限待ち → _remaining returns None
        acquired.set()
        lock.release_read()

    t = threading.Thread(target=waiter, daemon=True)
    t.start()
    lock.release_write()
    assert acquired.wait(timeout=3.0)
    t.join(timeout=3.0)


def test_release_read_without_acquire_raises():
    """release_read without matching acquire_read raises RuntimeError."""
    lock = ReadWriteLock()
    with pytest.raises(RuntimeError, match="release_read called without matching acquire_read"):
        lock.release_read()


def test_release_write_without_acquire_raises():
    """release_write without matching acquire_write raises RuntimeError."""
    lock = ReadWriteLock()
    with pytest.raises(RuntimeError, match="release_write called without matching acquire_write"):
        lock.release_write()
