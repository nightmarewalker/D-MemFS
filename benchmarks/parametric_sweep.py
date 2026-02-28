"""Parametric benchmark sweep: vary file size, file count, and directory depth."""
from __future__ import annotations

import gc
import importlib
import io
import os
import sys
import tempfile
import time
import tracemalloc
from typing import Callable

from dmemfs import MemoryFileSystem


def _measure(fn: Callable[[], None]) -> tuple[float, float]:
    """Run fn once, return (elapsed_sec, peak_kib)."""
    gc.collect()
    tracemalloc.start()
    t0 = time.perf_counter()
    fn()
    elapsed = time.perf_counter() - t0
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    gc.collect()
    return elapsed, peak / 1024.0


# ---------------------------------------------------------------------------
#  Stream write+read (vary file size)
# ---------------------------------------------------------------------------

def _stream_mfs(total: int, chunk: int) -> None:
    mfs = MemoryFileSystem(max_quota=total * 3)
    c = b"S" * chunk
    with mfs.open("/f.bin", "wb") as f:
        written = 0
        while written < total:
            n = min(chunk, total - written)
            f.write(c[:n])
            written += n
    with mfs.open("/f.bin", "rb") as f:
        read = 0
        while True:
            d = f.read(chunk)
            if not d:
                break
            read += len(d)
    assert read == total


def _stream_bytesio(total: int, chunk: int) -> None:
    c = b"S" * chunk
    bio = io.BytesIO()
    written = 0
    while written < total:
        n = min(chunk, total - written)
        bio.write(c[:n])
        written += n
    bio.seek(0)
    read = 0
    while True:
        d = bio.read(chunk)
        if not d:
            break
        read += len(d)
    assert read == total


def _stream_tempfile(total: int, chunk: int) -> None:
    c = b"S" * chunk
    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, "f.bin")
        with open(p, "wb") as f:
            written = 0
            while written < total:
                n = min(chunk, total - written)
                f.write(c[:n])
                written += n
        with open(p, "rb") as f:
            read = 0
            while True:
                d = f.read(chunk)
                if not d:
                    break
                read += len(d)
    assert read == total


def _stream_pyfs2(total: int, chunk: int) -> None:
    MemoryFS = importlib.import_module("fs.memoryfs").MemoryFS
    c = b"S" * chunk
    with MemoryFS() as memfs:
        with memfs.openbin("f.bin", "w") as f:
            written = 0
            while written < total:
                n = min(chunk, total - written)
                f.write(c[:n])
                written += n
        with memfs.openbin("f.bin", "r") as f:
            read = 0
            while True:
                d = f.read(chunk)
                if not d:
                    break
                read += len(d)
    assert read == total

def _many_mfs(count: int, fsize: int) -> None:
    import random
    mfs = MemoryFileSystem(max_quota=2 * 1024 * 1024 * 1024)
    payload = b"m" * fsize
    for i in range(count):
        with mfs.open(f"/f{i:06d}.bin", "wb") as f:
            f.write(payload)
    gen = random.Random(42)
    reads = count // 2
    total = 0
    for _ in range(reads):
        idx = gen.randint(0, count - 1)
        with mfs.open(f"/f{idx:06d}.bin", "rb") as f:
            total += len(f.read())
    assert total == reads * fsize


def _many_bytesio(count: int, fsize: int) -> None:
    import random
    payload = b"m" * fsize
    files: dict[int, bytes] = {}
    for i in range(count):
        files[i] = payload
    gen = random.Random(42)
    reads = count // 2
    total = 0
    for _ in range(reads):
        idx = gen.randint(0, count - 1)
        total += len(files[idx])
    assert total == reads * fsize


def _many_tempfile(count: int, fsize: int) -> None:
    import random
    payload = b"m" * fsize
    gen = random.Random(42)
    reads = count // 2
    indices = [gen.randint(0, count - 1) for _ in range(reads)]
    with tempfile.TemporaryDirectory() as td:
        for i in range(count):
            with open(os.path.join(td, f"f{i:06d}.bin"), "wb") as f:
                f.write(payload)
        total = 0
        for idx in indices:
            with open(os.path.join(td, f"f{idx:06d}.bin"), "rb") as f:
                total += len(f.read())
    assert total == reads * fsize


