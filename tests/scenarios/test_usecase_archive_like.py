"""Archive-like use case: store/retrieve multiple files."""
import pytest
from dmemfs import MemoryFileSystem


@pytest.fixture
def mfs():
    return MemoryFileSystem(max_quota=16 * 1024 * 1024)


def test_store_and_retrieve_multiple_files(mfs):
    files = {
        "/archive/doc1.txt": b"Document 1 content",
        "/archive/doc2.txt": b"Document 2 content",
        "/archive/sub/doc3.txt": b"Document 3 content",
    }
    mfs.import_tree(files)
    
    for path, expected in files.items():
        with mfs.open(path, "rb") as f:
            assert f.read() == expected


def test_list_archive_contents(mfs):
    mfs.import_tree({
        "/archive/a.bin": b"a",
        "/archive/b.bin": b"b",
        "/archive/c.bin": b"c",
    })
    contents = mfs.listdir("/archive")
    assert set(contents) == {"a.bin", "b.bin", "c.bin"}


def test_export_archive_roundtrip(mfs):
    original = {
        "/archive/f1.bin": b"file1 data",
        "/archive/f2.bin": b"file2 data",
    }
    mfs.import_tree(original)
    exported = mfs.export_tree(prefix="/archive")
    assert exported == original


def test_update_file_in_archive(mfs):
    mfs.import_tree({"/archive/config.bin": b"version=1"})
    mfs.import_tree({"/archive/config.bin": b"version=2"})
    with mfs.open("/archive/config.bin", "rb") as f:
        assert f.read() == b"version=2"


def test_remove_from_archive(mfs):
    mfs.import_tree({
        "/archive/keep.bin": b"keep",
        "/archive/remove.bin": b"remove",
    })
    mfs.remove("/archive/remove.bin")
    assert mfs.exists("/archive/keep.bin")
    assert not mfs.exists("/archive/remove.bin")
