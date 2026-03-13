# CI/CD Pipelines & Test Debugging

Running tests against an in-memory filesystem makes your CI pipelines incredibly fast and prevents host disk pollution. However, when a test fails, you lose the state of the filesystem.

D-MemFS solves this with the `export_tree()` method. You can dump the entire virtual filesystem state to a Python dictionary, then write it to physical disk **only when an error occurs**, allowing you to inspect the exact state of the files post-mortem.

## Why This Approach?

| Traditional Approach | D-MemFS Approach |
|---|---|
| Tests write to real disk, causing I/O overhead | Tests write to RAM — near-zero I/O latency |
| Failed tests leave stale files behind | All files vanish with the process — clean by default |
| Debugging requires manually recreating state | `export_tree()` snapshots the exact failure state |

## Prerequisites

- Python 3.11+
- `pip install D-MemFS`

## Key Concepts

- **`export_tree(prefix)`** — Returns a `dict[str, bytes]` of all files under `prefix`. Keys are virtual paths; values are raw file contents.
- **Binary-only I/O** — D-MemFS `open()` only supports binary modes (`"wb"`, `"rb"`, etc.). Encode strings to bytes with `.encode()` when writing.
- **`mkdir(path)`** — Creates directories. Intermediate directories are created automatically (like `os.makedirs`).

## Example: Export on Failure

```python
import os
import traceback

from dmemfs import MemoryFileSystem

mfs = MemoryFileSystem()


def run_complex_io_task():
    """Simulate an application writing various files to the virtual FS."""
    mfs.mkdir("/app/logs")

    with mfs.open("/app/logs/process.log", "wb") as f:
        f.write(b"Task started...\n")
        f.write(b"Processing data...\n")

    with mfs.open("/app/data.txt", "wb") as f:
        f.write(b"Important state data")

    # Simulate a critical failure
    raise RuntimeError("Unexpected data format encountered.")


def export_mfs_to_disk(dump_dir: str) -> None:
    """
    Export the entire in-memory filesystem to physical disk for debugging.

    export_tree() returns a dict[str, bytes] mapping virtual paths to file contents.
    We then write each entry to the physical filesystem.
    """
    tree = mfs.export_tree("/")
    for virtual_path, data in tree.items():
        # Convert virtual path (e.g., "/app/logs/process.log") to a real path
        real_path = os.path.join(dump_dir, virtual_path.lstrip("/"))
        os.makedirs(os.path.dirname(real_path), exist_ok=True)
        with open(real_path, "wb") as f:
            f.write(data)


def main():
    try:
        run_complex_io_task()
    except Exception as e:
        print(f"Task Failed: {e}")

        dump_dir = "./failed_test_dump"
        print(f"Exporting virtual filesystem to: {dump_dir}")
        export_mfs_to_disk(dump_dir)
        print("Export complete. Files written:")
        for root, dirs, files in os.walk(dump_dir):
            for name in files:
                print(f"  {os.path.join(root, name)}")

        traceback.print_exc()


if __name__ == "__main__":
    main()
```

## Expected Output

```
Task Failed: Unexpected data format encountered.
Exporting virtual filesystem to: ./failed_test_dump
Export complete. Files written:
  failed_test_dump\app\logs\process.log
  failed_test_dump\app\data.txt
...
```

## How to Run

```bash
pip install D-MemFS
python ci_debug_export.py
```

After running, inspect the `failed_test_dump/` directory to see the exact state of files at the moment of failure.
