from __future__ import annotations

import io
import time
import warnings
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ._fs import FileNode, MemoryFileSystem


class MemoryFileHandle:
    def __init__(
        self,
        mfs: MemoryFileSystem,
        fnode: FileNode,
        path: str,
        mode: str,
        is_append: bool = False,
    ) -> None:
        self._mfs = mfs
        self._fnode = fnode
        self._path = path
        self._mode = mode
        self._cursor: int = fnode.storage.get_size() if is_append else 0
        self._is_closed: bool = False
        self._is_append: bool = is_append

    def _assert_readable(self) -> None:
        if self._mode in ("wb", "ab", "xb"):
            raise io.UnsupportedOperation(f"not readable in mode '{self._mode}'")

    def _assert_writable(self) -> None:
        if self._mode == "rb":
            raise io.UnsupportedOperation(f"not writable in mode '{self._mode}'")

    def _assert_open(self) -> None:
        if self._is_closed:
            raise ValueError("I/O operation on closed file.")

    def read(self, size: int = -1) -> bytes:
        self._assert_open()
        self._assert_readable()
        storage = self._fnode.storage
        current_size = storage.get_size()
        if self._cursor >= current_size:
            return b""
        if size < 0:
            data = storage.read_at(self._cursor, current_size - self._cursor)
            self._cursor = current_size
        else:
            actual = min(size, current_size - self._cursor)
            data = storage.read_at(self._cursor, actual)
            self._cursor += actual
        return data

    def write(self, data: bytes) -> int:
        self._assert_open()
        self._assert_writable()
        if self._is_append:
            self._cursor = self._fnode.storage.get_size()
        n, promoted, old_quota = self._fnode.storage.write_at(
            self._cursor, data, self._mfs._quota
        )
        if promoted is not None:
            self._fnode.storage = promoted
            self._mfs._quota.release(old_quota)
        self._cursor += n
        if n > 0:
            self._fnode.generation += 1
            self._fnode.modified_at = time.time()
        return n

    def seek(self, offset: int, whence: int = 0) -> int:
        self._assert_open()
        if whence == 0:
            if offset < 0:
                raise ValueError("seek offset must be >= 0 for SEEK_SET")
            new_pos = offset
        elif whence == 1:
            new_pos = self._cursor + offset
        elif whence == 2:
            if offset > 0:
                raise ValueError(
                    "Seeking past end-of-file (SEEK_END with positive offset) "
                    "is not supported in MFS."
                )
            new_pos = self._fnode.storage.get_size() + offset
        else:
            raise ValueError(f"Invalid whence value: {whence}. Must be 0, 1, or 2.")
        if new_pos < 0:
            raise ValueError(f"Resulting cursor position {new_pos} is negative.")
        self._cursor = new_pos
        return self._cursor

    def tell(self) -> int:
        self._assert_open()
        return self._cursor

    def truncate(self, size: int | None = None) -> int:
        self._assert_open()
        self._assert_writable()
        target = self._cursor if size is None else size
        if target < 0:
            raise ValueError("truncate size must be >= 0")
        before = self._fnode.storage.get_size()
        self._fnode.storage.truncate(target, self._mfs._quota)
        if self._cursor > target:
            self._cursor = target
        if before != target:
            self._fnode.generation += 1
            self._fnode.modified_at = time.time()
        return target

    def flush(self) -> None:
        self._assert_open()
        return None

    def readable(self) -> bool:
        self._assert_open()
        return self._mode not in ("wb", "ab", "xb")

    def writable(self) -> bool:
        self._assert_open()
        return self._mode != "rb"

    def seekable(self) -> bool:
        self._assert_open()
        return True

    def close(self) -> None:
        if self._is_closed:
            return
        self._is_closed = True
        mode = self._mode
        if mode in ("wb", "ab", "r+b", "xb"):
            self._fnode._rw_lock.release_write()
        else:
            self._fnode._rw_lock.release_read()

    def __enter__(self) -> MemoryFileHandle:
        return self

    def __exit__(self, *args) -> None:
        self.close()

    def __del__(self) -> None:
        if not self._is_closed:
            warnings.warn(
                "MFS MemoryFileHandle was not closed properly. "
                "Always use 'with mfs.open(...) as f:' to ensure cleanup.",
                ResourceWarning,
                stacklevel=1,
            )
            try:
                self.close()
            except Exception:
                pass
