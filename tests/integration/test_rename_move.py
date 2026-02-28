import pytest
from dmemfs import MemoryFileSystem


def test_rename_file(mfs):
    with mfs.open("/a.bin", "wb") as f:
        f.write(b"data")
    mfs.rename("/a.bin", "/b.bin")
    assert not mfs.exists("/a.bin")
    assert mfs.exists("/b.bin")
    with mfs.open("/b.bin", "rb") as f:
        assert f.read() == b"data"


def test_rename_directory(mfs):
    mfs.mkdir("/src")
    with mfs.open("/src/f.bin", "wb") as f:
        f.write(b"content")
    mfs.rename("/src", "/dst")
    assert not mfs.exists("/src")
    assert mfs.is_dir("/dst")
    assert mfs.exists("/dst/f.bin")


def test_rename_nonexistent_raises(mfs):
    with pytest.raises(FileNotFoundError):
        mfs.rename("/nope.bin", "/other.bin")


def test_rename_destination_exists_raises(mfs):
    with mfs.open("/a.bin", "wb") as f:
        f.write(b"a")
    with mfs.open("/b.bin", "wb") as f:
        f.write(b"b")
    with pytest.raises(FileExistsError):
        mfs.rename("/a.bin", "/b.bin")


def test_rename_open_file_raises(mfs):
    with mfs.open("/f.bin", "wb") as handle:
        handle.write(b"data")
        with pytest.raises(BlockingIOError):
            mfs.rename("/f.bin", "/g.bin")


def test_rename_root_raises(mfs):
    with pytest.raises(ValueError):
        mfs.rename("/", "/newroot")


def test_rename_file_content_preserved(mfs):
    with mfs.open("/a.bin", "wb") as f:
        f.write(b"preserved content")
    mfs.rename("/a.bin", "/b.bin")
    with mfs.open("/b.bin", "rb") as f:
        assert f.read() == b"preserved content"


# ------------------------------------------------------------------
# copy()
# ------------------------------------------------------------------


def test_copy_creates_independent_file(mfs):
    with mfs.open("/src.bin", "wb") as f:
        f.write(b"original")
    mfs.copy("/src.bin", "/dst.bin")
    assert mfs.exists("/dst.bin")
    with mfs.open("/dst.bin", "rb") as f:
        assert f.read() == b"original"
    # Modifying src does not affect dst
    with mfs.open("/src.bin", "wb") as f:
        f.write(b"changed")
    with mfs.open("/dst.bin", "rb") as f:
        assert f.read() == b"original"


def test_copy_src_missing_raises(mfs):
    with pytest.raises(FileNotFoundError):
        mfs.copy("/nope.bin", "/dst.bin")


def test_copy_dst_exists_raises(mfs):
    with mfs.open("/a.bin", "wb") as f:
        f.write(b"a")
    with mfs.open("/b.bin", "wb") as f:
        f.write(b"b")
    with pytest.raises(FileExistsError):
        mfs.copy("/a.bin", "/b.bin")


def test_copy_src_is_dir_raises(mfs):
    mfs.mkdir("/d")
    with pytest.raises(IsADirectoryError):
        mfs.copy("/d", "/d2")


# ------------------------------------------------------------------
# get_size()
# ------------------------------------------------------------------


def test_get_size_returns_correct_bytes(mfs):
    with mfs.open("/f.bin", "wb") as f:
        f.write(b"hello world")
    assert mfs.get_size("/f.bin") == 11


def test_get_size_missing_raises(mfs):
    with pytest.raises(FileNotFoundError):
        mfs.get_size("/nope.bin")


def test_get_size_directory_raises(mfs):
    mfs.mkdir("/d")
    with pytest.raises(IsADirectoryError):
        mfs.get_size("/d")


def test_rename_directory_recursive(mfs):
    mfs.mkdir("/src")
    mfs.mkdir("/src/sub")
    with mfs.open("/src/sub/f.bin", "wb") as f:
        f.write(b"deep")
    mfs.rename("/src", "/dst")
    assert mfs.exists("/dst/sub/f.bin")
    with mfs.open("/dst/sub/f.bin", "rb") as f:
        assert f.read() == b"deep"


