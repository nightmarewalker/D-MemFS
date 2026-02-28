<a id="dmemfs"></a>

# dmemfs

<a id="dmemfs._exceptions"></a>

# dmemfs.\_exceptions

<a id="dmemfs._exceptions.MFSQuotaExceededError"></a>

## MFSQuotaExceededError Objects

```python
class MFSQuotaExceededError(OSError)
```

Raised when the quota limit is exceeded. Subclass of OSError.

<a id="dmemfs._exceptions.MFSNodeLimitExceededError"></a>

## MFSNodeLimitExceededError Objects

```python
class MFSNodeLimitExceededError(MFSQuotaExceededError)
```

Raised when the node count limit is exceeded. Subclass of MFSQuotaExceededError.

<a id="dmemfs._typing"></a>

# dmemfs.\_typing

<a id="dmemfs._quota"></a>

# dmemfs.\_quota

<a id="dmemfs._quota.QuotaManager"></a>

## QuotaManager Objects

```python
class QuotaManager()
```

<a id="dmemfs._quota.QuotaManager.snapshot"></a>

#### snapshot

```python
def snapshot() -> tuple[int, int, int]
```

Return (maximum, used, free) atomically under a single lock.

<a id="dmemfs._lock"></a>

# dmemfs.\_lock

<a id="dmemfs._lock.ReadWriteLock"></a>

## ReadWriteLock Objects

```python
class ReadWriteLock()
```

A simple readers–writer lock.

Multiple readers can hold the lock concurrently, but a writer requires
exclusive access.  There is **no fairness mechanism**: if readers
continuously acquire and release the lock, a waiting writer may starve
indefinitely.  Callers should use ``timeout`` to bound the wait.

<a id="dmemfs._file"></a>

# dmemfs.\_file

<a id="dmemfs._file.IMemoryFile"></a>

## IMemoryFile Objects

```python
class IMemoryFile(ABC)
```

Abstract base for file data storage.

In v10+, metadata (is_dir, generation, _rw_lock) has been moved to
DirNode/FileNode.  IMemoryFile is now pure data storage.

<a id="dmemfs._path"></a>

# dmemfs.\_path

<a id="dmemfs._handle"></a>

# dmemfs.\_handle

<a id="dmemfs._fs"></a>

# dmemfs.\_fs

<a id="dmemfs._fs.MemoryFileSystem"></a>

## MemoryFileSystem Objects

```python
class MemoryFileSystem()
```

<a id="dmemfs._fs.MemoryFileSystem.export_as_bytesio"></a>

#### export\_as\_bytesio

```python
def export_as_bytesio(path: str, max_size: int | None = None) -> io.BytesIO
```

Export file contents as a BytesIO object.

Note: The returned BytesIO object is outside quota management.
Exporting large files may consume significant process memory
beyond the configured quota limit.

<a id="dmemfs._fs.MemoryFileSystem.walk"></a>

#### walk

```python
def walk(path: str = "/") -> Iterator[tuple[str, list[str], list[str]]]
```

Recursively walk the directory tree (top-down).

.. warning::
    Thread Safety (Weak Consistency):
    walk() does not hold _global_lock across iterations.
    Structural changes by other threads may cause inconsistencies.
    Deleted entries are skipped (no crash).

<a id="dmemfs._fs.MemoryFileSystem.glob"></a>

#### glob

```python
def glob(pattern: str) -> list[str]
```

Return a sorted list of paths matching *pattern*.

Supports `*` (single dir), `**` (recursive), `?`, `[seq]`.

<a id="dmemfs._async"></a>

# dmemfs.\_async

Async wrapper around MemoryFileSystem.

All I/O is delegated to :func:`asyncio.to_thread`, so the underlying
synchronous locks are never held on the event-loop thread.

<a id="dmemfs._async.AsyncMemoryFileHandle"></a>

## AsyncMemoryFileHandle Objects

```python
class AsyncMemoryFileHandle()
```

Async wrapper for a single open-file handle.

<a id="dmemfs._async.AsyncMemoryFileSystem"></a>

## AsyncMemoryFileSystem Objects

```python
class AsyncMemoryFileSystem()
```

Thin async facade over :class:`MemoryFileSystem`.

Every method delegates to the synchronous implementation via
``asyncio.to_thread``, so the event-loop is never blocked.

<a id="dmemfs._text"></a>

# dmemfs.\_text

MFSTextHandle: bufferless text I/O helper.

MFS-specific text wrapper used instead of ``io.TextIOWrapper``.
Immediate quota checking, no ``readinto()`` required, no cookie seek issues.

<a id="dmemfs._text.MFSTextHandle"></a>

## MFSTextHandle Objects

```python
class MFSTextHandle()
```

Bufferless text I/O helper that wraps MemoryFileHandle.

Parameters
----------
handle:
    Binary handle obtained from ``MemoryFileSystem.open()``.
encoding:
    Text encoding (default ``"utf-8"``).
errors:
    Decode error handling (default ``"strict"``).

Example
-------
>>> with mfs.open("/data/hello.bin", "wb") as f:
...     th = MFSTextHandle(f, encoding="utf-8")
...     th.write("こんにちは世界\n")

<a id="dmemfs._text.MFSTextHandle.encoding"></a>

#### encoding

```python
@property
def encoding() -> str
```

Text encoding.

<a id="dmemfs._text.MFSTextHandle.errors"></a>

#### errors

```python
@property
def errors() -> str
```

Decode error handling.

<a id="dmemfs._text.MFSTextHandle.write"></a>

#### write

```python
def write(text: str) -> int
```

Encode text and write it to the handle.

Parameters
----------
text:
    The string to write.

Returns
-------
int
    Number of characters written (not bytes).

<a id="dmemfs._text.MFSTextHandle.read"></a>

#### read

```python
def read(size: int = -1) -> str
```

Read bytes and decode them.

Parameters
----------
size:
    Maximum number of characters to read. ``-1`` reads everything.
    Note that this is an approximation in characters, not bytes.

<a id="dmemfs._text.MFSTextHandle.readline"></a>

#### readline

```python
def readline(limit: int = -1) -> str
```

Read one line.

Recognizes ``\n``, ``\r\n``, and bare ``\r`` as line endings.

Parameters
----------
limit:
    Maximum number of bytes to read (``-1`` means unlimited).

<a id="dmemfs._text.MFSTextHandle.__iter__"></a>

#### \_\_iter\_\_

```python
def __iter__() -> Iterator[str]
```

Line iterator.

<a id="dmemfs._pytest_plugin"></a>

# dmemfs.\_pytest\_plugin

pytest fixture plugin.

Usage::

    # conftest.py
    pytest_plugins = ["dmemfs._pytest_plugin"]

This makes the ``mfs`` fixture automatically available::

    def test_something(mfs):
        with mfs.open("/a.txt", "wb") as f:
            f.write(b"hello")

<a id="dmemfs._pytest_plugin.mfs"></a>

#### mfs

```python
@pytest.fixture
def mfs() -> MemoryFileSystem
```

A :class:`MemoryFileSystem` fixture with default quota (1 MiB).

Provides an independent instance per test (function scope).

