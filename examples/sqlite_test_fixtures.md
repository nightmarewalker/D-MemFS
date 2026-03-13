# High-Speed SQLite Test Fixtures

Testing database-driven applications often suffers from severe I/O bottlenecks when creating and destroying physical SQLite files for every test case.

While you could keep serialized databases in Python variables, this quickly becomes chaotic when test states branch out (e.g., `schema_only`, `master_data_loaded`, `user_registered`).

By combining D-MemFS with Python's SQLite `serialize()` and `deserialize()` capabilities, you can build a complete virtual directory of database snapshots. You can derive new states from existing ones and load the exact branching point you need for any test instantly via its file path.

## Why This Approach?

| Traditional Approach | D-MemFS Approach |
|---|---|
| Create a new SQLite file on disk per test | Load a serialized snapshot from RAM instantly |
| States stored in Python variables get chaotic | States organized in a virtual directory tree (`/fixtures/db/step1_schema.sqlite`) |
| Deriving states requires re-running setup | Derive once, snapshot at each branch point |
| Disk I/O bottleneck on large test suites | Zero disk I/O — pure RAM speed |
| Cleanup required after each test | No cleanup needed — data lives in RAM |

## Prerequisites

- Python 3.11+
- `pip install D-MemFS pytest`

## Key Concepts

- **`MemoryFileSystem`** — An in-process virtual filesystem with a hard memory quota. All data lives in RAM.
- **Binary-only I/O** — D-MemFS operates exclusively in binary mode (`"rb"`, `"wb"`, etc.). This pairs perfectly with SQLite's `serialize()` which returns raw bytes.
- **`serialize()` / `deserialize()`** — Built-in SQLite methods (Python 3.11+) for converting databases to/from raw bytes. Each `deserialize()` call produces a fully independent in-memory database.
- **`mkdir(path)`** — Creates directories. Intermediate directories are created automatically (like `os.makedirs`).

## Example: Managing Branching DB States

This example demonstrates how to create a tree of derived database states and load them instantly.

```
State flow:

  step1_schema     (empty table)
       |
  step2_master     (+ Admin user)
       |
  step3_users      (+ Alice, Bob)
```

```python
import sqlite3

import pytest
from dmemfs import MemoryFileSystem

# Shared D-MemFS instance for the test session.
# Default quota (256 MiB) is generous for test databases.
mfs = MemoryFileSystem()


def setup_branched_fixtures():
    """Create a tree of derived database states in D-MemFS."""
    mfs.mkdir("/fixtures/db")

    # --- State 1: Schema Only ---
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, status TEXT)"
    )
    with mfs.open("/fixtures/db/step1_schema.sqlite", "wb") as f:
        f.write(conn.serialize())

    # --- State 2: Schema + Master Data (Derived from State 1) ---
    conn.execute(
        "INSERT INTO users (id, name, status) VALUES (1, 'Admin', 'active')"
    )
    with mfs.open("/fixtures/db/step2_master.sqlite", "wb") as f:
        f.write(conn.serialize())

    # --- State 3: Master Data + Test Users (Derived from State 2) ---
    conn.execute(
        "INSERT INTO users (id, name, status) VALUES (2, 'Alice', 'pending')"
    )
    conn.execute(
        "INSERT INTO users (id, name, status) VALUES (3, 'Bob', 'active')"
    )
    with mfs.open("/fixtures/db/step3_users.sqlite", "wb") as f:
        f.write(conn.serialize())

    conn.close()


@pytest.fixture(scope="session", autouse=True)
def initialize_mfs():
    """Populate the virtual filesystem before any tests run."""
    setup_branched_fixtures()


def load_snapshot(virtual_path: str) -> sqlite3.Connection:
    """Instantly load a specific branching point of the database.

    Each call returns a completely independent in-memory database.
    Modifications in one test never affect another.
    """
    with mfs.open(virtual_path, "rb") as f:
        db_bytes = f.read()

    conn = sqlite3.connect(":memory:")
    conn.deserialize(db_bytes)
    return conn


# --- Test Cases ---


def test_initial_migration_logic():
    """Requires only the schema — no data yet."""
    conn = load_snapshot("/fixtures/db/step1_schema.sqlite")
    count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    assert count == 0


def test_admin_functions():
    """Requires schema and master data, but no regular users."""
    conn = load_snapshot("/fixtures/db/step2_master.sqlite")
    admin_name = conn.execute(
        "SELECT name FROM users WHERE id=1"
    ).fetchone()[0]
    assert admin_name == "Admin"


def test_user_activation_logic():
    """Requires a fully populated database to test state changes."""
    conn = load_snapshot("/fixtures/db/step3_users.sqlite")

    # Modify the state (isolated to this test — other tests are unaffected)
    conn.execute("UPDATE users SET status='active' WHERE name='Alice'")
    active_count = conn.execute(
        "SELECT COUNT(*) FROM users WHERE status='active'"
    ).fetchone()[0]

    # Admin (1) + Bob (1) + Alice (now active) = 3
    assert active_count == 3
```

## How to Run

```bash
# Save the above code to a file (e.g., test_sqlite_fixtures.py), then:
pip install D-MemFS pytest
pytest test_sqlite_fixtures.py -v
```

## Expected Output

```
test_sqlite_fixtures.py::test_initial_migration_logic PASSED
test_sqlite_fixtures.py::test_admin_functions PASSED
test_sqlite_fixtures.py::test_user_activation_logic PASSED
```

## Notes

- **Perfect test isolation** — Each `load_snapshot()` call creates an independent copy via `deserialize()`. Mutations in one test never leak into another.
- **Scalability** — You can add as many branch points as you need. Organize them in directories like `/fixtures/db/auth/`, `/fixtures/db/billing/`, etc.
- **Performance** — Snapshot loading is a pure in-memory operation. Even databases with thousands of rows load in microseconds.
- **Session scope** — `setup_branched_fixtures()` runs once per test session (`scope="session"`), not once per test. The virtual filesystem persists across all tests.
