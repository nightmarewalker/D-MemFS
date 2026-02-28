"""unit/test_handle_io.py

このファイルは MemoryFileSystem を経由して MemoryFileHandle の振る舞いを検証する。
テストの観点はカーソル位置・read/write制約・モード別動作など Handle 固有のもの。
MemoryFileSystem.open() の API 契約（ファイル存在・クォータ・FS状態）を検証する
integration層テスト (test_open_modes.py) とは焦点が異なる。
"""

import io
import pytest
from dmemfs._exceptions import MFSQuotaExceededError


def test_write_and_read_basic(mfs):
    """Handle が write/read のカーソル移動を正しく管理する。"""
    with mfs.open("/test.bin", "wb") as f:
        f.write(b"hello")
    with mfs.open("/test.bin", "rb") as f:
        assert f.read() == b"hello"


def test_read_partial(mfs):
    with mfs.open("/test.bin", "wb") as f:
        f.write(b"hello world")
    with mfs.open("/test.bin", "rb") as f:
        assert f.read(5) == b"hello"
        assert f.read(6) == b" world"


def test_seek_set(mfs):
    with mfs.open("/test.bin", "wb") as f:
        f.write(b"hello world")
    with mfs.open("/test.bin", "r+b") as f:
        f.seek(6)
        assert f.read() == b"world"


def test_seek_cur(mfs):
    with mfs.open("/test.bin", "wb") as f:
        f.write(b"hello world")
    with mfs.open("/test.bin", "rb") as f:
        f.read(3)
        f.seek(3, 1)  # SEEK_CUR: skip "lo " to reach "world"
        assert f.read() == b"world"


def test_seek_end(mfs):
    with mfs.open("/test.bin", "wb") as f:
        f.write(b"hello world")
    with mfs.open("/test.bin", "rb") as f:
        pos = f.seek(-5, 2)  # SEEK_END
        assert pos == 6
        assert f.read() == b"world"


def test_tell(mfs):
    with mfs.open("/test.bin", "wb") as f:
        f.write(b"hello")
    with mfs.open("/test.bin", "rb") as f:
        assert f.tell() == 0
        f.read(3)
        assert f.tell() == 3


def test_append_mode(mfs):
    """ab Handle は write 後も元データ末尾に連結した結果を返す。"""
    with mfs.open("/test.bin", "wb") as f:
        f.write(b"hello")
    with mfs.open("/test.bin", "ab") as f:
        f.write(b" world")
    with mfs.open("/test.bin", "rb") as f:
        assert f.read() == b"hello world"


def test_wb_truncates_existing(mfs):
    """wb で開いた Handle は既存データを切り詰めた状態で開始する。"""
    with mfs.open("/test.bin", "wb") as f:
        f.write(b"hello world")
    with mfs.open("/test.bin", "wb") as f:
        f.write(b"hi")
    with mfs.open("/test.bin", "rb") as f:
        assert f.read() == b"hi"


def test_read_in_write_mode_raises(mfs):
    with mfs.open("/test.bin", "wb") as f:
        with pytest.raises(io.UnsupportedOperation):
            f.read()


def test_write_in_read_mode_raises(mfs):
    with mfs.open("/test.bin", "wb") as f:
        f.write(b"data")
    with mfs.open("/test.bin", "rb") as f:
        with pytest.raises(io.UnsupportedOperation):
            f.write(b"more")


def test_operation_on_closed_handle_raises(mfs):
    with mfs.open("/test.bin", "wb") as f:
        f.write(b"data")
    handle = mfs.open("/test.bin", "rb")
    handle.close()
    with pytest.raises(ValueError):
        handle.read()


def test_context_manager_closes(mfs):
    with mfs.open("/test.bin", "wb") as f:
        f.write(b"data")
    handle = mfs.open("/test.bin", "rb")
    with handle:
        pass
    assert handle._is_closed


def test_seek_negative_offset_raises(mfs):
    with mfs.open("/test.bin", "wb") as f:
        f.write(b"data")
    with mfs.open("/test.bin", "rb") as f:
        with pytest.raises(ValueError):
            f.seek(-1, 0)


def test_rplus_read_and_write(mfs):
    """r+b Handle は同一セッション内で読み取り・書き込みを交互に行える。"""
    with mfs.open("/test.bin", "wb") as f:
        f.write(b"hello world")
    with mfs.open("/test.bin", "r+b") as f:
        f.seek(6)
        f.write(b"Python")
    with mfs.open("/test.bin", "rb") as f:
        assert f.read() == b"hello Python"


def test_xb_creates_new_file(mfs):
    """xb Handle は新規ファイルを排他的に作成し内容を書ける。"""
    with mfs.open("/new.bin", "xb") as f:
        f.write(b"exclusive")
    with mfs.open("/new.bin", "rb") as f:
        assert f.read() == b"exclusive"


