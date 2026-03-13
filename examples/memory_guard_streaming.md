# Safe Large File Processing (Memory Guard)

In serverless or containerized environments, reading a massive file into memory can easily trigger an Out-Of-Memory (OOM) kill, bringing down the entire process without warning.

D-MemFS provides a two-layered defense:

1. **Hard Quota** — A logical byte limit (`max_quota`). Writes exceeding this limit are rejected *before* allocation with `MFSQuotaExceededError`.
2. **Memory Guard** — An active check against the host OS's actual free physical RAM. This catches scenarios where the quota is set higher than the available RAM.

By streaming data chunk-by-chunk, D-MemFS checks the host's available memory before every write, safely raising a catchable exception instead of crashing the system.

## Why This Approach?

| Traditional Approach | D-MemFS Approach |
|---|---|
| OS OOM killer terminates the process without warning | `MemoryError` is raised as a catchable Python exception |
| No way to know available RAM from application code | Memory Guard actively queries OS free memory |
| Need OS-level RAM disk (requires root/admin) | Works as a user-space library — no privileges needed |

## Prerequisites

- Python 3.11+
- `pip install D-MemFS`

## Key Concepts

### Memory Guard Modes

| Mode | Behavior | Overhead |
|---|---|---|
| `"none"` (default) | No OS memory checking | Zero |
| `"init"` | Check once at `MemoryFileSystem()` construction | Negligible |
| `"per_write"` | Cached check before every write operation | ~1 OS call/sec |

### Memory Guard Actions

| Action | Behavior |
|---|---|
| `"warn"` (default) | Emit `ResourceWarning` and allow the operation to continue |
| `"raise"` | Reject the operation with `MemoryError` before allocation |

## Example: Streaming with Safety

This example demonstrates chunk-by-chunk processing with Memory Guard protection. It creates dummy data to be fully self-contained.

```python
from dmemfs import MemoryFileSystem, MFSQuotaExceededError

# Enable Memory Guard to actively check host RAM before every write.
mfs = MemoryFileSystem(
    max_quota=2 * 1024 * 1024,        # 2 MiB logical quota
    memory_guard="per_write",          # Check OS memory before each write
    memory_guard_action="raise",       # Raise MemoryError if RAM is insufficient
    memory_guard_interval=1.0,         # Query OS at most once per second (cached)
)


def process_stream_safely(total_size: int, chunk_size: int = 8192) -> None:
    """
    Simulate streaming a large file into D-MemFS chunk-by-chunk.

    Each write is protected by both the hard quota and the Memory Guard.
    If either limit is breached, a catchable exception is raised.
    """
    dest_path = "/processed.dat"
    bytes_written = 0

    try:
        with mfs.open(dest_path, "wb") as f:
            remaining = total_size
            while remaining > 0:
                size = min(chunk_size, remaining)
                chunk = bytes(size)  # Dummy data (zero-filled)
                f.write(chunk)
                bytes_written += size
                remaining -= size

        print(f"Stream processed successfully: {bytes_written:,} bytes written.")

    except MFSQuotaExceededError as e:
        # Hard quota limit reached — the write was rejected safely.
        print(f"Quota limit reached after {bytes_written:,} bytes: {e}")
        if mfs.exists(dest_path):
            mfs.remove(dest_path)

    except MemoryError as e:
        # Memory Guard detected insufficient physical RAM.
        print(f"Memory Guard halted processing after {bytes_written:,} bytes: {e}")
        if mfs.exists(dest_path):
            mfs.remove(dest_path)


if __name__ == "__main__":
    # Case 1: Within quota — should succeed
    print("--- Case 1: Within quota (1 MiB) ---")
    process_stream_safely(1 * 1024 * 1024)

    # Clean up for next case
    if mfs.exists("/processed.dat"):
        mfs.remove("/processed.dat")

    # Case 2: Exceeds quota — should be caught safely
    print("\n--- Case 2: Exceeds quota (4 MiB into 2 MiB quota) ---")
    process_stream_safely(4 * 1024 * 1024)
```

## Expected Output

```
--- Case 1: Within quota (1 MiB) ---
Stream processed successfully: 1,048,576 bytes written.

--- Case 2: Exceeds quota (4 MiB into 2 MiB quota) ---
Quota limit reached after 2,XXX,XXX bytes: ...
```

## How to Run

```bash
pip install D-MemFS
python memory_guard_streaming.py
```
