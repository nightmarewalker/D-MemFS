import pytest
from dmemfs._path import normalize_path


def test_simple_absolute():
    assert normalize_path("/a/b/c") == "/a/b/c"


def test_trailing_slash_removed():
    assert normalize_path("/a/b/") == "/a/b"


def test_double_slash_collapsed():
    assert normalize_path("/a//b") == "/a/b"


def test_dot_removed():
    assert normalize_path("/a/./b") == "/a/b"


def test_dotdot_resolved():
    assert normalize_path("/a/b/../c") == "/a/c"


def test_relative_path_becomes_absolute():
    assert normalize_path("a/b/c") == "/a/b/c"


def test_empty_string_returns_root():
    assert normalize_path("") == "/"


def test_root_returns_root():
    assert normalize_path("/") == "/"


def test_traversal_beyond_root_raises():
    with pytest.raises(ValueError, match="traversal"):
        normalize_path("../x")


def test_deep_traversal_raises():
    with pytest.raises(ValueError, match="traversal"):
        normalize_path("/a/../../x")


def test_backslash_converted():
    assert normalize_path("\\a\\b") == "/a/b"


def test_windows_style_traversal():
    with pytest.raises(ValueError, match="traversal"):
        normalize_path("..\\x")
