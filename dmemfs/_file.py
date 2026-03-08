import bisect
import io
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ._memory_guard import MemoryGuard
    from ._quota import QuotaManager


def _wrap_memory_error(message: str) -> MemoryError:
    return MemoryError(message)


# Keep quota behavior deterministic across standard and free-threaded builds.
# A fixed conservative value avoids runtime-dependent quota boundaries.
CHUNK_OVERHEAD_ESTIMATE: int = 128


class IMemoryFile(ABC):
    """Abstract base for file data storage.

    In v10+, metadata (is_dir, generation, _rw_lock) has been moved to
    DirNode/FileNode.  IMemoryFile is now pure data storage.
    """

    @abstractmethod
    def read_at(self, offset: int, size: int) -> bytes: ...

    @abstractmethod
    def write_at(
        self,
        offset: int,
        data: bytes,
        quota_mgr: "QuotaManager",
        memory_guard: "MemoryGuard | None" = None,
    ) -> "tuple[int, RandomAccessMemoryFile | None, int]": ...

    @abstractmethod
    def truncate(
        self,
        size: int,
        quota_mgr: "QuotaManager",
        memory_guard: "MemoryGuard | None" = None,
    ) -> None: ...

    @abstractmethod
    def get_size(self) -> int: ...

    @abstractmethod
    def get_quota_usage(self) -> int: ...

    def _bulk_load(self, data: bytes) -> None:
        """Load data directly, bypassing quota (used by import_tree / copy operations)."""
        ...


class SequentialMemoryFile(IMemoryFile):
    DEFAULT_PROMOTION_HARD_LIMIT: int = 512 * 1024 * 1024

    def __init__(
        self,
        chunk_overhead: int = CHUNK_OVERHEAD_ESTIMATE,
        promotion_hard_limit: int | None = None,
        allow_promotion: bool = True,
    ) -> None:
        super().__init__()
        self._chunks: list[bytes] = []
        self._cumulative: list[int] = []
        self._size: int = 0
        self._chunk_overhead: int = chunk_overhead
        self._promotion_hard_limit: int = (
            promotion_hard_limit
            if promotion_hard_limit is not None
            else self.DEFAULT_PROMOTION_HARD_LIMIT
        )
        self._allow_promotion: bool = allow_promotion

    def get_size(self) -> int:
        return self._size

    def get_quota_usage(self) -> int:
        return self._size + len(self._chunks) * self._chunk_overhead

    def read_at(self, offset: int, size: int) -> bytes:
        if offset >= self._size or size == 0:
            return b""
        end = self._size if size < 0 else min(offset + size, self._size)
        start_idx = bisect.bisect_right(self._cumulative, offset)
        result = bytearray()
        for i in range(start_idx, len(self._chunks)):
            chunk_file_start = self._cumulative[i - 1] if i > 0 else 0
            chunk_file_end = self._cumulative[i]
            lo = max(offset, chunk_file_start) - chunk_file_start
            hi = min(end, chunk_file_end) - chunk_file_start
            result.extend(self._chunks[i][lo:hi])
            if chunk_file_end >= end:
                break
        return bytes(result)

    def write_at(
        self,
        offset: int,
        data: bytes,
        quota_mgr: "QuotaManager",
        memory_guard: "MemoryGuard | None" = None,
    ) -> "tuple[int, RandomAccessMemoryFile | None, int]":
        if offset != self._size:
            if not self._allow_promotion:
                raise io.UnsupportedOperation(
                    "Random-access write on a sequential-only file: "
                    "promotion is disabled (default_storage='sequential')."
                )
            return self._promote_and_write(offset, data, quota_mgr, memory_guard)
        n = len(data)
        if n == 0:
            return 0, None, 0
        overhead = self._chunk_overhead
        if memory_guard is not None:
            memory_guard.check_before_write(n + overhead)
        with quota_mgr.reserve(n + overhead):
            try:
                self._chunks.append(data)
                self._size += n
                self._cumulative.append(self._size)
            except MemoryError:
                raise _wrap_memory_error(
                    f"OS memory allocation failed while writing {n:,} bytes. "
                    f"MFS quota had {quota_mgr.free:,} bytes remaining. "
                    "The max_quota may exceed available system RAM. "
                    "Consider reducing max_quota or using memory_guard='init'."
                ) from None
        return n, None, 0

    def truncate(
        self,
        size: int,
        quota_mgr: "QuotaManager",
        memory_guard: "MemoryGuard | None" = None,
    ) -> None:
        if size == self._size:
            return
        if size > self._size:
            # POSIX: extend with zero bytes
            pad = bytes(size - self._size)
            overhead = self._chunk_overhead
            if memory_guard is not None:
                memory_guard.check_before_write(len(pad) + overhead)
            with quota_mgr.reserve(len(pad) + overhead):
                try:
                    self._chunks.append(pad)
                    self._size = size
                    self._cumulative.append(size)
                except MemoryError:
                    raise _wrap_memory_error(
                        f"OS memory allocation failed while extending file to {size:,} bytes. "
                        "Consider reducing max_quota or using memory_guard='init'."
                    ) from None
            return
        data = b"".join(self._chunks)[:size]
        old_overhead = len(self._chunks) * self._chunk_overhead
        self._chunks = [data] if data else []
        self._cumulative = [size] if data else []
        new_overhead = len(self._chunks) * self._chunk_overhead
        release_bytes = (self._size - size) + (old_overhead - new_overhead)
        quota_mgr.release(release_bytes)
        self._size = size

    def _bulk_load(self, data: bytes) -> None:
        """Load data directly into storage, bypassing quota management.

        Used exclusively by import_tree() and _deep_copy_subtree() where
        quota has already been pre-checked and reserved by the caller.
        """
        if data:
            self._chunks = [data]
            self._size = len(data)
            self._cumulative = [len(data)]
        else:
            self._chunks = []
            self._size = 0
            self._cumulative = []

    def _promote_and_write(
        self,
        offset: int,
        data: bytes,
        quota_mgr: "QuotaManager",
        memory_guard: "MemoryGuard | None" = None,
    ) -> "tuple[int, RandomAccessMemoryFile, int]":
        # NOTE: During promotion, both the original chunk list and the new
        # bytearray coexist temporarily, consuming ~2x the file size in memory.
        # quota_mgr.reserve(current_size) accounts for this in quota terms.
        current_size = self._size
        if current_size > self._promotion_hard_limit:
            raise io.UnsupportedOperation(
                f"Cannot promote SequentialMemoryFile: size {current_size} "
                f"exceeds hard limit {self._promotion_hard_limit}."
            )
        if memory_guard is not None:
            memory_guard.check_before_write(current_size)
        with quota_mgr.reserve(current_size):
            try:
                new_buf = bytearray(b"".join(self._chunks))
            except MemoryError:
                raise _wrap_memory_error(
                    f"OS memory allocation failed during storage promotion (file size: {current_size:,} bytes). "
                    "Consider reducing max_quota or using memory_guard='init'."
                ) from None
        old_overhead = len(self._chunks) * self._chunk_overhead
        quota_mgr.release(old_overhead)
        promoted = RandomAccessMemoryFile.from_bytearray(new_buf)
        written, _, _ = promoted.write_at(offset, data, quota_mgr, memory_guard)
        return written, promoted, current_size


