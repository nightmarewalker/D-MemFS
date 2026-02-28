import threading
from contextlib import contextmanager

from ._exceptions import MFSQuotaExceededError


class QuotaManager:
    def __init__(self, max_quota: int) -> None:
        self._max_quota: int = max_quota
        self._used: int = 0
        self._lock: threading.Lock = threading.Lock()

    @contextmanager
    def reserve(self, size: int):
        if size <= 0:
            yield
            return
        with self._lock:
            available = self._max_quota - self._used
            if size > available:
                raise MFSQuotaExceededError(requested=size, available=available)
            self._used += size
        try:
            yield
        except BaseException:
            with self._lock:
                self._used -= size
            raise

    def release(self, size: int) -> None:
        if size <= 0:
            return
        with self._lock:
            self._used = max(0, self._used - size)

    def _force_reserve(self, size: int) -> None:
        """Internal helper: add to used bytes without limit check.

        This bypasses normal quota enforcement and must be used only when all
        of the following conditions are true:

        1) The caller holds the filesystem global lock.
        2) Available quota has already been checked by the caller.
        3) The call site is part of an atomic operation path (`import_tree` or
           `copy_tree`) that performs its own rollback/invariant handling.
        """
        if size <= 0:
            return
        with self._lock:
            self._used += size

    def snapshot(self) -> tuple[int, int, int]:
        """Return (maximum, used, free) atomically under a single lock."""
        with self._lock:
            return self._max_quota, self._used, self._max_quota - self._used

    @property
    def used(self) -> int:
        with self._lock:
            return self._used

    @property
    def free(self) -> int:
        with self._lock:
            return self._max_quota - self._used

    @property
    def maximum(self) -> int:
        return self._max_quota
