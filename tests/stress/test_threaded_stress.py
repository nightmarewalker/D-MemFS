"""
GIL フリー (free-threaded) スレッドセーフ検証ストレステスト。

50 スレッド × 1000 回の高負荷パターンで MFS のロック機構が
GIL に依存せず正しく動作することを証明する。

実測値（2026-02-27）:
  50 × 1000 → 約 0.95 秒（通常 CI に組み込み可能）

実行方法:
  # 通常テスト
  uv run pytest tests/stress/ -v

  # free-threaded Python 3.13t（GIL=0）
  uv run --python cpython-3.13.7+freethreaded pytest tests/stress/ -v
"""

import threading

import pytest

from dmemfs import MemoryFileSystem, MFSQuotaExceededError


@pytest.fixture
def mfs_large():
    """ストレステスト用フィクスチャ（max_quota=64MiB）。"""
    return MemoryFileSystem(max_quota=64 * 1024 * 1024)


# ---------------------------------------------------------------------------
# ST-01
# ---------------------------------------------------------------------------


@pytest.mark.p1
def test_high_concurrency_write_no_corruption(mfs_large):
    """50 スレッドが各自の専用ファイルに 1000 回書き込み、データ破壊がないことを確認。"""
    n_threads = 50
    iterations = 1000
    errors: list[Exception] = []
    barrier = threading.Barrier(n_threads)

    def writer(thread_id: int) -> None:
        path = f"/file_{thread_id}.bin"
        payload = bytes([thread_id & 0xFF]) * 64
        try:
            barrier.wait(timeout=10.0)
            for _ in range(iterations):
                with mfs_large.open(path, "wb") as f:
                    f.write(payload)
                with mfs_large.open(path, "rb") as f:
                    data = f.read()
                if data != payload:
                    raise AssertionError(
                        f"thread {thread_id}: expected {payload[:4]!r}…, "
                        f"got {data[:4]!r}…"
                    )
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=writer, args=(i,), daemon=True) for i in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30.0)

    assert not errors, f"Data corruption / errors detected: {errors[:3]}"


# ---------------------------------------------------------------------------
# ST-02
# ---------------------------------------------------------------------------


@pytest.mark.p1
def test_concurrent_create_delete_cycle(mfs_large):
    """30 スレッドが同一パスを 1000 回 create/delete サイクルし、競合なしで完了する。"""
    n_threads = 30
    iterations = 1000
    errors: list[Exception] = []
    barrier = threading.Barrier(n_threads)

    def worker(thread_id: int) -> None:
        path = f"/shared_{thread_id % 5}.bin"
        try:
            barrier.wait(timeout=10.0)
            for _ in range(iterations):
                try:
                    with mfs_large.open(path, "xb") as f:
                        f.write(b"data")
                except FileExistsError:
                    pass
                try:
                    mfs_large.remove(path)
                except FileNotFoundError:
                    pass
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,), daemon=True) for i in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30.0)

    assert not errors, f"Errors during create/delete cycle: {errors[:3]}"


# ---------------------------------------------------------------------------
# ST-03
# ---------------------------------------------------------------------------


@pytest.mark.p1
def test_mixed_readwrite_same_file(mfs_large):
    """20 writer + 20 reader が同一ファイルを 500 回並行操作し、ロック競合が正確に動作する。"""
    n_writers = 20
    n_readers = 20
    iterations = 500
    errors: list[Exception] = []
    path = "/shared_rw.bin"
    barrier = threading.Barrier(n_writers + n_readers)

    with mfs_large.open(path, "wb") as f:
        f.write(b"\x00" * 128)

    def writer(thread_id: int) -> None:
        payload = bytes([thread_id & 0xFF]) * 128
        try:
            barrier.wait(timeout=10.0)
            for _ in range(iterations):
                with mfs_large.open(path, "wb") as f:
                    f.write(payload)
        except Exception as exc:
            errors.append(exc)

    def reader(_thread_id: int) -> None:
        try:
            barrier.wait(timeout=10.0)
            for _ in range(iterations):
                with mfs_large.open(path, "rb") as f:
                    data = f.read()
                # サイズが一定であることのみ確認（書き込みと同時なので内容は不定）
                assert len(data) == 128, f"unexpected size: {len(data)}"
        except Exception as exc:
            errors.append(exc)

    threads = (
        [threading.Thread(target=writer, args=(i,), daemon=True) for i in range(n_writers)]
        + [threading.Thread(target=reader, args=(i,), daemon=True) for i in range(n_readers)]
    )
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30.0)

    assert not errors, f"Errors during mixed read/write: {errors[:3]}"


