import pytest


def test_mkdir_basic(mfs):
    mfs.mkdir("/mydir")
    assert mfs.is_dir("/mydir")


def test_mkdir_nested(mfs):
    mfs.mkdir("/a")
    mfs.mkdir("/a/b")
    mfs.mkdir("/a/b/c")
    assert mfs.is_dir("/a/b/c")


def test_mkdir_exist_ok_false_raises(mfs):
    mfs.mkdir("/mydir")
    with pytest.raises(FileExistsError):
        mfs.mkdir("/mydir", exist_ok=False)


def test_mkdir_exist_ok_true_no_raise(mfs):
    mfs.mkdir("/mydir")
    mfs.mkdir("/mydir", exist_ok=True)  # should not raise


def test_mkdir_on_file_raises(mfs):
    with mfs.open("/f.bin", "wb") as f:
        f.write(b"data")
    with pytest.raises(FileExistsError):
        mfs.mkdir("/f.bin")


def test_mkdir_without_parent_creates_parents(mfs):
    """mkdir should create intermediate directories."""
    mfs.mkdir("/a/b/c")
    assert mfs.is_dir("/a")
    assert mfs.is_dir("/a/b")
    assert mfs.is_dir("/a/b/c")


def test_listdir_empty_dir(mfs):
    mfs.mkdir("/empty")
    assert mfs.listdir("/empty") == []


def test_listdir_with_files(mfs):
    mfs.mkdir("/dir")
    with mfs.open("/dir/a.bin", "wb") as f:
        f.write(b"a")
    with mfs.open("/dir/b.bin", "wb") as f:
        f.write(b"b")
    result = mfs.listdir("/dir")
    assert set(result) == {"a.bin", "b.bin"}


def test_listdir_with_subdirs(mfs):
    mfs.mkdir("/dir")
    mfs.mkdir("/dir/sub1")
    mfs.mkdir("/dir/sub2")
    result = mfs.listdir("/dir")
    assert set(result) == {"sub1", "sub2"}


def test_listdir_nonexistent_raises(mfs):
    with pytest.raises(FileNotFoundError):
        mfs.listdir("/nope")


def test_listdir_on_file_raises(mfs):
    with mfs.open("/f.bin", "wb") as f:
        f.write(b"data")
    with pytest.raises(NotADirectoryError):
        mfs.listdir("/f.bin")


def test_listdir_root(mfs):
    mfs.mkdir("/a")
    mfs.mkdir("/b")
    result = mfs.listdir("/")
    assert "a" in result
    assert "b" in result


def test_exists_file(mfs):
    with mfs.open("/f.bin", "wb") as f:
        f.write(b"data")
    assert mfs.exists("/f.bin")


def test_exists_dir(mfs):
    mfs.mkdir("/d")
    assert mfs.exists("/d")


def test_exists_nonexistent(mfs):
    assert not mfs.exists("/nope")


def test_is_file_file_dir_and_missing(mfs):
    mfs.mkdir("/d")
    with mfs.open("/d/f.bin", "wb") as f:
        f.write(b"x")
    assert mfs.is_file("/d/f.bin") is True
    assert mfs.is_file("/d") is False
    assert mfs.is_file("/missing.bin") is False


# ------------------------------------------------------------------
# walk()
# ------------------------------------------------------------------


def test_walk_yields_top_down(mfs):
    mfs.mkdir("/a/b")
    with mfs.open("/a/f.bin", "wb") as f:
        f.write(b"x")
    with mfs.open("/a/b/g.bin", "wb") as f:
        f.write(b"y")
    entries = list(mfs.walk("/a"))
    assert entries[0] == ("/a", ["b"], ["f.bin"])
    assert entries[1] == ("/a/b", [], ["g.bin"])


def test_walk_empty_dir(mfs):
    mfs.mkdir("/empty")
    entries = list(mfs.walk("/empty"))
    assert entries == [("/empty", [], [])]


def test_walk_nonexistent_raises(mfs):
    with pytest.raises(FileNotFoundError):
        list(mfs.walk("/nope"))


def test_walk_file_raises(mfs):
    with mfs.open("/f.bin", "wb") as f:
        f.write(b"x")
    with pytest.raises(NotADirectoryError):
        list(mfs.walk("/f.bin"))


# ------------------------------------------------------------------
# glob()
# ------------------------------------------------------------------


def test_glob_matches_extension(mfs):
    with mfs.open("/a.bin", "wb") as f:
        f.write(b"x")
    with mfs.open("/b.txt", "wb") as f:
        f.write(b"y")
    result = mfs.glob("/*.bin")
    assert result == ["/a.bin"]


