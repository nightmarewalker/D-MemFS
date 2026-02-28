"""
Coverage-targeted unit tests for dmemfs/_fs.py.

These tests target specific branches that are not covered by other test files.
"""

import pytest
from dmemfs import MemoryFileSystem
from dmemfs._fs import MemoryFileSystem as MFS


# ---------------------------------------------------------------------------
# _resolve_path: FileNode in middle of path (L109)
# ---------------------------------------------------------------------------


def test_resolve_path_file_in_middle_returns_none(mfs):
    """_resolve_path returns None when a file node is encountered mid-path."""
    with mfs.open("/f", "wb") as h:
        h.write(b"data")
    # "/f" is a file; resolving "/f/sub" should return None (not raise)
    node = mfs._resolve_path("/f/sub")
    assert node is None


# ---------------------------------------------------------------------------
# exists() / is_dir(): ValueError catch (L371-372, L377-378)
# ---------------------------------------------------------------------------


def test_exists_with_traversal_path_returns_false(mfs):
    """exists() catches ValueError from path traversal and returns False."""
    assert mfs.exists("/../etc/passwd") is False


def test_is_dir_with_traversal_path_returns_false(mfs):
    """is_dir() catches ValueError from path traversal and returns False."""
    assert mfs.is_dir("/../etc") is False


# ---------------------------------------------------------------------------
# export_tree / _collect_files: node is None branch (L476)
# and FileNode branch (L487)
# ---------------------------------------------------------------------------


def test_export_tree_nonexistent_prefix_returns_empty(mfs):
    """iter_export_tree with non-existent prefix hits _collect_files(None,...) → L476."""
    with mfs.open("/f.bin", "wb") as h:
        h.write(b"hello")
    result = mfs.export_tree(prefix="/nonexistent")
    assert result == {}


def test_export_tree_file_prefix_returns_single_file(mfs):
    """iter_export_tree with a file path as prefix hits _collect_files FileNode branch → L487."""
    with mfs.open("/f.bin", "wb") as h:
        h.write(b"hello")
    result = mfs.export_tree(prefix="/f.bin")
    assert result == {"/f.bin": b"hello"}


# ---------------------------------------------------------------------------
# _deep_copy_subtree: TypeError for unknown node type (L654)
# ---------------------------------------------------------------------------


def test_deep_copy_subtree_unknown_type_raises():
    """_deep_copy_subtree raises TypeError for unrecognised node types."""
    mfs = MFS(max_quota=1024 * 1024)
    with pytest.raises(TypeError, match="Unknown node type"):
        mfs._deep_copy_subtree(object(), [])  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# _walk_dir: deleted child node skipped (L685)
# _glob_match / _collect_all_paths: deleted child node skipped (L703, L739, L762, L777)
# ---------------------------------------------------------------------------


def test_walk_skips_deleted_child(mfs):
    """_walk_dir skips a child whose node_id has been removed from _nodes."""
    mfs.mkdir("/dir")
    with mfs.open("/dir/f.bin", "wb") as h:
        h.write(b"data")

    # Manually delete the file node from _nodes to simulate a deleted entry
    dir_node = mfs._resolve_path("/dir")
    child_id = dir_node.children["f.bin"]
    del mfs._nodes[child_id]

    result = list(mfs.walk("/dir"))
    # walk should complete without error; file is simply absent
    assert result[0][0] == "/dir"
    assert "f.bin" not in result[0][2]


def test_glob_skips_deleted_child(mfs):
    """_glob_match skips a child whose node_id has been removed from _nodes."""
    with mfs.open("/f.bin", "wb") as h:
        h.write(b"data")

    # Manually delete the file node from _nodes
    root = mfs._root
    child_id = root.children["f.bin"]
    del mfs._nodes[child_id]

    result = mfs.glob("/*.bin")
    assert "/f.bin" not in result


def test_collect_all_paths_skips_deleted_child(mfs):
    """_collect_all_paths skips a child whose node_id has been removed from _nodes."""
    mfs.mkdir("/dir")
    with mfs.open("/dir/f.bin", "wb") as h:
        h.write(b"data")

    # Manually delete the file node so _collect_all_paths encounters a missing entry
    dir_node = mfs._resolve_path("/dir")
    child_id = dir_node.children["f.bin"]
    del mfs._nodes[child_id]

    # glob with ** triggers _collect_all_paths
    result = mfs.glob("/**")
    assert "/dir/f.bin" not in result


# ---------------------------------------------------------------------------
# __init__.py lazy-load branch (L13-19)
# ---------------------------------------------------------------------------


def test_init_lazy_load_async_classes():
    """Accessing AsyncMemoryFileSystem via module __getattr__ triggers lazy import."""
    import importlib
    import dmemfs as pkg

    # Remove cached attributes to force __getattr__ to run
    pkg.__dict__.pop("AsyncMemoryFileSystem", None)
    pkg.__dict__.pop("AsyncMemoryFileHandle", None)

    cls = pkg.AsyncMemoryFileSystem
    assert cls.__name__ == "AsyncMemoryFileSystem"

    handle_cls = pkg.AsyncMemoryFileHandle
    assert handle_cls.__name__ == "AsyncMemoryFileHandle"


