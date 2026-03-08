# D-MemFS

**An in-process virtual filesystem with hard quota enforcement for Python.**

[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)
[![Tests](https://github.com/nightmarewalker/D-MemFS/actions/workflows/test.yml/badge.svg)](https://github.com/nightmarewalker/D-MemFS/actions/workflows/test.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://github.com/nightmarewalker/D-MemFS/blob/main/LICENSE)
[![Zero dependencies (runtime)](https://img.shields.io/badge/runtime_deps-none-brightgreen.svg)]()

Languages: [English](https://github.com/nightmarewalker/D-MemFS/blob/main/README.md) | [Japanese](https://github.com/nightmarewalker/D-MemFS/blob/main/README_ja.md)

---

## Why MFS?

`MemoryFileSystem` gives you a fully isolated filesystem-like workspace inside a Python process.

- Hard quota (`MFSQuotaExceededError`) to reject oversized writes before OOM
- Hierarchical directories and multi-file operations (`import_tree`, `copy_tree`, `move`)
- File-level RW locking + global structure lock for thread-safe operations
- Free-threaded Python compatible (`PYTHON_GIL=0`) — stress-tested under 50-thread contention
- Async wrapper (`AsyncMemoryFileSystem`) powered by `asyncio.to_thread`
- Zero runtime dependencies (standard library only)

This is useful when `io.BytesIO` is too primitive (single buffer), and OS-level RAM disks/tmpfs are impractical (permissions, container policy, Windows driver friction).

---

## Installation

```bash
pip install D-MemFS
```

Requirements: Python 3.11+

---

## Quick Start

```python
from dmemfs import MemoryFileSystem, MFSQuotaExceededError

mfs = MemoryFileSystem(max_quota=64 * 1024 * 1024)

mfs.mkdir("/data")
with mfs.open("/data/hello.bin", "wb") as f:
    f.write(b"hello")

with mfs.open("/data/hello.bin", "rb") as f:
    print(f.read())  # b"hello"

print(mfs.listdir("/data"))
print(mfs.is_file("/data/hello.bin"))  # True

try:
    with mfs.open("/huge.bin", "wb") as f:
        f.write(bytes(512 * 1024 * 1024))
except MFSQuotaExceededError as e:
    print(e)
```

---

## API Highlights

### `MemoryFileSystem`

- `open(path, mode, *, preallocate=0, lock_timeout=None)`
- `mkdir`, `remove`, `rmtree`, `rename`, `move`, `copy`, `copy_tree`
- `listdir`, `exists`, `is_dir`, `is_file`, `walk`, `glob`
- `stat`, `stats`, `get_size`
- `export_as_bytesio`, `export_tree`, `iter_export_tree`, `import_tree`

**Constructor parameters:**
- `max_quota` (default `256 MiB`): byte quota for file data
- `max_nodes` (default `None`): optional cap on total node count (files + directories). Raises `MFSNodeLimitExceededError` when exceeded.
- `default_storage` (default `"auto"`): storage backend for new files — `"auto"` / `"sequential"` / `"random_access"`
- `promotion_hard_limit` (default `None`): byte threshold above which Sequential→RandomAccess auto-promotion is suppressed (`None` uses the built-in 512 MiB limit)
- `chunk_overhead_override` (default `None`): override the per-chunk overhead estimate used for quota accounting
- `default_lock_timeout` (default `30.0`): default timeout in seconds for file-lock acquisition during `open()`. Use `None` to wait indefinitely.
- `memory_guard` (default `"none"`): physical memory protection mode — `"none"` / `"init"` / `"per_write"`
- `memory_guard_action` (default `"warn"`): action when the guard triggers — `"warn"` (`ResourceWarning`) / `"raise"` (`MemoryError`)
- `memory_guard_interval` (default `1.0`): minimum seconds between OS memory queries (`"per_write"` only)

> **Note:** The `BytesIO` returned by `export_as_bytesio()` is outside quota management.
> Exporting large files may consume significant process memory beyond the configured quota limit.

> **Note — Quota and free-threaded Python:**
> The per-chunk overhead estimate used for quota accounting is calibrated at import time
> via `sys.getsizeof()`. Free-threaded Python (3.13t, `PYTHON_GIL=0`) has larger object
> headers than the standard build, so `CHUNK_OVERHEAD_ESTIMATE` is higher (~117 bytes vs
> ~93 bytes on CPython 3.13). This means the same `max_quota` yields slightly less
> effective storage capacity on free-threaded builds, especially for workloads with many
> small files or small appends. This is not a bug — it reflects real memory consumption.
> To ensure consistent behaviour across builds, use `chunk_overhead_override` to pin the
> value, or inspect `stats()["overhead_per_chunk_estimate"]` at runtime.

Supported binary modes: `rb`, `wb`, `ab`, `r+b`, `xb`

## Memory Guard

MFS enforces a logical quota, but that quota can still be configured larger than the
currently available physical RAM. `memory_guard` provides an optional safety net.

```python
from dmemfs import MemoryFileSystem

# Warn if max_quota exceeds available RAM
mfs = MemoryFileSystem(max_quota=8 * 1024**3, memory_guard="init")

# Raise MemoryError before writes when RAM is insufficient
mfs = MemoryFileSystem(
    max_quota=8 * 1024**3,
    memory_guard="per_write",
    memory_guard_action="raise",
)
```

| Mode | Initialization | Each Write | Overhead |
|---|---|---|---|
| `"none"` | — | — | Zero |
| `"init"` | Check once | — | Negligible |
| `"per_write"` | Check once | Cached check | About 1 OS call/sec |

When `memory_guard_action="warn"`, the guard emits `ResourceWarning` and allows the operation to continue.
When `memory_guard_action="raise"`, the guard rejects the operation with `MemoryError` before the actual allocation path.

`AsyncMemoryFileSystem` accepts the same constructor parameters and forwards them to the synchronous implementation.

### `MemoryFileHandle`

- `io.RawIOBase`-compatible binary handle
- `read`, `write`, `seek`, `tell`, `truncate`, `flush`, `close`
- `readinto`
- file-like capability checks: `readable`, `writable`, `seekable`

`flush()` is intentionally a no-op (compatibility API for file-like integrations).

### `stat()` return (`MFSStatResult`)

`size`, `created_at`, `modified_at`, `generation`, `is_dir`

- Supports both files and directories
- For directories: `size=0`, `generation=0`, `is_dir=True`

---

## Text Mode

D-MemFS natively operates in binary mode. For text I/O, use `MFSTextHandle`:

```python
from dmemfs import MemoryFileSystem, MFSTextHandle

mfs = MemoryFileSystem()
mfs.mkdir("/data")

# Write text
with mfs.open("/data/hello.bin", "wb") as f:
    th = MFSTextHandle(f, encoding="utf-8")
    th.write("こんにちは世界\n")
    th.write("Hello, World!\n")

# Read text line by line
with mfs.open("/data/hello.bin", "rb") as f:
    th = MFSTextHandle(f, encoding="utf-8")
    for line in th:
        print(line, end="")
```

`MFSTextHandle` is a thin, bufferless wrapper. It encodes on `write()` and decodes on `read()` / `readline()`. `read(size)` counts characters, not bytes, so multibyte text can be read safely without splitting code points. Unlike `io.TextIOWrapper`, it introduces no buffering issues when used with `MemoryFileHandle`.

---

## Use Case Tutorials

### ETL Staging

Stage data through raw → processed → output directories:

```python
from dmemfs import MemoryFileSystem

mfs = MemoryFileSystem(max_quota=16 * 1024 * 1024)
mfs.mkdir("/raw")
mfs.mkdir("/processed")

raw_data = b"id,name,value\n1,foo,100\n2,bar,200\n"
with mfs.open("/raw/data.csv", "wb") as f:
    f.write(raw_data)

with mfs.open("/raw/data.csv", "rb") as f:
    data = f.read()

with mfs.open("/processed/data.csv", "wb") as f:
    f.write(data.upper())

mfs.rmtree("/raw")  # cleanup staging
```

### Archive-like Operations

Store, list, and export multiple files as a tree:

```python
from dmemfs import MemoryFileSystem

mfs = MemoryFileSystem()
mfs.import_tree({
    "/archive/doc1.bin": b"Document 1",
    "/archive/doc2.bin": b"Document 2",
    "/archive/sub/doc3.bin": b"Document 3",
})

print(mfs.listdir("/archive"))  # ['doc1.bin', 'doc2.bin', 'sub']

snapshot = mfs.export_tree(prefix="/archive")  # dict of {path: bytes}
```

### SQLite Snapshot

Serialize an in-memory SQLite DB into MFS and restore it later:

```python
import sqlite3
from dmemfs import MemoryFileSystem

mfs = MemoryFileSystem()
conn = sqlite3.connect(":memory:")
conn.execute("CREATE TABLE t (id INTEGER, val TEXT)")
conn.execute("INSERT INTO t VALUES (1, 'hello')")
conn.commit()

with mfs.open("/snapshot.db", "wb") as f:
    f.write(conn.serialize())
conn.close()

with mfs.open("/snapshot.db", "rb") as f:
    raw = f.read()
restored = sqlite3.connect(":memory:")
restored.deserialize(raw)
rows = restored.execute("SELECT * FROM t").fetchall()  # [(1, 'hello')]
```

---

## Concurrency and Locking Notes

- Path/tree operations are guarded by `_global_lock`.
- File access is guarded by per-file `ReadWriteLock`.
- `lock_timeout` behavior:
  - `None`: block indefinitely
  - `0.0`: try-lock (fail immediately with `BlockingIOError`)
  - `> 0`: timeout in seconds, then `BlockingIOError`
- Current `ReadWriteLock` is non-fair: under sustained read load, writers can starve.

Operational guidance:

- Keep lock hold duration short
- Set an explicit `lock_timeout` in latency-sensitive code paths
- `walk()` and `glob()` provide weak consistency: each directory level is
  snapshotted under `_global_lock`, but the overall traversal is NOT atomic.
  Concurrent structural changes may produce inconsistent results.

---

## Async Usage

```python
from dmemfs import AsyncMemoryFileSystem

async def run() -> None:
    mfs = AsyncMemoryFileSystem(max_quota=64 * 1024 * 1024)
    await mfs.mkdir("/a")
    async with await mfs.open("/a/f.bin", "wb") as f:
        await f.write(b"data")
    async with await mfs.open("/a/f.bin", "rb") as f:
        print(await f.read())
```

---

## Benchmarks

Minimal benchmark tooling is included:

- MFS vs `io.BytesIO` vs `PyFilesystem2 (MemoryFS)` vs `tempfile`
- Cases: many-small-files and stream write/read
- Optional report output to `benchmarks/results/`

> **Note:** As of setuptools 82 (February 2026), `pyfilesystem2` fails to import due to a known upstream issue ([#597](https://github.com/PyFilesystem/pyfilesystem2/issues/597)). Benchmark results including PyFilesystem2 were measured with setuptools ≤ 81 and are valid as historical comparison data.

Run:

```bash
uvx --with-requirements requirements.txt --with-editable . python benchmarks/compare_backends.py --save-md auto --save-json auto
```

See `BENCHMARK.md` for details.

Latest benchmark snapshot:

- [benchmark_current_result.md](https://github.com/nightmarewalker/D-MemFS/blob/main/benchmarks/results/benchmark_current_result.md)

---

## Testing and Coverage

Test execution and dev flow are documented in `TESTING.md`.

Typical local run:

```bash
uv pip compile requirements.in -o requirements.txt
uvx --with-requirements requirements.txt --with-editable . pytest tests/ -v --timeout=30 --cov=dmemfs --cov-report=xml --cov-report=term-missing
```

CI (`.github/workflows/test.yml`) runs tests with coverage XML generation.

---

## API Docs Generation

API docs can be generated as Markdown (viewable on GitHub) using `pydoc-markdown`:

```bash
uvx --with pydoc-markdown --with-editable . pydoc-markdown '{
  loaders: [{type: python, search_path: [.]}],
  processors: [{type: filter, expression: "default()"}],
  renderer: {type: markdown, filename: docs/api_md/index.md}
}'
```

Or as HTML using `pdoc` (local browsing only):

```bash
uvx --with-requirements requirements.txt pdoc dmemfs -o docs/api
```

- [API Reference (Markdown)](https://github.com/nightmarewalker/D-MemFS/blob/main/docs/api_md/index.md)

---

## Compatibility and Non-Goals

- Core `open()` is binary-only (`rb`, `wb`, `ab`, `r+b`, `xb`). Text I/O is available via the `MFSTextHandle` wrapper.
- No symlink/hardlink support — intentionally omitted to eliminate path traversal loops and structural complexity (same rationale as `pathlib.PurePath`).
- No direct `pathlib.Path` / `os.PathLike` API — MFS paths are virtual and must not be confused with host filesystem paths. Accepting `os.PathLike` would allow third-party libraries or a plain `open()` call to silently treat an MFS virtual path as a real OS path, potentially issuing unintended syscalls against the host filesystem. All paths must be plain `str` with POSIX-style absolute notation (e.g. `"/data/file.txt"`).
- No kernel filesystem integration (intentionally in-process only)

Auto-promotion behavior:

- By default (`default_storage="auto"`), new files start as `SequentialMemoryFile` and auto-promote to `RandomAccessMemoryFile` when random writes are detected.
- Promotion is one-way (no downgrade back to sequential).
- Use `default_storage="sequential"` or `"random_access"` to fix the backend at construction; use `promotion_hard_limit` to suppress auto-promotion above a byte threshold.
- Storage promotion temporarily doubles memory usage for the promoted file. The quota system accounts for this, but process-level memory may spike briefly.

Security note: In-memory data may be written to physical disk via OS swap
or core dumps. MFS does not provide memory-locking (e.g., mlock) or
secure erasure. Do not rely on MFS alone for sensitive data isolation.

---

## Exception Reference

| Exception | Typical cause |
|---|---|
| `MFSQuotaExceededError` | write/import/copy would exceed quota |
| `MFSNodeLimitExceededError` | node count would exceed `max_nodes` (subclass of `MFSQuotaExceededError`) |
| `FileNotFoundError` | path missing |
| `FileExistsError` | creation target already exists |
| `IsADirectoryError` | file operation on directory |
| `NotADirectoryError` | directory operation on file |
| `BlockingIOError` | lock timeout or open-file conflict |
| `io.UnsupportedOperation` | mode mismatch / unsupported operation |
| `ValueError` | invalid mode/path/seek/truncate arguments |

---

## Testing with pytest

D-MemFS ships a pytest plugin that provides an `mfs` fixture:

```python
# conftest.py — register the plugin explicitly
pytest_plugins = ["dmemfs._pytest_plugin"]
```

> **Note:** The plugin is **not** auto-discovered. Users must declare it in `conftest.py` to opt in.

```python
# test_example.py
def test_write_read(mfs):
    mfs.mkdir("/tmp")
    with mfs.open("/tmp/hello.txt", "wb") as f:
        f.write(b"hello")
    with mfs.open("/tmp/hello.txt", "rb") as f:
        assert f.read() == b"hello"
```

---

## Development Notes

Design documents (Japanese):

- [Architecture Spec v13](https://github.com/nightmarewalker/D-MemFS/blob/main/docs/design/spec_v13.md) — API design, internal structure, CI matrix
- [Architecture Spec v14](https://github.com/nightmarewalker/D-MemFS/blob/main/docs/design/spec_v14.md) — MemoryGuard-integrated architecture spec
- [Detailed Design Spec v2](https://github.com/nightmarewalker/D-MemFS/blob/main/docs/design/DetailedDesignSpec_v2.md) — component-level design and rationale
- [Test Design Spec v2](https://github.com/nightmarewalker/D-MemFS/blob/main/docs/design/DetailedDesignSpec_test_v2.md) — test case table and pseudocode

> These documents are written in Japanese and serve as internal design references.

---

## Performance Summary

Key results from the included benchmark (300 small files × 4 KiB, 16 MiB stream, 2 GiB large stream):

| Case | MFS (ms) | BytesIO (ms) | tempfile (ms) |
|---|---:|---:|---:|
| small_files_rw | 34 | 5 | 164 |
| stream_write_read | 64 | 51 | 17 |
| random_access_rw | **24** | 53 | 27 |
| large_stream_write_read | **1 438** | 7 594 | 1 931 |
| many_files_random_read | 777 | 163 | 4 745 |

MFS incurs a small overhead on tiny-file workloads but delivers significantly better performance on large streams and random-access patterns compared with `BytesIO`. See `BENCHMARK.md` and [benchmark_current_result.md](https://github.com/nightmarewalker/D-MemFS/blob/main/benchmarks/results/benchmark_current_result.md) for full data.

> **Note:** `tempfile` results above were measured with the system temp directory on a RAM disk. On a physical SSD/HDD, `tempfile` performance will be substantially slower.

---

## License

MIT License
