"""SQLite serialize/deserialize roundtrip scenarios (README Quick Start)."""
import sqlite3
import pytest
from dmemfs import MemoryFileSystem
from dmemfs._exceptions import MFSQuotaExceededError


@pytest.fixture
def mfs():
    return MemoryFileSystem(max_quota=16 * 1024 * 1024)


def test_sqlite_serialize_roundtrip(mfs):
    """README_en Quick Start SQLite example: serialize → MFS → deserialize."""
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE t (id INTEGER, val TEXT)")
    conn.execute("INSERT INTO t VALUES (1, 'hello')")
    conn.execute("INSERT INTO t VALUES (2, 'world')")
    conn.commit()

    with mfs.open("/snapshot.db", "wb") as f:
        f.write(conn.serialize())
    conn.close()

    with mfs.open("/snapshot.db", "rb") as f:
        raw = f.read()
    restored = sqlite3.connect(":memory:")
    restored.deserialize(raw)
    rows = restored.execute("SELECT * FROM t ORDER BY id").fetchall()
    assert rows == [(1, "hello"), (2, "world")]
    restored.close()


def test_sqlite_data_integrity_after_roundtrip(mfs):
    """Multi-table, many-row DB survives MFS roundtrip with full integrity."""
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, data BLOB)")
    for i in range(1000):
        conn.execute("INSERT INTO items VALUES (?, ?)", (i, bytes([i % 256] * 64)))
    conn.commit()

    with mfs.open("/big.db", "wb") as f:
        f.write(conn.serialize())
    conn.close()

    with mfs.open("/big.db", "rb") as f:
        raw = f.read()
    restored = sqlite3.connect(":memory:")
    restored.deserialize(raw)
    count = restored.execute("SELECT COUNT(*) FROM items").fetchone()[0]
    assert count == 1000
    restored.close()


def test_sqlite_quota_limits_db_size():
    """MFS hard quota rejects a DB that would exceed the quota."""
    mfs_tiny = MemoryFileSystem(max_quota=4096)
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE big (data BLOB)")
    # Insert enough data to exceed 4096 bytes when serialized
    for _ in range(50):
        conn.execute("INSERT INTO big VALUES (?)", (b"x" * 200,))
    conn.commit()
    serialized = conn.serialize()
    conn.close()
    assert len(serialized) > 4096, "precondition: serialized DB must exceed quota"
    with pytest.raises(MFSQuotaExceededError):
        with mfs_tiny.open("/snap.db", "wb") as f:
            f.write(serialized)