def test_xb_raises_if_exists(mfs):
    """既存パスへの xb オープンは Handle 生成前に FileExistsError を送出する。"""
    with mfs.open("/test.bin", "wb") as f:
        f.write(b"data")
    with pytest.raises(FileExistsError):
        mfs.open("/test.bin", "xb")


def test_preallocate(mfs):
    """preallocate 指定時に Handle オープン直後からクォータ消費が発生する。"""
    with mfs.open("/test.bin", "wb", preallocate=1024) as f:
        assert mfs.stats()["used_bytes"] > 0


def test_ab_write_always_appends_to_eof(mfs):
    """ab モードでは seek しても write は常に EOF に追記する。"""
    with mfs.open("/test.bin", "wb") as f:
        f.write(b"hello")
    with mfs.open("/test.bin", "ab") as f:
        f.seek(0)  # seek to beginning — should NOT affect write position
        f.write(b" world")
    with mfs.open("/test.bin", "rb") as f:
        assert f.read() == b"hello world"


def test_seek_end_positive_offset_raises(mfs):
    """SEEK_END に正のオフセットを渡すと ValueError が送出される。"""
    with mfs.open("/test.bin", "wb") as f:
        f.write(b"data")
    with mfs.open("/test.bin", "rb") as f:
        with pytest.raises(ValueError):
            f.seek(1, 2)  # SEEK_END + positive offset


def test_seek_cur_negative_result_raises(mfs):
    """SEEK_CUR でカーソルが負になる場合は ValueError が送出される。"""
    with mfs.open("/test.bin", "wb") as f:
        f.write(b"data")
    with mfs.open("/test.bin", "rb") as f:
        with pytest.raises(ValueError):
            f.seek(-1, 1)  # SEEK_CUR: 0 + (-1) = -1


def test_seek_invalid_whence_raises(mfs):
    """無効な whence 値を渡すと ValueError が送出される。"""
    with mfs.open("/test.bin", "wb") as f:
        f.write(b"data")
    with mfs.open("/test.bin", "rb") as f:
        with pytest.raises(ValueError):
            f.seek(0, 99)


def test_tell_on_closed_handle_raises(mfs):
    """クローズ済みハンドルで tell() を呼ぶと ValueError が送出される。"""
    with mfs.open("/test.bin", "wb") as f:
        f.write(b"data")
    handle = mfs.open("/test.bin", "rb")
    handle.close()
    with pytest.raises(ValueError):
        handle.tell()


def test_close_twice_is_idempotent(mfs):
    """close() を2回呼んでも例外は発生しない（L101 の早期リターン）。"""
    with mfs.open("/test.bin", "wb") as f:
        f.write(b"data")
    handle = mfs.open("/test.bin", "rb")
    handle.close()
    handle.close()  # 2回目は早期リターン（例外なし）


def test_del_without_close_emits_resource_warning(mfs):
    """クローズしないまま del するとResourceWarning が発行される。"""
    import warnings

    with mfs.open("/f.bin", "wb") as f:
        f.write(b"x")
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        handle = mfs.open("/f.bin", "rb")
        del handle
        # CPython では参照カウントで即 __del__ が呼ばれる
    assert any(issubclass(warning.category, ResourceWarning) for warning in w)


def test_truncate_shrinks_file_and_updates_cursor(mfs):
    with mfs.open("/f.bin", "wb") as f:
        f.write(b"abcdef")
    with mfs.open("/f.bin", "r+b") as f:
        f.seek(6)
        size = f.truncate(3)
        assert size == 3
        assert f.tell() == 3
    with mfs.open("/f.bin", "rb") as f:
        assert f.read() == b"abc"


def test_truncate_default_uses_cursor(mfs):
    with mfs.open("/f.bin", "wb") as f:
        f.write(b"abcdef")
    with mfs.open("/f.bin", "r+b") as f:
        f.seek(2)
        assert f.truncate() == 2
    with mfs.open("/f.bin", "rb") as f:
        assert f.read() == b"ab"


def test_truncate_in_read_mode_raises(mfs):
    with mfs.open("/f.bin", "wb") as f:
        f.write(b"data")
    with mfs.open("/f.bin", "rb") as f:
        with pytest.raises(io.UnsupportedOperation):
            f.truncate(1)


def test_io_capability_methods(mfs):
    with mfs.open("/f.bin", "wb") as f:
        assert f.writable() is True
        assert f.readable() is False
        assert f.seekable() is True
        assert f.flush() is None

    with mfs.open("/f.bin", "rb") as f:
        assert f.writable() is False
        assert f.readable() is True
        assert f.seekable() is True
