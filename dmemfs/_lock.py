import threading
import time


def _calc_deadline(timeout: float | None) -> float | None:
    if timeout is None:
        return None
    if timeout == 0.0:
        return 0.0
    return time.monotonic() + timeout


def _remaining(deadline: float | None) -> float | None:
    if deadline is None:
        return None
    r = deadline - time.monotonic()
    return max(0.0, r)


class ReadWriteLock:
    """A simple readers–writer lock.

    Multiple readers can hold the lock concurrently, but a writer requires
    exclusive access.  There is **no fairness mechanism**: if readers
    continuously acquire and release the lock, a waiting writer may starve
    indefinitely.  Callers should use ``timeout`` to bound the wait.
    """

    def __init__(self) -> None:
        self._condition = threading.Condition(threading.Lock())
        self._read_count: int = 0
        self._write_held: bool = False

    def acquire_read(self, timeout: float | None = None) -> None:
        deadline = _calc_deadline(timeout)
        with self._condition:
            while self._write_held:
                remaining = _remaining(deadline)
                if remaining == 0.0:
                    raise BlockingIOError("Could not acquire read lock within timeout.")
                if not self._condition.wait(timeout=remaining):
                    raise BlockingIOError("Could not acquire read lock within timeout.")
            self._read_count += 1

    def release_read(self) -> None:
        with self._condition:
            if self._read_count <= 0:
                raise RuntimeError("release_read called without matching acquire_read")
            self._read_count -= 1
            if self._read_count == 0:
                self._condition.notify_all()

    def acquire_write(self, timeout: float | None = None) -> None:
        deadline = _calc_deadline(timeout)
        with self._condition:
            while self._write_held or self._read_count > 0:
                remaining = _remaining(deadline)
                if remaining == 0.0:
                    raise BlockingIOError("Could not acquire write lock within timeout.")
                if not self._condition.wait(timeout=remaining):
                    raise BlockingIOError("Could not acquire write lock within timeout.")
            self._write_held = True

    def release_write(self) -> None:
        with self._condition:
            if not self._write_held:
                raise RuntimeError("release_write called without matching acquire_write")
            self._write_held = False
            self._condition.notify_all()

    @property
    def is_locked(self) -> bool:
        with self._condition:
            return self._write_held or self._read_count > 0