def _many_pyfs2(count: int, fsize: int) -> None:
    import random
    MemoryFS = importlib.import_module("fs.memoryfs").MemoryFS
    payload = b"m" * fsize
    gen = random.Random(42)
    reads = count // 2
    with MemoryFS() as memfs:
        for i in range(count):
            with memfs.openbin(f"f{i:06d}.bin", "w") as f:
                f.write(payload)
        total = 0
        for _ in range(reads):
            idx = gen.randint(0, count - 1)
            with memfs.openbin(f"f{idx:06d}.bin", "r") as f:
                total += len(f.read())
    assert total == reads * fsize


# ---------------------------------------------------------------------------
#  Deep tree read (vary depth)
# ---------------------------------------------------------------------------

def _deep_mfs(depth: int) -> None:
    mfs = MemoryFileSystem(max_quota=1024 * 1024 * 1024)
    parts = [f"d{i}" for i in range(depth)]
    for d in range(1, depth + 1):
        mfs.mkdir("/" + "/".join(parts[:d]), exist_ok=True)
    deep = "/" + "/".join(parts) + "/file.bin"
    with mfs.open(deep, "wb") as f:
        f.write(b"d" * 1024)
    total = 0
    for _ in range(1000):
        with mfs.open(deep, "rb") as f:
            total += len(f.read())
    assert total == 1000 * 1024


def _deep_bytesio(depth: int) -> None:
    parts = [f"d{i}" for i in range(depth)]
    key = "/" + "/".join(parts) + "/file.bin"
    data = b"d" * 1024
    files = {key: data}
    total = 0
    for _ in range(1000):
        total += len(files[key])
    assert total == 1000 * 1024


def _deep_tempfile(depth: int) -> None:
    with tempfile.TemporaryDirectory() as td:
        parts = [f"d{i}" for i in range(depth)]
        ddir = os.path.join(td, *parts)
        os.makedirs(ddir, exist_ok=True)
        deep = os.path.join(ddir, "file.bin")
        with open(deep, "wb") as f:
            f.write(b"d" * 1024)
        total = 0
        for _ in range(1000):
            with open(deep, "rb") as f:
                total += len(f.read())
    assert total == 1000 * 1024


def _deep_pyfs2(depth: int) -> None:
    MemoryFS = importlib.import_module("fs.memoryfs").MemoryFS
    parts = [f"d{i}" for i in range(depth)]
    deep_dir = "/".join(parts)
    with MemoryFS() as memfs:
        memfs.makedirs(deep_dir, recreate=True)
        deep_file = deep_dir + "/file.bin"
        with memfs.openbin(deep_file, "w") as f:
            f.write(b"d" * 1024)
        total = 0
        for _ in range(1000):
            with memfs.openbin(deep_file, "r") as f:
                total += len(f.read())
    assert total == 1000 * 1024


# ---------------------------------------------------------------------------
#  Runner
# ---------------------------------------------------------------------------

def _fmt(v: float) -> str:
    if v >= 1000:
        return f"{v:,.0f}"
    return f"{v:.2f}"


def _size_label(b: int) -> str:
    if b < 1024:
        return f"{b}B"
    if b < 1024 * 1024:
        return f"{b // 1024}KB"
    if b < 1024 * 1024 * 1024:
        return f"{b // (1024 * 1024)}MB"
    return f"{b / (1024 * 1024 * 1024):.0f}GB"


