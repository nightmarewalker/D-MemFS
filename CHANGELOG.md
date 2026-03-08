# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.3.0] - 2026-03-09

### Added
- `memory_guard` parameter for physical memory protection
  - `memory_guard="none"` (default): no check, fully backward compatible
  - `memory_guard="init"`: check available RAM at initialization
  - `memory_guard="per_write"`: check before each write with interval caching
- `memory_guard_action="warn" | "raise"` to choose `ResourceWarning` or `MemoryError`
- `memory_guard_interval=1.0` to control OS query cache interval
- New internal modules: `_memory_info.py` and `_memory_guard.py`
- MemoryGuard-specific unit and integration tests

### Changed
- `IMemoryFile.write_at()` accepts an optional `memory_guard` parameter
- `IMemoryFile.truncate()` accepts an optional `memory_guard` parameter
- `MemoryFileHandle.write()` and `truncate()` now forward `memory_guard`
- `MemoryFileSystem` and `AsyncMemoryFileSystem` accept all `memory_guard` parameters
- `open(..., preallocate=...)`, `import_tree()`, and `copy_tree()` are integrated with MemoryGuard
- `MemoryError` messages now include context and recovery hints for memory-sensitive paths
- `dmemfs.__version__` and project version bumped to `0.3.0`

## [0.2.2] - 2026-03-08

### Added
- `MemoryFileSystem.is_file(path)` for API symmetry with `exists()` / `is_dir()`
- `MemoryFileHandle` file-like methods: `truncate()`, `flush()`, `readable()`, `writable()`, `seekable()`
- `MemoryFileHandle.readinto()` and `io.RawIOBase` compatibility for file-like integrations
- Async counterparts for new file-like methods and `AsyncMemoryFileSystem.is_file()`
- `IMemoryFile._bulk_load(data)` method for internal use by `import_tree()` / `_deep_copy_subtree()` (improves encapsulation)
- Version consistency test for `pyproject.toml` and `dmemfs.__version__`

### Changed
- `MemoryFileSystem.__init__` and `AsyncMemoryFileSystem.__init__` accept a new `default_lock_timeout: float | None = 30.0` parameter. `open()` now resolves `lock_timeout=None` to this value, preventing `_global_lock` from being held indefinitely when a file lock cannot be acquired. Pass `default_lock_timeout=None` to restore the previous infinite-wait behaviour.
- **[BREAKING]** `MFSStatResult.is_sequential` field removed. This internal implementation detail is no longer exposed in the public API.
- **[BREAKING]** Package renamed from `memory-file-system` / `memory_file_system` to `D-MemFS` / `dmemfs`. Update imports: `from dmemfs import ...`
- `MFSTextHandle.read(size)` and `readline(limit)` now treat their limits as character counts and avoid splitting multibyte text
- `export_as_bytesio()` TOCTOU gap fixed: `_rw_lock.acquire_read()` now called inside `_global_lock` block
- `exists()` / `is_dir()` now resolve paths under `_global_lock` for consistent thread-safety policy
- `open(..., preallocate=...)` now performs preallocation under `_global_lock`
- `import_tree()` quota accounting simplified to net-delta apply after successful write phase
- `import_tree()` rollback now also cleans up auto-created parent directories
- CI workflow now runs tests with coverage (`--cov`, `coverage.xml`) and uploads coverage artifact

### Documentation
- README / README_en updated with lock behavior notes (`_global_lock` hold, writer starvation)
- README / README_en API tables updated for `is_file()`, `readinto()`, and RawIOBase-compatible handle behavior
- Clarified `export_as_bytesio()` detached-snapshot semantics, `MFSTextHandle` character-count behavior, and `mkdir()` auto-parent semantics

### Tests
- Added 3 tests to `test_concurrency.py` for `default_lock_timeout`: contention raises `BlockingIOError`, explicit `lock_timeout` overrides the default, and `default_lock_timeout=None` waits indefinitely until lock is released
- Added tests for `is_file()`, handle file-like methods, async wrappers, and `import_tree()` parent-dir rollback
- Added regression tests for `readinto()`, multibyte `MFSTextHandle.read(size)`, detached `export_as_bytesio()` snapshots, weakly-consistent `iter_export_tree()`, and version synchronization

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