def test_rename_to_different_directory(mfs):
    mfs.mkdir("/dir1")
    mfs.mkdir("/dir2")
    with mfs.open("/dir1/f.bin", "wb") as f:
        f.write(b"moved")
    mfs.rename("/dir1/f.bin", "/dir2/f.bin")
    assert not mfs.exists("/dir1/f.bin")
    assert mfs.exists("/dir2/f.bin")


# ------------------------------------------------------------------
# v10: move()
# ------------------------------------------------------------------


def test_move_file(mfs):
    mfs.mkdir("/src")
    with mfs.open("/src/f.bin", "wb") as f:
        f.write(b"data")
    mfs.move("/src/f.bin", "/dst_f.bin")
    assert not mfs.exists("/src/f.bin")
    with mfs.open("/dst_f.bin", "rb") as f:
        assert f.read() == b"data"


def test_move_directory(mfs):
    mfs.mkdir("/src/sub")
    with mfs.open("/src/sub/f.bin", "wb") as f:
        f.write(b"deep")
    mfs.move("/src", "/dst")
    assert not mfs.exists("/src")
    assert mfs.is_dir("/dst")
    assert mfs.exists("/dst/sub/f.bin")


def test_move_auto_creates_parent(mfs):
    """move() は dst の親ディレクトリを自動作成する。"""
    with mfs.open("/f.bin", "wb") as f:
        f.write(b"data")
    mfs.move("/f.bin", "/new/deep/path/f.bin")
    assert mfs.is_dir("/new/deep/path")
    with mfs.open("/new/deep/path/f.bin", "rb") as f:
        assert f.read() == b"data"


def test_move_root_raises(mfs):
    with pytest.raises(ValueError):
        mfs.move("/", "/elsewhere")


def test_move_nonexistent_raises(mfs):
    with pytest.raises(FileNotFoundError):
        mfs.move("/nope", "/other")


def test_move_dst_exists_raises(mfs):
    with mfs.open("/a.bin", "wb") as f:
        f.write(b"a")
    with mfs.open("/b.bin", "wb") as f:
        f.write(b"b")
    with pytest.raises(FileExistsError):
        mfs.move("/a.bin", "/b.bin")


def test_move_open_file_raises(mfs):
    with mfs.open("/f.bin", "wb") as handle:
        handle.write(b"data")
        with pytest.raises(BlockingIOError):
            mfs.move("/f.bin", "/g.bin")


# ------------------------------------------------------------------
# v10: copy_tree()
# ------------------------------------------------------------------


def test_copy_tree_basic(mfs):
    mfs.mkdir("/src")
    with mfs.open("/src/a.bin", "wb") as f:
        f.write(b"aaa")
    with mfs.open("/src/b.bin", "wb") as f:
        f.write(b"bbb")
    mfs.copy_tree("/src", "/dst")
    assert mfs.is_dir("/dst")
    with mfs.open("/dst/a.bin", "rb") as f:
        assert f.read() == b"aaa"
    with mfs.open("/dst/b.bin", "rb") as f:
        assert f.read() == b"bbb"


def test_copy_tree_deep(mfs):
    mfs.mkdir("/src/sub/deep")
    with mfs.open("/src/sub/deep/f.bin", "wb") as f:
        f.write(b"deep data")
    mfs.copy_tree("/src", "/dst")
    assert mfs.exists("/dst/sub/deep/f.bin")
    with mfs.open("/dst/sub/deep/f.bin", "rb") as f:
        assert f.read() == b"deep data"


def test_copy_tree_independent(mfs):
    """copy_tree のコピーは独立している。"""
    mfs.mkdir("/src")
    with mfs.open("/src/f.bin", "wb") as f:
        f.write(b"original")
    mfs.copy_tree("/src", "/dst")

    with mfs.open("/src/f.bin", "wb") as f:
        f.write(b"changed")
    with mfs.open("/dst/f.bin", "rb") as f:
        assert f.read() == b"original"


