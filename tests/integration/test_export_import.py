import pytest
from dmemfs import MemoryFileSystem
from dmemfs._exceptions import MFSQuotaExceededError


def test_export_as_bytesio(mfs):
    with mfs.open("/f.bin", "wb") as f:
        f.write(b"hello world")
    bio = mfs.export_as_bytesio("/f.bin")
    assert bio.read() == b"hello world"


def test_export_as_bytesio_nonexistent_raises(mfs):
    with pytest.raises(FileNotFoundError):
        mfs.export_as_bytesio("/nope.bin")


def test_export_as_bytesio_max_size(mfs):
    with mfs.open("/f.bin", "wb") as f:
        f.write(b"x" * 100)
    with pytest.raises(ValueError):
        mfs.export_as_bytesio("/f.bin", max_size=50)


def test_export_tree_basic(mfs):
    with mfs.open("/a.bin", "wb") as f:
        f.write(b"aaa")
    with mfs.open("/b.bin", "wb") as f:
        f.write(b"bbb")
    tree = mfs.export_tree()
    assert tree["/a.bin"] == b"aaa"
    assert tree["/b.bin"] == b"bbb"


def test_export_tree_with_prefix(mfs):
    mfs.mkdir("/dir")
    with mfs.open("/dir/f.bin", "wb") as f:
        f.write(b"inside")
    with mfs.open("/other.bin", "wb") as f:
        f.write(b"outside")
    tree = mfs.export_tree(prefix="/dir")
    assert "/dir/f.bin" in tree
    assert "/other.bin" not in tree


def test_export_tree_only_dirty(mfs):
    with mfs.open("/f.bin", "wb") as f:
        f.write(b"data")
    tree = mfs.export_tree(only_dirty=True)
    assert "/f.bin" in tree


def test_import_tree_basic(mfs):
    mfs.import_tree({"/a.bin": b"aaa", "/b.bin": b"bbb"})
    with mfs.open("/a.bin", "rb") as f:
        assert f.read() == b"aaa"
    with mfs.open("/b.bin", "rb") as f:
        assert f.read() == b"bbb"


def test_import_tree_creates_dirs(mfs):
    mfs.import_tree({"/new/path/f.bin": b"deep"})
    assert mfs.is_dir("/new")
    assert mfs.is_dir("/new/path")
    with mfs.open("/new/path/f.bin", "rb") as f:
        assert f.read() == b"deep"


def test_import_tree_replaces_existing(mfs):
    with mfs.open("/f.bin", "wb") as f:
        f.write(b"old")
    mfs.import_tree({"/f.bin": b"new"})
    with mfs.open("/f.bin", "rb") as f:
        assert f.read() == b"new"


def test_import_tree_quota_exceeded_raises():
    mfs = MemoryFileSystem(max_quota=100)
    with pytest.raises(MFSQuotaExceededError):
        mfs.import_tree({"/f.bin": b"x" * 1000})


def test_import_tree_open_file_raises(mfs):
    handle = mfs.open("/f.bin", "wb")
    handle.write(b"data")
    try:
        with pytest.raises(BlockingIOError):
            mfs.import_tree({"/f.bin": b"new"})
    finally:
        handle.close()


def test_iter_export_tree(mfs):
    with mfs.open("/a.bin", "wb") as f:
        f.write(b"aaa")
    items = list(mfs.iter_export_tree())
    paths = [p for p, _ in items]
    assert "/a.bin" in paths


def test_roundtrip_export_import(mfs):
    with mfs.open("/data.bin", "wb") as f:
        f.write(b"round trip data")
    original_tree = mfs.export_tree()

    mfs2 = MemoryFileSystem(max_quota=1 * 1024 * 1024)
    mfs2.import_tree(original_tree)

    with mfs2.open("/data.bin", "rb") as f:
        assert f.read() == b"round trip data"


# --- v10: export_as_bytesio lock granularity ---


def test_export_as_bytesio_with_global_lock(mfs):
    """v10: export_as_bytesio が _global_lock でエントリ存在確認を保護する。"""
    import threading

    with mfs.open("/f.bin", "wb") as f:
        f.write(b"data")

    errors = []

    def exporter():
        for _ in range(100):
            try:
                bio = mfs.export_as_bytesio("/f.bin")
                assert bio.read() == b"data"
            except FileNotFoundError:
                pass  # remove と競合した場合は正常
            except Exception as e:
                errors.append(e)

    def remover_creator():
        for _ in range(100):
            try:
                mfs.remove("/f.bin")
            except FileNotFoundError:
                pass
            with mfs.open("/f.bin", "wb") as f:
                f.write(b"data")

    threads = [
        threading.Thread(target=exporter, daemon=True),
        threading.Thread(target=remover_creator, daemon=True),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10.0)
    assert not errors, f"Unexpected errors: {errors}"


def test_import_tree_rollback_quota_consistency():
    """import_tree がクォータ超過で失敗した場合、used_bytes が元に戻る。"""
    mfs = MemoryFileSystem(max_quota=500)
    # 事前にファイルを作成してクォータを消費
    with mfs.open("/existing.bin", "wb") as f:
        f.write(b"x" * 200)
    used_before = mfs.stats()["used_bytes"]

    # クォータを超過するインポートを試みる
    with pytest.raises(MFSQuotaExceededError):
        mfs.import_tree({"/big.bin": b"y" * 1000})

    # クォータが元に戻っていること
    used_after = mfs.stats()["used_bytes"]
    assert used_after == used_before
    # 既存ファイルは無傷
    with mfs.open("/existing.bin", "rb") as f:
        assert f.read() == b"x" * 200


def test_export_as_bytesio_on_directory_raises(mfs):
    """export_as_bytesio にディレクトリパスを渡すと IsADirectoryError。"""
    mfs.mkdir("/mydir")
    with pytest.raises(IsADirectoryError):
        mfs.export_as_bytesio("/mydir")


def test_import_tree_rollback_removes_auto_created_parent_dirs():
    """import_tree 失敗時に自動作成された親ディレクトリが残らない。"""
    mfs = MemoryFileSystem(max_quota=1 * 1024 * 1024)

    with pytest.raises(ValueError):
        mfs.import_tree({"/new/deep/path/file.bin": b"ok", "../invalid": b"bad"})

    assert not mfs.exists("/new")
    assert not mfs.exists("/new/deep")
    assert not mfs.exists("/new/deep/path")