def run_sweep() -> str:
    lines: list[str] = []
    chunk = 64 * 1024  # 64KB base chunk

    # === 1. Stream size sweep ===
    sizes = [
        10 * 1024,           # 10KB
        100 * 1024,          # 100KB
        1024 * 1024,         # 1MB
        10 * 1024 * 1024,    # 10MB
        100 * 1024 * 1024,   # 100MB
        1024 * 1024 * 1024,  # 1GB
        2 * 1024 * 1024 * 1024,  # 2GB
    ]

    lines.append("## 1. Stream write+read by file size")
    lines.append("")
    lines.append("chunk = 64KB (or file size if smaller)")
    lines.append("")
    lines.append("| Size | MFS ms | MFS KiB | BytesIO ms | BytesIO KiB | PyFS2 ms | PyFS2 KiB | tempfile ms | tempfile KiB |")
    lines.append("|---:|---:|---:|---:|---:|---:|---:|---:|---:|")

    for sz in sizes:
        c = min(chunk, sz)
        label = _size_label(sz)
        print(f"  stream {label} ...", end=" ", flush=True)

        t1, m1 = _measure(lambda: _stream_mfs(sz, c))
        t2, m2 = _measure(lambda: _stream_bytesio(sz, c))
        t4, m4 = _measure(lambda: _stream_pyfs2(sz, c))
        t3, m3 = _measure(lambda: _stream_tempfile(sz, c))

        lines.append(
            f"| {label} | {_fmt(t1*1000)} | {_fmt(m1)} "
            f"| {_fmt(t2*1000)} | {_fmt(m2)} "
            f"| {_fmt(t4*1000)} | {_fmt(m4)} "
            f"| {_fmt(t3*1000)} | {_fmt(m3)} |"
        )
        print(f"done (MFS={t1*1000:.0f}ms)")

    lines.append("")

    # === 2. Many files sweep ===
    counts = [10, 50, 100, 300, 500, 1000, 2000, 5000, 8000, 10000]
    fsize = 4096  # 4KB per file

    lines.append("## 2. Many files random read by file count")
    lines.append("")
    lines.append("file_size = 4KB, reads = count/2")
    lines.append("")
    lines.append("| Count | MFS ms | MFS KiB | BytesIO ms | BytesIO KiB | PyFS2 ms | PyFS2 KiB | tempfile ms | tempfile KiB |")
    lines.append("|---:|---:|---:|---:|---:|---:|---:|---:|---:|")

    for cnt in counts:
        print(f"  many_files {cnt} ...", end=" ", flush=True)

        t1, m1 = _measure(lambda: _many_mfs(cnt, fsize))
        t2, m2 = _measure(lambda: _many_bytesio(cnt, fsize))
        t4, m4 = _measure(lambda: _many_pyfs2(cnt, fsize))
        t3, m3 = _measure(lambda: _many_tempfile(cnt, fsize))

        lines.append(
            f"| {cnt:,} | {_fmt(t1*1000)} | {_fmt(m1)} "
            f"| {_fmt(t2*1000)} | {_fmt(m2)} "
            f"| {_fmt(t4*1000)} | {_fmt(m4)} "
            f"| {_fmt(t3*1000)} | {_fmt(m3)} |"
        )
        print(f"done (MFS={t1*1000:.0f}ms)")

    lines.append("")

    # === 3. Deep tree sweep ===
    depths = [10, 20, 30, 40, 50]

    lines.append("## 3. Deep tree read by directory depth")
    lines.append("")
    lines.append("1KB file at deepest level, 1000 reads")
    lines.append("")
    lines.append("| Depth | MFS ms | MFS KiB | BytesIO ms | BytesIO KiB | PyFS2 ms | PyFS2 KiB | tempfile ms | tempfile KiB |")
    lines.append("|---:|---:|---:|---:|---:|---:|---:|---:|---:|")

    for dep in depths:
        print(f"  deep_tree {dep} ...", end=" ", flush=True)

        t1, m1 = _measure(lambda: _deep_mfs(dep))
        t2, m2 = _measure(lambda: _deep_bytesio(dep))
        t4, m4 = _measure(lambda: _deep_pyfs2(dep))
        t3, m3 = _measure(lambda: _deep_tempfile(dep))

        lines.append(
            f"| {dep} | {_fmt(t1*1000)} | {_fmt(m1)} "
            f"| {_fmt(t2*1000)} | {_fmt(m2)} "
            f"| {_fmt(t4*1000)} | {_fmt(m4)} "
            f"| {_fmt(t3*1000)} | {_fmt(m3)} |"
        )
        print(f"done (MFS={t1*1000:.0f}ms)")

    lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    print("=== Parametric Benchmark Sweep ===\n")
    result = run_sweep()
    print("\n" + result)

    # Save to file
    from datetime import datetime
    from pathlib import Path
    out_dir = Path("benchmarks") / "results"
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = out_dir / f"parametric_sweep_{ts}.md"
    out_path.write_text(f"# Parametric Benchmark Sweep\n\n{result}", encoding="utf-8")
    print(f"\nSaved: {out_path}")
