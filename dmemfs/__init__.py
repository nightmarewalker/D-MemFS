from typing import TYPE_CHECKING

from ._exceptions import MFSNodeLimitExceededError, MFSQuotaExceededError
from ._fs import MemoryFileSystem
from ._handle import MemoryFileHandle
from ._text import MFSTextHandle
from ._typing import MFSStatResult, MFSStats

if TYPE_CHECKING:
    from ._async import AsyncMemoryFileHandle, AsyncMemoryFileSystem


def __getattr__(name: str):  # type: ignore[no-untyped-def]
    if name in ("AsyncMemoryFileSystem", "AsyncMemoryFileHandle"):
        from ._async import AsyncMemoryFileHandle, AsyncMemoryFileSystem

        globals()["AsyncMemoryFileSystem"] = AsyncMemoryFileSystem
        globals()["AsyncMemoryFileHandle"] = AsyncMemoryFileHandle
        return globals()[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "MemoryFileSystem",
    "MemoryFileHandle",
    "MFSQuotaExceededError",
    "MFSNodeLimitExceededError",
    "MFSStats",
    "MFSStatResult",
    "MFSTextHandle",
    "AsyncMemoryFileSystem",
    "AsyncMemoryFileHandle",
]
__version__ = "0.2.0"
