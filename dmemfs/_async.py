"""Async wrapper around MemoryFileSystem.

All I/O is delegated to :func:`asyncio.to_thread`, so the underlying
synchronous locks are never held on the event-loop thread.
"""

from __future__ import annotations

import asyncio
import io

from ._fs import MemoryFileSystem
from ._typing import MFSStatResult, MFSStats


class AsyncMemoryFileHandle:
    """Async wrapper for a single open-file handle."""

    def __init__(self, _sync_handle) -> None:  # type: ignore[no-untyped-def]
        self._h = _sync_handle

    async def read(self, size: int = -1) -> bytes:
        return await asyncio.to_thread(self._h.read, size)

    async def write(self, data: bytes) -> int:
        return await asyncio.to_thread(self._h.write, data)

    async def seek(self, offset: int, whence: int = 0) -> int:
        return await asyncio.to_thread(self._h.seek, offset, whence)

    async def tell(self) -> int:
        return await asyncio.to_thread(self._h.tell)

    async def truncate(self, size: int | None = None) -> int:
        return await asyncio.to_thread(self._h.truncate, size)

    async def flush(self) -> None:
        await asyncio.to_thread(self._h.flush)

    async def readable(self) -> bool:
        return await asyncio.to_thread(self._h.readable)

    async def writable(self) -> bool:
        return await asyncio.to_thread(self._h.writable)

    async def seekable(self) -> bool:
        return await asyncio.to_thread(self._h.seekable)

    async def close(self) -> None:
        await asyncio.to_thread(self._h.close)

    async def __aenter__(self) -> AsyncMemoryFileHandle:
        return self

    async def __aexit__(self, *args) -> None:  # type: ignore[no-untyped-def]
        await self.close()


class AsyncMemoryFileSystem:
    """Thin async facade over :class:`MemoryFileSystem`.

    Every method delegates to the synchronous implementation via
    ``asyncio.to_thread``, so the event-loop is never blocked.
    """

    def __init__(
        self,
        max_quota: int = 256 * 1024 * 1024,
        chunk_overhead_override: int | None = None,
        promotion_hard_limit: int | None = None,
        max_nodes: int | None = None,
        default_storage: str = "auto",
    ) -> None:
        self._sync = MemoryFileSystem(
            max_quota=max_quota,
            chunk_overhead_override=chunk_overhead_override,
            promotion_hard_limit=promotion_hard_limit,
            max_nodes=max_nodes,
            default_storage=default_storage,
        )

    async def open(
        self,
        path: str,
        mode: str = "rb",
        preallocate: int = 0,
        lock_timeout: float | None = None,
    ) -> AsyncMemoryFileHandle:
        h = await asyncio.to_thread(
            self._sync.open, path, mode, preallocate, lock_timeout
        )
        return AsyncMemoryFileHandle(h)

    async def mkdir(self, path: str, exist_ok: bool = False) -> None:
        await asyncio.to_thread(self._sync.mkdir, path, exist_ok)

    async def rename(self, src: str, dst: str) -> None:
        await asyncio.to_thread(self._sync.rename, src, dst)

    async def move(self, src: str, dst: str) -> None:
        await asyncio.to_thread(self._sync.move, src, dst)

    async def remove(self, path: str) -> None:
        await asyncio.to_thread(self._sync.remove, path)

    async def rmtree(self, path: str) -> None:
        await asyncio.to_thread(self._sync.rmtree, path)

    async def listdir(self, path: str) -> list[str]:
        return await asyncio.to_thread(self._sync.listdir, path)

    async def exists(self, path: str) -> bool:
        return await asyncio.to_thread(self._sync.exists, path)

    async def is_dir(self, path: str) -> bool:
        return await asyncio.to_thread(self._sync.is_dir, path)

    async def is_file(self, path: str) -> bool:
        return await asyncio.to_thread(self._sync.is_file, path)

    async def stat(self, path: str) -> MFSStatResult:
        return await asyncio.to_thread(self._sync.stat, path)

    async def stats(self) -> MFSStats:
        return await asyncio.to_thread(self._sync.stats)

    async def get_size(self, path: str) -> int:
        return await asyncio.to_thread(self._sync.get_size, path)

    async def export_as_bytesio(
        self, path: str, max_size: int | None = None
    ) -> io.BytesIO:
        return await asyncio.to_thread(self._sync.export_as_bytesio, path, max_size)

    async def export_tree(
        self, prefix: str = "/", only_dirty: bool = False
    ) -> dict[str, bytes]:
        return await asyncio.to_thread(self._sync.export_tree, prefix, only_dirty)

    async def import_tree(self, tree: dict[str, bytes]) -> None:
        await asyncio.to_thread(self._sync.import_tree, tree)

    async def copy(self, src: str, dst: str) -> None:
        await asyncio.to_thread(self._sync.copy, src, dst)

    async def copy_tree(self, src: str, dst: str) -> None:
        await asyncio.to_thread(self._sync.copy_tree, src, dst)

    async def walk(self, path: str = "/") -> list[tuple[str, list[str], list[str]]]:
        return await asyncio.to_thread(lambda: list(self._sync.walk(path)))

    async def glob(self, pattern: str) -> list[str]:
        return await asyncio.to_thread(self._sync.glob, pattern)
