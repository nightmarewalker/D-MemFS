import pytest
from tests.helpers.asserts import assert_stats_consistent


def test_stats_initial(mfs):
    s = mfs.stats()
    assert s["used_bytes"] == 0
    assert s["quota_bytes"] == 1 * 1024 * 1024
    assert s["free_bytes"] == 1 * 1024 * 1024
    assert s["file_count"] == 0
    assert s["dir_count"] == 1  # root
    assert_stats_consistent(mfs)


def test_stats_after_write(mfs):
    with mfs.open("/f.bin", "wb") as f:
        f.write(b"x" * 100)
    s = mfs.stats()
    assert s["used_bytes"] > 0
    assert s["file_count"] == 1
    assert_stats_consistent(mfs)


def test_stats_after_mkdir(mfs):
    mfs.mkdir("/d")
    s = mfs.stats()
    assert s["dir_count"] == 2  # root + /d
    assert_stats_consistent(mfs)


def test_stats_after_remove(mfs):
    with mfs.open("/f.bin", "wb") as f:
        f.write(b"x" * 100)
    used_before = mfs.stats()["used_bytes"]
    mfs.remove("/f.bin")
    assert mfs.stats()["used_bytes"] < used_before
    assert mfs.stats()["file_count"] == 0
    assert_stats_consistent(mfs)


def test_stats_consistent_always(mfs):
    mfs.mkdir("/dir")
    with mfs.open("/dir/a.bin", "wb") as f:
        f.write(b"aaa")
    with mfs.open("/dir/b.bin", "wb") as f:
        f.write(b"bbb")
    assert_stats_consistent(mfs)


def test_stats_free_bytes(mfs):
    s = mfs.stats()
    assert s["free_bytes"] == s["quota_bytes"] - s["used_bytes"]


def test_stats_chunk_count(mfs):
    with mfs.open("/f.bin", "wb") as f:
        f.write(b"chunk1")
        f.write(b"chunk2")
    s = mfs.stats()
    # Each write_at appends a chunk to SequentialMemoryFile
    assert s["chunk_count"] >= 1


def test_stats_after_rmtree(mfs):
    mfs.mkdir("/d")
    with mfs.open("/d/f.bin", "wb") as f:
        f.write(b"x" * 100)
    mfs.rmtree("/d")
    s = mfs.stats()
    assert s["file_count"] == 0
    assert s["dir_count"] == 1
    assert_stats_consistent(mfs)


def test_stats_snapshot_consistency(mfs):
    """used_bytes + free_bytes == quota_bytes holds atomically."""
    s = mfs.stats()
    assert s["used_bytes"] + s["free_bytes"] == s["quota_bytes"]
    with mfs.open("/f.bin", "wb") as f:
        f.write(b"x" * 500)
    s = mfs.stats()
    assert s["used_bytes"] + s["free_bytes"] == s["quota_bytes"]


def test_stats_overhead_per_chunk_estimate(mfs):
    s = mfs.stats()
    assert s["overhead_per_chunk_estimate"] > 0
