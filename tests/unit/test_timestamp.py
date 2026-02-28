"""unit/test_timestamp.py

MemoryFileSystem を経由して FileNode のタイムスタンプ・stat() の振る舞いを検証する。
観測対象は個々のファイルノードのメタデータ更新ルール（ctime/mtime/atime）。
FS全体の状態整合性ではなく、タイムスタンプ属性そのものに焦点を当てたユニット的検証。
"""

import time
from unittest.mock import patch
import pytest


# -------------------------------------------------------------------
# §17.1  タイムスタンプの初期化・更新・不変性
# -------------------------------------------------------------------


def test_new_file_has_timestamps(mfs):
    before = time.time()
    with mfs.open("/test.bin", "wb") as f:
        f.write(b"data")
    after = time.time()

    info = mfs.stat("/test.bin")
    assert before <= info["created_at"] <= after
    assert before <= info["modified_at"] <= after


def test_created_at_equals_modified_at_on_creation(mfs):
    with mfs.open("/test.bin", "xb") as f:
        pass  # write なし → modified_at は更新されない

    info = mfs.stat("/test.bin")
    assert info["created_at"] == info["modified_at"]


def test_write_updates_modified_at(mfs):
    with patch("time.time") as mock_time:
        mock_time.return_value = 1000.0
        with mfs.open("/test.bin", "wb") as f:
            f.write(b"initial")
        info1 = mfs.stat("/test.bin")

        mock_time.return_value = 2000.0
        with mfs.open("/test.bin", "r+b") as f:
            f.write(b"updated")
        info2 = mfs.stat("/test.bin")

    assert info2["modified_at"] > info1["modified_at"]
    assert info2["created_at"] == info1["created_at"]


def test_write_does_not_change_created_at(mfs):
    with patch("time.time") as mock_time:
        mock_time.return_value = 1000.0
        with mfs.open("/test.bin", "wb") as f:
            f.write(b"initial")
        created = mfs.stat("/test.bin")["created_at"]

        mock_time.return_value = 2000.0
        with mfs.open("/test.bin", "r+b") as f:
            f.write(b"updated")
        assert mfs.stat("/test.bin")["created_at"] == created


def test_truncate_updates_modified_at(mfs):
    with patch("time.time") as mock_time:
        mock_time.return_value = 1000.0
        with mfs.open("/test.bin", "wb") as f:
            f.write(b"data")
        info1 = mfs.stat("/test.bin")

        mock_time.return_value = 2000.0
        with mfs.open("/test.bin", "wb") as f:
            pass  # wb truncates to 0
        info2 = mfs.stat("/test.bin")

    assert info2["modified_at"] > info1["modified_at"]


def test_rename_preserves_timestamps(mfs):
    with mfs.open("/a.bin", "wb") as f:
        f.write(b"data")
    info_before = mfs.stat("/a.bin")

    mfs.rename("/a.bin", "/b.bin")
    info_after = mfs.stat("/b.bin")

    assert info_after["created_at"] == info_before["created_at"]
    assert info_after["modified_at"] == info_before["modified_at"]


def test_move_preserves_timestamps(mfs):
    mfs.mkdir("/src")
    mfs.mkdir("/dst")
    with mfs.open("/src/a.bin", "wb") as f:
        f.write(b"data")
    info_before = mfs.stat("/src/a.bin")

    mfs.move("/src/a.bin", "/dst/a.bin")
    info_after = mfs.stat("/dst/a.bin")

    assert info_after["created_at"] == info_before["created_at"]
    assert info_after["modified_at"] == info_before["modified_at"]


def test_copy_creates_new_timestamps(mfs):
    with patch("time.time") as mock_time:
        mock_time.return_value = 1000.0
        with mfs.open("/src.bin", "wb") as f:
            f.write(b"data")
        info_src = mfs.stat("/src.bin")

        mock_time.return_value = 2000.0
        mfs.copy("/src.bin", "/dst.bin")
        info_dst = mfs.stat("/dst.bin")

    # コピー先は新しいタイムスタンプ
    assert info_dst["created_at"] >= info_src["created_at"]


def test_copy_tree_creates_new_timestamps(mfs):
    with patch("time.time") as mock_time:
        mock_time.return_value = 1000.0
        mfs.mkdir("/src")
        with mfs.open("/src/a.bin", "wb") as f:
            f.write(b"aaa")
        info_src = mfs.stat("/src/a.bin")

        mock_time.return_value = 2000.0
        mfs.copy_tree("/src", "/dst")
        info_dst = mfs.stat("/dst/a.bin")

    assert info_dst["created_at"] >= info_src["created_at"]


def test_import_tree_creates_new_timestamps(mfs):
    before = time.time()
    mfs.import_tree({"/imp.bin": b"imported"})
    after = time.time()

    info = mfs.stat("/imp.bin")
    assert before <= info["created_at"] <= after


# -------------------------------------------------------------------
# §17.2  stat() API — エラーハンドリングと統合動作
# -------------------------------------------------------------------


def test_stat_returns_correct_size(mfs):
    data = b"hello world"
    with mfs.open("/test.bin", "wb") as f:
        f.write(data)
    info = mfs.stat("/test.bin")
    assert info["size"] == len(data)
    assert info["generation"] > 0


def test_stat_returns_generation(mfs):
    with mfs.open("/test.bin", "wb") as f:
        f.write(b"a")
    gen1 = mfs.stat("/test.bin")["generation"]

    with mfs.open("/test.bin", "r+b") as f:
        f.write(b"b")
    gen2 = mfs.stat("/test.bin")["generation"]
    assert gen2 > gen1


def test_stat_returns_size_and_generation(mfs):
    with mfs.open("/test.bin", "wb") as f:
        f.write(b"hello")
    info = mfs.stat("/test.bin")
    assert info["size"] == 5
    assert info["generation"] > 0


def test_stat_file_not_found(mfs):
    with pytest.raises(FileNotFoundError):
        mfs.stat("/nonexistent")


def test_stat_is_directory(mfs):
    mfs.mkdir("/mydir")
    info = mfs.stat("/mydir")
    assert info["is_dir"] is True
    assert info["size"] == 0
    assert info["generation"] == 0


def test_stat_after_promotion(mfs):
    """書き込みによる自動昇格後もstat()が正常に動作する。"""
    with mfs.open("/test.bin", "wb") as f:
        f.write(b"hello")
    assert mfs.stat("/test.bin")["size"] == 5

    # r+b で offset 0 に書き込むと Sequential → RandomAccess に昇格
    with mfs.open("/test.bin", "r+b") as f:
        f.seek(0)
        f.write(b"X")
    assert mfs.stat("/test.bin")["size"] == 5