def test_copy_tree_src_not_dir_raises(mfs):
    with mfs.open("/f.bin", "wb") as f:
        f.write(b"data")
    with pytest.raises(NotADirectoryError):
        mfs.copy_tree("/f.bin", "/dst")


def test_copy_tree_dst_exists_raises(mfs):
    mfs.mkdir("/src")
    mfs.mkdir("/dst")
    with pytest.raises(FileExistsError):
        mfs.copy_tree("/src", "/dst")


def test_copy_tree_src_missing_raises(mfs):
    with pytest.raises(FileNotFoundError):
        mfs.copy_tree("/nope", "/dst")


def test_copy_tree_quota_exceeded(mfs):
    """copy_tree でクォータを超過すると MFSQuotaExceededError。"""
    from dmemfs import MFSQuotaExceededError

    small_mfs = MemoryFileSystem(max_quota=200)
    small_mfs.mkdir("/src")
    with small_mfs.open("/src/f.bin", "wb") as f:
        f.write(b"x" * 100)
    with pytest.raises(MFSQuotaExceededError):
        small_mfs.copy_tree("/src", "/dst")


def test_copy_tree_rollback_quota_consistency():
    """copy_tree がクォータ超過で失敗した場合、used_bytes が元に戻る。"""
    from dmemfs import MFSQuotaExceededError

    mfs = MemoryFileSystem(max_quota=300)
    mfs.mkdir("/src")
    with mfs.open("/src/f.bin", "wb") as f:
        f.write(b"x" * 200)
    used_before = mfs.stats()["used_bytes"]

    with pytest.raises(MFSQuotaExceededError):
        mfs.copy_tree("/src", "/dst")

    # クォータが元に戻っていること
    used_after = mfs.stats()["used_bytes"]
    assert used_after == used_before
    # 元ツリーは無傷
    with mfs.open("/src/f.bin", "rb") as f:
        assert f.read() == b"x" * 200
    # dst は作成されていないこと
    assert not mfs.exists("/dst")


def test_copy_tree_rollback_no_orphan_nodes():
    """copy_tree failure cleans up all nodes created during the partial copy."""
    from unittest.mock import patch
    from dmemfs._fs import MemoryFileSystem as MFS

    mfs = MFS(max_quota=1024 * 1024)
    mfs.mkdir("/src")
    mfs.mkdir("/src/sub")
    with mfs.open("/src/a.bin", "wb") as f:
        f.write(b"aaa")
    with mfs.open("/src/sub/b.bin", "wb") as f:
        f.write(b"bbb")

    node_count_before = len(mfs._nodes)

    # Patch _alloc_file to fail on the second file copy
    original_alloc = MFS._alloc_file
    call_count = 0

    def failing_alloc(self, storage):
        nonlocal call_count
        call_count += 1
        if call_count >= 2:
            raise RuntimeError("simulated failure")
        return original_alloc(self, storage)

    with patch.object(MFS, '_alloc_file', failing_alloc):
        with pytest.raises(RuntimeError, match="simulated failure"):
            mfs.copy_tree("/src", "/dst")

    # No orphan nodes should remain
    assert len(mfs._nodes) == node_count_before
    assert not mfs.exists("/dst")


def test_rename_dst_parent_missing_raises(mfs):
    """rename の dst の親ディレクトリが存在しない場合 FileNotFoundError。"""
    with mfs.open("/a.bin", "wb") as f:
        f.write(b"data")
    with pytest.raises(FileNotFoundError):
        mfs.rename("/a.bin", "/nonexistent_dir/b.bin")


def test_copy_tree_dst_parent_missing_raises(mfs):
    """copy_tree の dst の親ディレクトリが存在しない場合 FileNotFoundError。"""
    mfs.mkdir("/src")
    with mfs.open("/src/f.bin", "wb") as f:
        f.write(b"data")
    with pytest.raises(FileNotFoundError):
        mfs.copy_tree("/src", "/nonexistent_dir/dst")
