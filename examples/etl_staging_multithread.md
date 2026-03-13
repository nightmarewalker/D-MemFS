# Multi-threaded Data Staging (ETL)

D-MemFS is built with thread safety as a core design principle. It uses a multi-layered locking strategy:

- **Global structure lock** (`threading.RLock`) — Protects directory tree operations (create, rename, delete).
- **Per-file read/write locks** — Allow multiple concurrent readers OR one exclusive writer per file.

This makes D-MemFS an ideal volatile staging area for Extract, Transform, Load (ETL) pipelines where multiple threads are downloading, processing, and writing data simultaneously.

## Why This Approach?

| Traditional Approach | D-MemFS Approach |
|---|---|
| Write staging files to disk (slow I/O) | Write directly to RAM (near-zero latency) |
| Manual file locking or naming conventions | Built-in per-file read/write locks |
| Manual cleanup of staging directories | Staging data vanishes with the process |
| Disk wear from frequent small writes | Zero disk wear |

## Prerequisites

- Python 3.11+
- `pip install D-MemFS`

## Key Concepts

- **`mkdir(path, exist_ok=False)`** — Creates directories, automatically creating any missing intermediate directories (like `os.makedirs`).
- **Thread-safe `open()`** — Each `open()` call acquires an appropriate lock (read lock for `"rb"`, write lock for `"wb"`, `"ab"`, etc.).
- **`lock_timeout`** — You can set a timeout for lock acquisition to avoid indefinite blocking in contentious scenarios.

## Example: Concurrent Writers

```python
import threading
import time

from dmemfs import MemoryFileSystem

mfs = MemoryFileSystem(max_quota=16 * 1024 * 1024)  # 16 MiB staging area
mfs.mkdir("/staging/raw_data")


def download_and_stage(worker_id: int) -> None:
    """Simulate downloading data and writing it to the staging area."""
    filename = f"/staging/raw_data/worker_{worker_id}.csv"

    # Simulate network latency
    time.sleep(0.05)

    # Generate CSV-like data (binary mode required)
    data = f"id,value\n{worker_id},100\n{worker_id},200\n".encode("utf-8")

    # Thread-safe write to the virtual filesystem.
    # D-MemFS automatically acquires a write lock for this file.
    with mfs.open(filename, "wb") as f:
        f.write(data)

    print(f"  Worker {worker_id}: staged {len(data)} bytes")


def main():
    print("Starting 10 concurrent workers...")
    threads = []
    for i in range(10):
        t = threading.Thread(target=download_and_stage, args=(i,))
        threads.append(t)
        t.start()

    for t in threads:
        t.join()

    # Verify all files were written safely
    files = mfs.listdir("/staging/raw_data")
    print(f"\nTotal files in staging: {len(files)}")
    assert len(files) == 10, f"Expected 10 files, got {len(files)}"

    # Read back and verify one file
    with mfs.open("/staging/raw_data/worker_0.csv", "rb") as f:
        content = f.read().decode("utf-8")
    print(f"Worker 0 data:\n{content}")

    # Show quota usage
    stats = mfs.stats()
    print(f"Quota used: {stats['used_bytes']:,} / {stats['quota_bytes']:,} bytes")


if __name__ == "__main__":
    main()
```

## Expected Output

```
Starting 10 concurrent workers...
  Worker 0: staged 24 bytes
  Worker 3: staged 24 bytes
  ...
Total files in staging: 10
Worker 0 data:
id,value
0,100
0,200

Quota used: X,XXX / 16,777,216 bytes
```

## How to Run

```bash
pip install D-MemFS
python etl_staging_multithread.py
```
