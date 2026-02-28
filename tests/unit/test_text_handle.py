"""Tests for MFSTextHandle."""

import pytest
from dmemfs import MemoryFileSystem, MFSTextHandle, MFSQuotaExceededError


# ---------------------------------------------------------------------------
# write / read
# ---------------------------------------------------------------------------

def test_write_and_read_utf8(mfs):
    with mfs.open("/f.bin", "wb") as fh:
        th = MFSTextHandle(fh, encoding="utf-8")
        th.write("こんにちは世界\n")
        th.write("Hello, World!\n")
    with mfs.open("/f.bin", "rb") as fh:
        th = MFSTextHandle(fh, encoding="utf-8")
        content = th.read()
    assert content == "こんにちは世界\nHello, World!\n"


def test_write_and_read_shiftjis(mfs):
    with mfs.open("/f.bin", "wb") as fh:
        th = MFSTextHandle(fh, encoding="shift_jis")
        th.write("日本語テスト\n")
    with mfs.open("/f.bin", "rb") as fh:
        th = MFSTextHandle(fh, encoding="shift_jis")
        content = th.read()
    assert content == "日本語テスト\n"


def test_write_returns_char_count(mfs):
    with mfs.open("/f.bin", "wb") as fh:
        th = MFSTextHandle(fh)
        n = th.write("hello")
    assert n == 5


def test_read_partial(mfs):
    with mfs.open("/f.bin", "wb") as fh:
        th = MFSTextHandle(fh)
        th.write("abcde")
    with mfs.open("/f.bin", "rb") as fh:
        th = MFSTextHandle(fh)
        result = th.read(3)
    # 3バイト=3文字（ASCII）を読む
    assert result == "abc"


# ---------------------------------------------------------------------------
# readline
# ---------------------------------------------------------------------------

def test_readline_lf(mfs):
    with mfs.open("/f.bin", "wb") as fh:
        th = MFSTextHandle(fh)
        th.write("line1\nline2\nline3")
    with mfs.open("/f.bin", "rb") as fh:
        th = MFSTextHandle(fh)
        assert th.readline() == "line1\n"
        assert th.readline() == "line2\n"
        assert th.readline() == "line3"
        assert th.readline() == ""


def test_readline_crlf(mfs):
    with mfs.open("/f.bin", "wb") as fh:
        fh.write(b"line1\r\nline2\r\n")
    with mfs.open("/f.bin", "rb") as fh:
        th = MFSTextHandle(fh)
        assert th.readline() == "line1\r\n"
        assert th.readline() == "line2\r\n"
        assert th.readline() == ""


def test_readline_cr(mfs):
    with mfs.open("/f.bin", "wb") as fh:
        fh.write(b"line1\rline2\r")
    with mfs.open("/f.bin", "rb") as fh:
        th = MFSTextHandle(fh)
        assert th.readline() == "line1\r"
        assert th.readline() == "line2\r"
        assert th.readline() == ""


# ---------------------------------------------------------------------------
# __iter__ / __next__
# ---------------------------------------------------------------------------

def test_iteration(mfs):
    lines = ["alpha\n", "beta\n", "gamma"]
    with mfs.open("/f.bin", "wb") as fh:
        th = MFSTextHandle(fh)
        for ln in lines:
            th.write(ln)
    with mfs.open("/f.bin", "rb") as fh:
        th = MFSTextHandle(fh)
        result = list(th)
    assert result == lines


# ---------------------------------------------------------------------------
# context manager
# ---------------------------------------------------------------------------

def test_context_manager(mfs):
    with mfs.open("/f.bin", "wb") as fh:
        with MFSTextHandle(fh) as th:
            th.write("hello")
    with mfs.open("/f.bin", "rb") as fh:
        th = MFSTextHandle(fh)
        assert th.read() == "hello"


# ---------------------------------------------------------------------------
# properties
# ---------------------------------------------------------------------------

def test_encoding_property(mfs):
    with mfs.open("/f.bin", "wb") as fh:
        th = MFSTextHandle(fh, encoding="latin-1")
        assert th.encoding == "latin-1"


def test_errors_property(mfs):
    with mfs.open("/f.bin", "wb") as fh:
        th = MFSTextHandle(fh, errors="replace")
        assert th.errors == "replace"


# ---------------------------------------------------------------------------
# quota enforcement
# ---------------------------------------------------------------------------

def test_write_raises_on_quota_exceeded():
    tiny = MemoryFileSystem(max_quota=10)
    with tiny.open("/f.bin", "wb") as fh:
        th = MFSTextHandle(fh)
        with pytest.raises(MFSQuotaExceededError):
            th.write("This string is definitely longer than 10 bytes")
