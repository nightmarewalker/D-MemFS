# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- `MemoryFileSystem.is_file(path)` for API symmetry with `exists()` / `is_dir()`
- `MemoryFileHandle` file-like methods: `truncate()`, `flush()`, `readable()`, `writable()`, `seekable()`
- Async counterparts for new file-like methods and `AsyncMemoryFileSystem.is_file()`
- `IMemoryFile._bulk_load(data)` method for internal use by `import_tree()` / `_deep_copy_subtree()` (improves encapsulation)

### Changed
- **[BREAKING]** `MFSStatResult.is_sequential` field removed. This internal implementation detail is no longer exposed in the public API.
- **[BREAKING]** Package renamed from `memory-file-system` / `memory_file_system` to `D-MemFS` / `dmemfs`. Update imports: `from dmemfs import ...`
- `stat()` directory support: previously raised `IsADirectoryError`; behavior unchanged in this release, but `is_dir` field added to `MFSStatResult` in future
- `export_as_bytesio()` TOCTOU gap fixed: `_rw_lock.acquire_read()` now called inside `_global_lock` block
- `exists()` / `is_dir()` now resolve paths under `_global_lock` for consistent thread-safety policy
- `open(..., preallocate=...)` now performs preallocation under `_global_lock`
- `import_tree()` quota accounting simplified to net-delta apply after successful write phase
- `import_tree()` rollback now also cleans up auto-created parent directories
- CI workflow now runs tests with coverage (`--cov`, `coverage.xml`) and uploads coverage artifact

### Documentation
- README / README_en updated with lock behavior notes (`_global_lock` hold, writer starvation)
- README / README_en API tables updated for `is_file()` and new handle methods
- Clarified that `stat()` is file-only and that `MFSStatResult.is_sequential` is implementation detail

### Tests
- Added tests for `is_file()`, handle file-like methods, async wrappers, and `import_tree()` parent-dir rollback

## [0.2.0] - 2026-02-26

### Added
- **Directory Index Layer**: Internal refactoring from flat `dict[str, IMemoryFile]` to `DirNode`/`FileNode` tree structure
  - `listdir()` complexity improved from O(N total entries) to O(children count)
  - `rename()` / `rmtree()` no longer require prefix scanning
- **`move(src, dst)`**: Move files/directories with automatic parent directory creation
- **`copy_tree(src, dst)`**: Deep copy of directory subtrees with quota pre-check
- **`stat(path)`**: Return `MFSStatResult` with size, timestamps, generation, storage type
- **`glob("**")`**: Recursive glob pattern matching with `**` support
- **File timestamps**: `created_at` / `modified_at` on `FileNode`, updated on write/truncate
- **`MFSStatResult` TypedDict**: New typed return value for `stat()`
- **`bytearray` shrink**: `RandomAccessMemoryFile.truncate()` reallocates buffer when new size ≤ 25% of old capacity
- **`AsyncMemoryFileSystem` / `AsyncMemoryFileHandle`**: Async wrappers via `asyncio.to_thread()`
- **`pytest-asyncio`** added to test dependencies

### Changed
- `IMemoryFile` is now pure data storage; `is_dir`, `generation`, `_rw_lock` moved to `DirNode`/`FileNode`
- `wb` mode: truncate now executes **after** write-lock acquisition (prevents data corruption during concurrent reads)
- `export_as_bytesio()`: entry lookup now protected by `_global_lock` (prevents race with concurrent `remove()`)
- `MemoryFileHandle.__del__`: `stacklevel` changed from 2 to 1 for correct warning source location
- `__version__` bumped to `0.2.0`

### Tests
- 288 tests (was 230): +58 new tests including `test_fs_coverage.py`
- Coverage target documented at 99% (claim) with CI-side coverage XML generation in place
- New test files: `test_timestamp.py`, `test_async.py`
- Extended: `test_rename_move.py` (+13), `test_files_randomaccess.py` (+5), `test_concurrency.py` (+2), `test_open_modes.py` (+2), `test_export_import.py` (+1), `test_mkdir_listdir.py` (+2)

## [0.1.0] - 2026-02-23

### Added
- Initial release of MemoryFileSystem (MFS)
- In-process virtual filesystem with hard quota management
- `MemoryFileSystem` class with full POSIX-like file operations:
  - `open()` supporting modes `rb`, `wb`, `ab`, `r+b`, `xb` with optional preallocate
  - `mkdir()`, `rename()`, `remove()`, `rmtree()`, `listdir()`, `exists()`, `is_dir()`
  - `stats()` for quota and filesystem metrics
  - `export_as_bytesio()`, `export_tree()`, `iter_export_tree()` with `only_dirty` support
  - `import_tree()` with All-or-Nothing atomicity and rollback
- `MemoryFileHandle` with full `io.RawIOBase`-compatible interface (read, write, seek, tell, truncate)
- `MFSQuotaExceededError` — hard quota enforcement before any write
- `ReadWriteLock` with configurable timeout — concurrent reads, exclusive writes
- Auto-promotion from `SequentialMemoryFile` to `RandomAccessMemoryFile` on random-access writes
- PEP 561 `py.typed` marker — full type annotation support
- Zero external dependencies (Python 3.11+ standard library only)
- 163 tests across Unit / Integration / Scenario / Property (Hypothesis) layers
- CI matrix: 3 OS × 3 Python versions (3.11, 3.12, 3.13)
