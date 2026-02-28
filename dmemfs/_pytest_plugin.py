"""pytest fixture plugin.

Usage::

    # conftest.py
    pytest_plugins = ["dmemfs._pytest_plugin"]

This makes the ``mfs`` fixture automatically available::

    def test_something(mfs):
        with mfs.open("/a.txt", "wb") as f:
            f.write(b"hello")
"""

import pytest

from ._fs import MemoryFileSystem


@pytest.fixture
def mfs() -> MemoryFileSystem:
    """A :class:`MemoryFileSystem` fixture with default quota (1 MiB).

    Provides an independent instance per test (function scope).
    """
    return MemoryFileSystem(max_quota=1 * 1024 * 1024)
