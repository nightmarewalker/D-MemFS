"""MFSTextHandle: bufferless text I/O helper.

MFS-specific text wrapper used instead of ``io.TextIOWrapper``.
Immediate quota checking, no ``readinto()`` required, no cookie seek issues.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ._handle import MemoryFileHandle

_READLINE_CHUNK = 4096


class MFSTextHandle:
    """Bufferless text I/O helper that wraps MemoryFileHandle.

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
    ...     th.write("こんにちは世界\\n")
    """

    def __init__(
        self,
        handle: MemoryFileHandle,
        encoding: str = "utf-8",
        errors: str = "strict",
    ) -> None:
        self._handle = handle
        self._encoding = encoding
        self._errors = errors

    @property
    def encoding(self) -> str:
        """Text encoding."""
        return self._encoding

    @property
    def errors(self) -> str:
        """Decode error handling."""
        return self._errors

    def write(self, text: str) -> int:
        """Encode text and write it to the handle.

        Parameters
        ----------
        text:
            The string to write.

        Returns
        -------
        int
            Number of characters written (not bytes).
        """
        data = text.encode(self._encoding, self._errors)
        self._handle.write(data)
        return len(text)

    def read(self, size: int = -1) -> str:
        """Read bytes and decode them.

        Parameters
        ----------
        size:
            Maximum number of characters to read. ``-1`` reads everything.
            Note that this is an approximation in characters, not bytes.
        """
        if size < 0:
            raw = self._handle.read()
        else:
            raw = self._handle.read(size)
        return raw.decode(self._encoding, self._errors)

    def readline(self, limit: int = -1) -> str:
        """Read one line.

        Recognizes ``\\n``, ``\\r\\n``, and bare ``\\r`` as line endings.

        Parameters
        ----------
        limit:
            Maximum number of bytes to read (``-1`` means unlimited).
        """
        buf = bytearray()
        while True:
            if limit >= 0 and len(buf) >= limit:
                break
            b = self._handle.read(1)
            if not b:
                break
            buf.extend(b)
            if b == b"\n":
                break
            if b == b"\r":
                # Peek at the next byte to determine \r\n vs bare \r
                next_b = self._handle.read(1)
                if next_b == b"\n":
                    buf.extend(next_b)
                elif next_b:
                    # Bare \r: seek back one byte
                    self._handle.seek(self._handle.tell() - 1)
                break
        return buf.decode(self._encoding, self._errors)

    def __iter__(self) -> Iterator[str]:
        """Line iterator."""
        return self

    def __next__(self) -> str:
        line = self.readline()
        if not line:
            raise StopIteration
        return line

    def __enter__(self) -> MFSTextHandle:
        return self

    def __exit__(self, *args: object) -> None:
        # Closing the handle is the responsibility of the caller's with mfs.open(...) block
        pass