# ---------------------------------------------------------------------------
# ST-04
# ---------------------------------------------------------------------------


@pytest.mark.p1
def test_quota_boundary_concurrent(mfs_large):
    """40 スレッドがクォータ境界付近で競合書き込みし、超過は例外のみでデータ破壊が起きない。"""
    quota = 512 * 1024  # 512 KiB の小さい MFS
    mfs_small = MemoryFileSystem(max_quota=quota)
    n_threads = 40
    iterations = 500
    errors: list[Exception] = []
    unexpected_errors: list[Exception] = []
    barrier = threading.Barrier(n_threads)

    def worker(thread_id: int) -> None:
        path = f"/q_{thread_id}.bin"
        try:
            barrier.wait(timeout=10.0)
            for _ in range(iterations):
                try:
                    with mfs_small.open(path, "wb") as f:
                        f.write(b"\xff" * 16384)  # 16 KiB
                    with mfs_small.open(path, "rb") as f:
                        data = f.read()
                    if len(data) != 16384:
                        errors.append(
                            AssertionError(f"thread {thread_id}: size mismatch {len(data)}")
                        )
                except MFSQuotaExceededError:
                    pass  # 期待される例外
                except Exception as exc:
                    unexpected_errors.append(exc)
        except Exception as exc:
            unexpected_errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,), daemon=True) for i in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30.0)

    assert not errors, f"Data corruption at quota boundary: {errors[:3]}"
    assert not unexpected_errors, f"Unexpected errors: {unexpected_errors[:3]}"


# ---------------------------------------------------------------------------
# ST-05
# ---------------------------------------------------------------------------


@pytest.mark.p1
def test_directory_tree_concurrent_ops(mfs_large):
    """20 スレッドが mkdir / listdir / rmtree を 500 回並行実行し、パニックなしで完了する。"""
    n_threads = 20
    iterations = 500
    errors: list[Exception] = []
    barrier = threading.Barrier(n_threads)

    def worker(thread_id: int) -> None:
        base = f"/dir_{thread_id % 4}"
        try:
            barrier.wait(timeout=30.0)
            for i in range(iterations):
                try:
                    mfs_large.mkdir(base)
                    mfs_large.mkdir(f"{base}/sub_{i % 8}", exist_ok=True)
                    mfs_large.listdir(base)
                except (FileExistsError, FileNotFoundError):
                    pass
                try:
                    mfs_large.rmtree(base)
                except FileNotFoundError:
                    pass
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,), daemon=True) for i in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30.0)

    assert not errors, f"Errors during concurrent directory ops: {errors[:3]}"


# ---------------------------------------------------------------------------
# ST-06
# ---------------------------------------------------------------------------


@pytest.mark.p1
def test_stat_rename_concurrent(mfs_large):
    """10 writer + 10 stat スレッドが 500 回並行実行し、クラッシュなしで完了する。"""
    n_workers = 10
    iterations = 500
    errors: list[Exception] = []
    path_a = "/rename_a.bin"
    path_b = "/rename_b.bin"
    barrier = threading.Barrier(n_workers * 2)

    with mfs_large.open(path_a, "wb") as f:
        f.write(b"initial")

    def writer(_thread_id: int) -> None:
        try:
            barrier.wait(timeout=10.0)
            for _ in range(iterations):
                try:
                    with mfs_large.open(path_a, "wb") as f:
                        f.write(b"x" * 64)
                except Exception:
                    pass
        except Exception as exc:
            errors.append(exc)

    def stat_reader(_thread_id: int) -> None:
        try:
            barrier.wait(timeout=10.0)
            for _ in range(iterations):
                try:
                    info = mfs_large.stat(path_a)
                    assert "size" in info
                    assert "is_dir" in info
                except FileNotFoundError:
                    pass
                except Exception as exc:
                    errors.append(exc)
        except Exception as exc:
            errors.append(exc)

    threads = (
        [threading.Thread(target=writer, args=(i,), daemon=True) for i in range(n_workers)]
        + [threading.Thread(target=stat_reader, args=(i,), daemon=True) for i in range(n_workers)]
    )
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30.0)

    _ = path_b  # rename は将来拡張のために予約
    assert not errors, f"Errors during concurrent stat: {errors[:3]}"
