# Archive Extraction In-Memory

Extracting large archives (ZIP, TAR) to physical disk generates massive I/O load, wears down SSDs (TBW), and risks leaving garbage files behind if a process crashes mid-extraction.

By extracting directly into D-MemFS, you keep all operations in RAM. It's faster, perfectly clean, and automatically garbage-collected when the filesystem instance goes out of scope.

## Why This Approach?

| Traditional Approach | D-MemFS Approach |
|---|---|
| Extract to disk — slow I/O, disk wear | Extract to RAM — near-instant |
| Crashed process leaves orphaned files | RAM is cleaned up automatically |
| Need `try/finally` cleanup logic | No cleanup needed |
| Large archives may fill disk | Controlled by hard quota |

## Prerequisites

- Python 3.11+
- `pip install D-MemFS`

## Key Concepts

- **`mkdir(path, exist_ok=True)`** — Creates directories safely even if they already exist. Intermediate directories are created automatically.
- **Binary I/O** — ZIP `source.read()` returns `bytes`, which can be written directly to D-MemFS in `"wb"` mode.
- **`walk()`** — Recursively traverse the virtual directory tree, similar to `os.walk()`.

## Example: Extracting a ZIP File to RAM

This example is fully self-contained. It creates a dummy ZIP archive in memory, then extracts it entirely into D-MemFS.

```python
import io
import zipfile

from dmemfs import MemoryFileSystem

mfs = MemoryFileSystem(max_quota=64 * 1024 * 1024)  # 64 MiB


def create_dummy_zip() -> bytes:
    """Create a ZIP archive in memory for demonstration purposes."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("README.txt", "This is a sample archive.")
        zf.writestr("data/config.json", '{"key": "value", "count": 42}')
        zf.writestr("data/records.csv", "id,name\n1,Alice\n2,Bob\n3,Charlie\n")
        zf.writestr("data/nested/deep.txt", "Deeply nested file content.")
    return buf.getvalue()


def extract_zip_to_mfs(zip_bytes: bytes, prefix: str = "/") -> None:
    """
    Extract a ZIP archive entirely into D-MemFS.

    All file contents are read from the ZIP and written to the
    virtual filesystem. No physical disk I/O occurs.
    """
    with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zf:
        for info in zf.infolist():
            virtual_path = prefix.rstrip("/") + "/" + info.filename

            if info.is_dir():
                mfs.mkdir(virtual_path, exist_ok=True)
                continue

            # Ensure parent directory exists
            parent = "/".join(virtual_path.split("/")[:-1])
            if parent and not mfs.exists(parent):
                mfs.mkdir(parent)

            # Read from ZIP and write directly to D-MemFS
            with zf.open(info) as source:
                data = source.read()
            with mfs.open(virtual_path, "wb") as target:
                target.write(data)


def main():
    # Step 1: Create a dummy ZIP archive
    zip_bytes = create_dummy_zip()
    print(f"ZIP archive size: {len(zip_bytes):,} bytes")

    # Step 2: Extract into D-MemFS
    print("\nExtracting into D-MemFS...")
    extract_zip_to_mfs(zip_bytes, prefix="/archive")

    # Step 3: List all extracted files using walk()
    print("\nExtracted files:")
    for dirpath, dirnames, filenames in mfs.walk("/archive"):
        for fname in filenames:
            full_path = dirpath.rstrip("/") + "/" + fname
            size = mfs.get_size(full_path)
            print(f"  {full_path} ({size} bytes)")

    # Step 4: Read back a specific file
    with mfs.open("/archive/data/config.json", "rb") as f:
        config = f.read().decode("utf-8")
    print(f"\nconfig.json content: {config}")

    # Step 5: Show quota usage
    stats = mfs.stats()
    print(f"\nQuota: {stats['used_bytes']:,} / {stats['quota_bytes']:,} bytes used")
    print(f"Files: {stats['file_count']}, Directories: {stats['dir_count']}")


if __name__ == "__main__":
    main()
```

## Expected Output

```
ZIP archive size: XXX bytes

Extracting into D-MemFS...

Extracted files:
  /archive/README.txt (25 bytes)
  /archive/data/config.json (29 bytes)
  /archive/data/records.csv (33 bytes)
  /archive/data/nested/deep.txt (26 bytes)

config.json content: {"key": "value", "count": 42}

Quota: X,XXX / 67,108,864 bytes used
Files: 4, Directories: 4
```

## How to Run

```bash
pip install D-MemFS
python archive_extraction.py
```
