import pytest


def test_remove_file(mfs):
    with mfs.open("/f.bin", "wb") as f:
        f.write(b"data")
    mfs.remove("/f.bin")
    assert not mfs.exists("/f.bin")


def test_remove_frees_quota(mfs):
    with mfs.open("/f.bin", "wb") as f:
        f.write(b"x" * 1000)
    used_before = mfs.stats()["used_bytes"]
    mfs.remove("/f.bin")
    assert mfs.stats()["used_bytes"] < used_before


def test_remove_nonexistent_raises(mfs):
    with pytest.raises(FileNotFoundError):
        mfs.remove("/nope.bin")


def test_remove_directory_raises(mfs):
    mfs.mkdir("/d")
    with pytest.raises(IsADirectoryError):
        mfs.remove("/d")


def test_remove_open_file_raises(mfs):
    with mfs.open("/f.bin", "wb") as handle:
        handle.write(b"data")
        with pytest.raises(BlockingIOError):
            mfs.remove("/f.bin")


def test_rmtree_removes_dir(mfs):
    mfs.mkdir("/d")
    with mfs.open("/d/f.bin", "wb") as f:
        f.write(b"data")
    mfs.rmtree("/d")
    assert not mfs.exists("/d")
    assert not mfs.exists("/d/f.bin")


def test_rmtree_frees_quota(mfs):
    mfs.mkdir("/d")
    with mfs.open("/d/f.bin", "wb") as f:
        f.write(b"x" * 1000)
    used_before = mfs.stats()["used_bytes"]
    mfs.rmtree("/d")
    assert mfs.stats()["used_bytes"] < used_before


def test_rmtree_nonexistent_raises(mfs):
    with pytest.raises(FileNotFoundError):
        mfs.rmtree("/nope")


def test_rmtree_on_file_raises(mfs):
    with mfs.open("/f.bin", "wb") as f:
        f.write(b"data")
    with pytest.raises(NotADirectoryError):
        mfs.rmtree("/f.bin")


def test_rmtree_with_open_file_raises(mfs):
    mfs.mkdir("/d")
    handle = mfs.open("/d/f.bin", "wb")
    handle.write(b"data")
    try:
        with pytest.raises(BlockingIOError):
            mfs.rmtree("/d")
    finally:
        handle.close()


def test_rmtree_root_raises(mfs):
    """ルートディレクトリの rmtree は ValueError を送出する。"""
    with pytest.raises(ValueError):
        mfs.rmtree("/")