def test_glob_matches_nested(mfs):
    mfs.mkdir("/dir")
    with mfs.open("/dir/file.bin", "wb") as f:
        f.write(b"x")
    result = mfs.glob("/dir/*.bin")
    assert result == ["/dir/file.bin"]


def test_glob_wildcard_all(mfs):
    with mfs.open("/a.bin", "wb") as f:
        f.write(b"x")
    with mfs.open("/b.bin", "wb") as f:
        f.write(b"y")
    result = mfs.glob("/*.bin")
    assert sorted(result) == ["/a.bin", "/b.bin"]


def test_glob_no_match_returns_empty(mfs):
    assert mfs.glob("/*.xyz") == []


# --- v10: glob(**) recursive matching ---


def test_glob_double_star_matches_recursive(mfs):
    """** パターンで再帰的にファイルをマッチする。"""
    mfs.mkdir("/a/b/c")
    with mfs.open("/a/x.bin", "wb") as f:
        f.write(b"x")
    with mfs.open("/a/b/y.bin", "wb") as f:
        f.write(b"y")
    with mfs.open("/a/b/c/z.bin", "wb") as f:
        f.write(b"z")

    result = mfs.glob("/a/**/*.bin")
    assert "/a/x.bin" in result or "/a/b/y.bin" in result
    assert "/a/b/c/z.bin" in result


def test_glob_double_star_at_end(mfs):
    """末尾の ** は全てのエントリにマッチする。"""
    mfs.mkdir("/top/sub")
    with mfs.open("/top/a.bin", "wb") as f:
        f.write(b"a")
    with mfs.open("/top/sub/b.bin", "wb") as f:
        f.write(b"b")

    result = mfs.glob("/top/**")
    assert "/top/a.bin" in result
    assert "/top/sub" in result
    assert "/top/sub/b.bin" in result


def test_glob_consecutive_double_star(mfs):
    """/**/**/*.txt は連続 ** でも正しくマッチする。"""
    mfs.mkdir("/a/b")
    with mfs.open("/a/b/c.txt", "wb") as f:
        f.write(b"x")
    with mfs.open("/a/d.txt", "wb") as f:
        f.write(b"y")

    result = mfs.glob("/**/**/*.txt")
    assert "/a/b/c.txt" in result
    assert "/a/d.txt" in result


def test_glob_double_star_trailing_slash(mfs):
    """/**/ パターンは中間ディレクトリにマッチする。"""
    mfs.mkdir("/a/b")
    with mfs.open("/a/b/f.txt", "wb") as f:
        f.write(b"x")
    with mfs.open("/a/g.txt", "wb") as f:
        f.write(b"y")

    result = mfs.glob("/**/f.txt")
    assert "/a/b/f.txt" in result


def test_glob_question_mark(mfs):
    """? は任意の1文字にマッチする。"""
    mfs.mkdir("/dir")
    with mfs.open("/dir/a.txt", "wb") as f:
        f.write(b"x")
    with mfs.open("/dir/b.txt", "wb") as f:
        f.write(b"y")
    with mfs.open("/dir/ab.txt", "wb") as f:
        f.write(b"z")

    result = mfs.glob("/dir/?.txt")
    assert sorted(result) == ["/dir/a.txt", "/dir/b.txt"]


def test_glob_character_class(mfs):
    """[abc] は指定文字のいずれかにマッチする。"""
    mfs.mkdir("/dir")
    with mfs.open("/dir/a.txt", "wb") as f:
        f.write(b"x")
    with mfs.open("/dir/b.txt", "wb") as f:
        f.write(b"y")
    with mfs.open("/dir/c.txt", "wb") as f:
        f.write(b"z")
    with mfs.open("/dir/d.txt", "wb") as f:
        f.write(b"w")

    result = mfs.glob("/dir/[ac].txt")
    assert sorted(result) == ["/dir/a.txt", "/dir/c.txt"]


def test_glob_double_star_at_beginning(mfs):
    """/**/*.txt はルートから再帰的にファイルをマッチする。"""
    mfs.mkdir("/x/y")
    with mfs.open("/top.txt", "wb") as f:
        f.write(b"a")
    with mfs.open("/x/mid.txt", "wb") as f:
        f.write(b"b")
    with mfs.open("/x/y/deep.txt", "wb") as f:
        f.write(b"c")

    result = mfs.glob("/**/*.txt")
    assert "/top.txt" in result
    assert "/x/mid.txt" in result
    assert "/x/y/deep.txt" in result


def test_makedirs_file_at_path_component_raises(mfs):
    """_makedirs should raise FileExistsError when a file occupies an intermediate path component."""
    with mfs.open("/a", "wb") as f:
        f.write(b"data")
    # "/a" is a file, so mkdir "/a/b" should fail inside _makedirs
    with pytest.raises(FileExistsError):
        mfs.mkdir("/a/b")
