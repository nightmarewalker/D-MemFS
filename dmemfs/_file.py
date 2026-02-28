import bisect
import io
import sys
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ._quota import QuotaManager


def _calibrate_chunk_overhead(safety_mul: float = 1.5, safety_add: int = 32) -> int:
    empty_bytes_size = sys.getsizeof(b"")
    list_ptr_size = sys.getsizeof([None]) - sys.getsizeof([])
    raw = empty_bytes_size + list_ptr_size
    return int(raw * safety_mul) + safety_add


CHUNK_OVERHEAD_ESTIMATE: int = _calibrate_chunk_overhead()


class IMemoryFile(ABC):
    """Abstract base for file data storage.

    In v10+, metadata (is_dir, generation, _rw_lock) has been moved to
    DirNode/FileNode.  IMemoryFile is now pure data storage.
    """

    @abstractmethod
    def read_at(self, offset: int, size: int) -> bytes: ...

    @abstractmethod
    def write_at(
        self, offset: int, data: bytes, quota_mgr: "QuotaManager"
    ) -> "tuple[int, RandomAccessMemoryFile | None, int]":
        ...

    @abstractmethod
    def truncate(self, size: int, quota_mgr: "QuotaManager") -> None: ...

    @abstractmethod
    def get_size(self) -> int: ...

    @abstractmethod
    def get_quota_usage(self) -> int: ...

    def _bulk_load(self, data: bytes) -> None:
        """Load data directly, bypassing quota (used by import_tree / copy operations)."""
        ...


class SequentialMemoryFile(IMemoryFile):
    DEFAULT_PROMOTION_HARD_LIMIT: int = 512 * 1024 * 1024

    def __init__(self, chunk_overhead: int = CHUNK_OVERHEAD_ESTIMATE, promotion_hard_limit: int | None = None, allow_promotion: bool = True) -> None:
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

    def write_at(self, offset: int, data: bytes, quota_mgr: "QuotaManager") -> "tuple[int, RandomAccessMemoryFile | None, int]":
        if offset != self._size:
            if not self._allow_promotion:
                raise io.UnsupportedOperation(
                    "Random-access write on a sequential-only file: "
                    "promotion is disabled (default_storage='sequential')."
                )
            return self._promote_and_write(offset, data, quota_mgr)
        n = len(data)
        if n == 0:
            return 0, None, 0
        overhead = self._chunk_overhead
        with quota_mgr.reserve(n + overhead):
            self._chunks.append(data)
            self._size += n
            self._cumulative.append(self._size)
        return n, None, 0

    def truncate(self, size: int, quota_mgr: "QuotaManager") -> None:
        if size == self._size:
            return
        if size > self._size:
            # POSIX: extend with zero bytes
            pad = bytes(size - self._size)
            overhead = self._chunk_overhead
            with quota_mgr.reserve(len(pad) + overhead):
                self._chunks.append(pad)
                self._size = size
                self._cumulative.append(size)
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

    def _promote_and_write(self, offset: int, data: bytes, quota_mgr: "QuotaManager") -> "tuple[int, RandomAccessMemoryFile, int]":
        # NOTE: During promotion, both the original chunk list and the new
        # bytearray coexist temporarily, consuming ~2x the file size in memory.
        # quota_mgr.reserve(current_size) accounts for this in quota terms.
        current_size = self._size
        if current_size > self._promotion_hard_limit:
            raise io.UnsupportedOperation(
                f"Cannot promote SequentialMemoryFile: size {current_size} "
                f"exceeds hard limit {self._promotion_hard_limit}."
            )
        with quota_mgr.reserve(current_size):
            new_buf = bytearray(b"".join(self._chunks))
        old_overhead = len(self._chunks) * self._chunk_overhead
        quota_mgr.release(old_overhead)
        promoted = RandomAccessMemoryFile.from_bytearray(new_buf)
        written, _, _ = promoted.write_at(offset, data, quota_mgr)
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
        return bytes(self._buf[offset: offset + size])

    def write_at(self, offset: int, data: bytes, quota_mgr: "QuotaManager") -> "tuple[int, None, int]":
        n = len(data)
        if n == 0:
            return 0, None, 0
        current_len = len(self._buf)
        new_size = max(current_len, offset + n)
        extend = new_size - current_len
        if extend > 0:
            with quota_mgr.reserve(extend):
                if offset > current_len:
                    self._buf.extend(bytes(offset - current_len))
                    self._buf.extend(data)
                else:
                    overlap = current_len - offset
                    self._buf[offset:current_len] = data[:overlap]
                    self._buf.extend(data[overlap:])
        else:
            self._buf[offset: offset + n] = data
        return n, None, 0

    def truncate(self, size: int, quota_mgr: "QuotaManager") -> None:
        old_size = len(self._buf)
        if size == old_size:
            return
        if size > old_size:
            # POSIX: extend with zero bytes
            extend = size - old_size
            with quota_mgr.reserve(extend):
                self._buf.extend(bytes(extend))
            return
        release = old_size - size
        del self._buf[size:]
        if old_size > 0 and size <= old_size * self.SHRINK_THRESHOLD:
            self._buf = bytearray(self._buf)
        quota_mgr.release(release)

    def _bulk_load(self, data: bytes) -> None:
        """Load data directly into storage, bypassing quota management."""
        self._buf = bytearray(data)