def test_init_getattr_unknown_raises():
    """__getattr__ raises AttributeError for unknown names."""
    import dmemfs as pkg

    with pytest.raises(AttributeError, match="has no attribute"):
        _ = pkg.NonExistentSymbol


# ---------------------------------------------------------------------------
# import_tree: empty dict early return (L487)
# ---------------------------------------------------------------------------


def test_import_tree_empty_dict_is_noop(mfs):
    """import_tree with an empty dict returns immediately without error."""
    mfs.import_tree({})
    assert mfs.stats()["file_count"] == 0


# ---------------------------------------------------------------------------
# glob(): relative pattern prepends "/" (L703)
# _glob_match: non-DirNode early return (L717-718)
# _glob_match: idx >= len(parts) early return (L719-720)
# ---------------------------------------------------------------------------


def test_glob_relative_pattern_auto_prefixed(mfs):
    """glob() prepends '/' to patterns not starting with '/' (L703)."""
    with mfs.open("/f.txt", "wb") as h:
        h.write(b"data")
    result = mfs.glob("*.txt")  # no leading slash
    assert "/f.txt" in result


def test_max_nodes_file_limit():
    """max_nodes: creating too many files raises MFSNodeLimitExceededError."""
    from dmemfs import MFSNodeLimitExceededError
    # root dir already occupies 1 node; limit=3 allows root + 2 files
    mfs = MemoryFileSystem(max_quota=1 * 1024 * 1024, max_nodes=3)
    mfs.open("/a.txt", "wb").close()
    mfs.open("/b.txt", "wb").close()
    with pytest.raises(MFSNodeLimitExceededError):
        mfs.open("/c.txt", "wb").close()


def test_max_nodes_dir_limit():
    """max_nodes: creating too many directories raises MFSNodeLimitExceededError."""
    from dmemfs import MFSNodeLimitExceededError
    # root occupies 1 node; limit=2 allows root + 1 dir
    mfs = MemoryFileSystem(max_quota=1 * 1024 * 1024, max_nodes=2)
    mfs.mkdir("/d1")
    with pytest.raises(MFSNodeLimitExceededError):
        mfs.mkdir("/d2")


def test_glob_match_file_node_returns_empty(mfs):
    """_glob_match called with a FileNode returns immediately (L717-718)."""
    with mfs.open("/f.txt", "wb") as h:
        h.write(b"data")
    fnode = mfs._resolve_path("/f.txt")
    results: list[str] = []
    mfs._glob_match(fnode, "/f.txt", ["*"], 0, results)  # type: ignore[arg-type]
    assert results == []


def test_glob_match_empty_parts_returns_empty(mfs):
    """_glob_match called with empty parts list triggers idx >= len(parts) (L719-720)."""
    results: list[str] = []
    mfs._glob_match(mfs._root, "/", [], 0, results)
    assert results == []


# ---------------------------------------------------------------------------
# import_tree: rollback path when write fails mid-way (L553-570)
# ---------------------------------------------------------------------------


def test_import_tree_rollback_restores_existing_file():
    """import_tree rollback restores a previously-existing file after failure."""
    from unittest.mock import patch

    mfs = MemoryFileSystem(max_quota=1 * 1024 * 1024)

    # Create an existing file that will be overwritten then rolled back
    with mfs.open("/existing.bin", "wb") as h:
        h.write(b"original")

    call_count = {"n": 0}
    original_alloc = mfs._alloc_file

    def failing_alloc(storage):
        call_count["n"] += 1
        if call_count["n"] == 2:
            raise RuntimeError("Simulated mid-write failure for rollback test")
        return original_alloc(storage)

    with patch.object(mfs, "_alloc_file", side_effect=failing_alloc):
        with pytest.raises(RuntimeError, match="Simulated"):
            # First entry overwrites /existing.bin, second entry "/new.bin" fails
            mfs.import_tree({"/existing.bin": b"replaced", "/new.bin": b"data"})

    # After rollback, /existing.bin should be restored
    with mfs.open("/existing.bin", "rb") as h:
        assert h.read() == b"original"
    assert not mfs.exists("/new.bin")


def test_import_tree_rollback_removes_new_file():
    """import_tree rollback removes newly created file entries (L566-567)."""
    from unittest.mock import patch

    mfs = MemoryFileSystem(max_quota=1 * 1024 * 1024)
    # No pre-existing files; second alloc will fail, triggering rollback for new files

    call_count = {"n": 0}
    original_alloc = mfs._alloc_file

    def failing_alloc(storage):
        call_count["n"] += 1
        if call_count["n"] == 2:
            raise RuntimeError("Simulated failure for new-file rollback")
        return original_alloc(storage)

    with patch.object(mfs, "_alloc_file", side_effect=failing_alloc):
        with pytest.raises(RuntimeError, match="Simulated"):
            mfs.import_tree({"/a.bin": b"aaa", "/b.bin": b"bbb"})

    # Both files should be absent after rollback
    assert not mfs.exists("/a.bin")
    assert not mfs.exists("/b.bin")
