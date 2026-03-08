"""MFSTextHandle: bufferless text I/O helper.

MFS-specific text wrapper used instead of ``io.TextIOWrapper``.
Immediate quota checking, no ``readinto()`` required, no cookie seek issues.
"""

from __future__ import annotations

import codecs
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
        self._decoded_buffer = ""

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
        """
        if size < 0:
            raw = self._handle.read()
            if self._decoded_buffer:
                prefix = self._decoded_buffer
                self._decoded_buffer = ""
                return prefix + raw.decode(self._encoding, self._errors)
            return raw.decode(self._encoding, self._errors)

        if size == 0:
            return ""

        parts: list[str] = []
        remaining = size
        if self._decoded_buffer:
            take = self._decoded_buffer[:remaining]
            parts.append(take)
            self._decoded_buffer = self._decoded_buffer[len(take) :]
            remaining -= len(take)
            if remaining == 0:
                return "".join(parts)

        decoder = codecs.getincrementaldecoder(self._encoding)(errors=self._errors)
        while remaining > 0:
            chunk = self._handle.read(1)
            if not chunk:
                tail = decoder.decode(b"", final=True)
                if tail:
                    take = tail[:remaining]
                    parts.append(take)
                    self._decoded_buffer = tail[len(take) :] + self._decoded_buffer
                break
            decoded = decoder.decode(chunk, final=False)
            if not decoded:
                continue
            take = decoded[:remaining]
            parts.append(take)
            remaining -= len(take)
            if len(decoded) > len(take):
                self._decoded_buffer = decoded[len(take) :] + self._decoded_buffer
                break

        return "".join(parts)

    def readline(self, limit: int = -1) -> str:
        """Read one line.

        Recognizes ``\\n``, ``\\r\\n``, and bare ``\\r`` as line endings.

        Parameters
        ----------
        limit:
            Maximum number of characters to read (``-1`` means unlimited).
        """
        chars: list[str] = []
        while True:
            if limit >= 0 and len(chars) >= limit:
                break
            ch = self.read(1)
            if not ch:
                break
            chars.append(ch)
            if ch == "\n":
                break
            if ch == "\r":
                next_ch = self.read(1)
                if next_ch == "\n":
                    chars.append(next_ch)
                elif next_ch:
                    self._decoded_buffer = next_ch + self._decoded_buffer
                break
        return "".join(chars)

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