class RandomAccessMemoryFile(IMemoryFile):
    SHRINK_THRESHOLD: float = 0.25

    def __init__(self, initial_data: bytes = b"") -> None:
        super().__init__()
        self._buf: bytearray = bytearray(initial_data)

    @classmethod
    def from_bytearray(cls, buf: bytearray) -> "RandomAccessMemoryFile":
        obj = cls.__new__(cls)
        IMemoryFile.__init__(obj)
        obj._buf = buf
        return obj

    def get_size(self) -> int:
        return len(self._buf)

    def get_quota_usage(self) -> int:
        return len(self._buf)

    def read_at(self, offset: int, size: int) -> bytes:
        if size < 0:
            return bytes(self._buf[offset:])
        return bytes(self._buf[offset : offset + size])

    def write_at(
        self,
        offset: int,
        data: bytes,
        quota_mgr: "QuotaManager",
        memory_guard: "MemoryGuard | None" = None,
    ) -> "tuple[int, None, int]":
        n = len(data)
        if n == 0:
            return 0, None, 0
        current_len = len(self._buf)
        new_size = max(current_len, offset + n)
        extend = new_size - current_len
        if extend > 0:
            if memory_guard is not None:
                memory_guard.check_before_write(extend)
            with quota_mgr.reserve(extend):
                try:
                    if offset > current_len:
                        self._buf.extend(bytes(offset - current_len))
                        self._buf.extend(data)
                    else:
                        overlap = current_len - offset
                        self._buf[offset:current_len] = data[:overlap]
                        self._buf.extend(data[overlap:])
                except MemoryError:
                    raise _wrap_memory_error(
                        f"OS memory allocation failed while writing {n:,} bytes. "
                        f"MFS quota had {quota_mgr.free:,} bytes remaining. "
                        "Consider reducing max_quota or using memory_guard='init'."
                    ) from None
        else:
            self._buf[offset : offset + n] = data
        return n, None, 0

    def truncate(
        self,
        size: int,
        quota_mgr: "QuotaManager",
        memory_guard: "MemoryGuard | None" = None,
    ) -> None:
        old_size = len(self._buf)
        if size == old_size:
            return
        if size > old_size:
            # POSIX: extend with zero bytes
            extend = size - old_size
            if memory_guard is not None:
                memory_guard.check_before_write(extend)
            with quota_mgr.reserve(extend):
                try:
                    self._buf.extend(bytes(extend))
                except MemoryError:
                    raise _wrap_memory_error(
                        f"OS memory allocation failed while extending file to {size:,} bytes. "
                        "Consider reducing max_quota or using memory_guard='init'."
                    ) from None
            return
        release = old_size - size
        del self._buf[size:]
        if old_size > 0 and size <= old_size * self.SHRINK_THRESHOLD:
            self._buf = bytearray(self._buf)
        quota_mgr.release(release)

    def _bulk_load(self, data: bytes) -> None:
        """Load data directly into storage, bypassing quota management."""
        self._buf = bytearray(data)
