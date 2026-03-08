"""Physical memory guard strategies for D-MemFS."""

from __future__ import annotations

import threading
import time
import warnings
from abc import ABC, abstractmethod

from ._memory_info import get_available_memory_bytes


class MemoryGuard(ABC):
    def __init__(self, action: str = "warn") -> None:
        if action not in ("warn", "raise"):
            raise ValueError(
                f"Invalid memory_guard_action: {action!r}. Expected 'warn' or 'raise'."
            )
        self._action = action

    @abstractmethod
    def check_init(self, max_quota: int) -> None: ...

    @abstractmethod
    def check_before_write(self, size: int) -> None: ...

    def _handle_violation(self, message: str) -> None:
        if self._action == "raise":
            raise MemoryError(message)
        warnings.warn(message, ResourceWarning, stacklevel=4)


class NullGuard(MemoryGuard):
    def __init__(self) -> None:
        super().__init__(action="warn")

    def check_init(self, max_quota: int) -> None:
        return None

    def check_before_write(self, size: int) -> None:
        return None


class InitGuard(MemoryGuard):
    def check_init(self, max_quota: int) -> None:
        avail = get_available_memory_bytes()
        if avail is not None and max_quota > avail:
            self._handle_violation(
                f"max_quota ({max_quota:,} bytes) exceeds available physical RAM "
                f"({avail:,} bytes). MemoryError may occur before quota limit is reached."
            )

    def check_before_write(self, size: int) -> None:
        return None


class PerWriteGuard(MemoryGuard):
    def __init__(self, action: str = "warn", interval: float = 1.0) -> None:
        super().__init__(action=action)
        self._interval = interval
        self._last_check = 0.0
        self._last_avail: int | None = None
        self._lock = threading.Lock()

    def check_init(self, max_quota: int) -> None:
        avail = get_available_memory_bytes()
        if avail is not None and max_quota > avail:
            self._handle_violation(
                f"max_quota ({max_quota:,} bytes) exceeds available physical RAM "
                f"({avail:,} bytes). MemoryError may occur before quota limit is reached."
            )
        with self._lock:
            self._last_avail = avail
            self._last_check = time.monotonic()

    def check_before_write(self, size: int) -> None:
        now = time.monotonic()
        with self._lock:
            if now - self._last_check >= self._interval:
                self._last_avail = get_available_memory_bytes()
                self._last_check = now
            avail = self._last_avail
            age = now - self._last_check
        if avail is not None and size > avail:
            self._handle_violation(
                f"Write of {size:,} bytes requested but only {avail:,} bytes of "
                f"physical RAM available (checked {age:.1f}s ago)."
            )


def create_memory_guard(
    mode: str = "none",
    action: str = "warn",
    interval: float = 1.0,
) -> MemoryGuard:
    if action not in ("warn", "raise"):
        raise ValueError(f"Invalid memory_guard_action: {action!r}. Expected 'warn' or 'raise'.")
    if mode == "none":
        return NullGuard()
    if mode == "init":
        return InitGuard(action=action)
    if mode == "per_write":
        return PerWriteGuard(action=action, interval=interval)
    raise ValueError(f"Invalid memory_guard: {mode!r}. Expected 'none', 'init', or 'per_write'.")
