from __future__ import annotations

import argparse
from datetime import datetime
import importlib
import io
import json
import os
from pathlib import Path
import statistics
import tempfile
import time
import tracemalloc
from dataclasses import dataclass
from typing import Callable

from dmemfs import MemoryFileSystem


@dataclass
class CaseResult:
    backend: str
    case: str
    seconds_mean: float
    seconds_min: float
    seconds_max: float
    peak_kib_mean: float


def _run_with_memory(fn: Callable[[], None]) -> tuple[float, float]:
    tracemalloc.start()
    start = time.perf_counter()
    fn()
    elapsed = time.perf_counter() - start
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return elapsed, peak / 1024.0


def bench_mfs_small_files(file_count: int, file_size: int) -> None:
    mfs = MemoryFileSystem(max_quota=1024 * 1024 * 1024)
    mfs.mkdir("/bench")
    payload = b"x" * file_size
    for i in range(file_count):
        with mfs.open(f"/bench/f{i:05d}.bin", "wb") as f:
            f.write(payload)
    total = 0
    for i in range(file_count):
        with mfs.open(f"/bench/f{i:05d}.bin", "rb") as f:
            total += len(f.read())
    if total != file_count * file_size:
        raise RuntimeError("MFS small-files benchmark validation failed")


def bench_bytesio_small_files(file_count: int, file_size: int) -> None:
    files: dict[str, io.BytesIO] = {}
    payload = b"x" * file_size
    for i in range(file_count):
        path = f"/bench/f{i:05d}.bin"
        bio = io.BytesIO()
        bio.write(payload)
        files[path] = bio
    total = 0
    for i in range(file_count):
        path = f"/bench/f{i:05d}.bin"
        total += len(files[path].getvalue())
    if total != file_count * file_size:
        raise RuntimeError("BytesIO small-files benchmark validation failed")


def bench_tempfs_small_files(file_count: int, file_size: int) -> None:
    payload = b"x" * file_size
    with tempfile.TemporaryDirectory() as td:
        root = os.path.join(td, "bench")
        os.makedirs(root, exist_ok=True)
        for i in range(file_count):
            path = os.path.join(root, f"f{i:05d}.bin")
            with open(path, "wb") as f:
                f.write(payload)
        total = 0
        for i in range(file_count):
            path = os.path.join(root, f"f{i:05d}.bin")
            with open(path, "rb") as f:
                total += len(f.read())
    if total != file_count * file_size:
        raise RuntimeError("TempFS small-files benchmark validation failed")


def bench_pyfs2_small_files(file_count: int, file_size: int) -> None:
    MemoryFS = importlib.import_module("fs.memoryfs").MemoryFS
    payload = b"x" * file_size
    with MemoryFS() as memfs:
        memfs.makedirs("bench", recreate=True)
        for i in range(file_count):
            path = f"bench/f{i:05d}.bin"
            with memfs.openbin(path, "w") as f:
                f.write(payload)
        total = 0
        for i in range(file_count):
            path = f"bench/f{i:05d}.bin"
            with memfs.openbin(path, "r") as f:
                total += len(f.read())
    if total != file_count * file_size:
        raise RuntimeError("PyFilesystem2 small-files benchmark validation failed")


def bench_mfs_stream(total_bytes: int, chunk_bytes: int) -> None:
    mfs = MemoryFileSystem(max_quota=1024 * 1024 * 1024)
    chunk = b"y" * chunk_bytes
    loops = total_bytes // chunk_bytes
    with mfs.open("/stream.bin", "wb") as f:
        for _ in range(loops):
            f.write(chunk)
    with mfs.open("/stream.bin", "rb") as f:
        data = f.read()
    if len(data) != loops * chunk_bytes:
        raise RuntimeError("MFS stream benchmark validation failed")


def bench_bytesio_stream(total_bytes: int, chunk_bytes: int) -> None:
    chunk = b"y" * chunk_bytes
    loops = total_bytes // chunk_bytes
    bio = io.BytesIO()
    for _ in range(loops):
        bio.write(chunk)
    data = bio.getvalue()
    if len(data) != loops * chunk_bytes:
        raise RuntimeError("BytesIO stream benchmark validation failed")


def bench_tempfs_stream(total_bytes: int, chunk_bytes: int) -> None:
    chunk = b"y" * chunk_bytes
    loops = total_bytes // chunk_bytes
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "stream.bin")
        with open(path, "wb") as f:
            for _ in range(loops):
                f.write(chunk)
        with open(path, "rb") as f:
            data = f.read()
    if len(data) != loops * chunk_bytes:
        raise RuntimeError("TempFS stream benchmark validation failed")


def bench_pyfs2_stream(total_bytes: int, chunk_bytes: int) -> None:
    MemoryFS = importlib.import_module("fs.memoryfs").MemoryFS
    chunk = b"y" * chunk_bytes
    loops = total_bytes // chunk_bytes
    with MemoryFS() as memfs:
        with memfs.openbin("stream.bin", "w") as f:
            for _ in range(loops):
                f.write(chunk)
        with memfs.openbin("stream.bin", "r") as f:
            data = f.read()
    if len(data) != loops * chunk_bytes:
        raise RuntimeError("PyFilesystem2 stream benchmark validation failed")


def bench_mfs_random_access(total_bytes: int, chunk_bytes: int) -> None:
    mfs = MemoryFileSystem(max_quota=1024 * 1024 * 1024)
    chunk = b"z" * chunk_bytes
    loops = total_bytes // chunk_bytes
    # Sequential write first, then random overwrites to trigger promotion
    with mfs.open("/random.bin", "wb") as f:
        for _ in range(loops):
            f.write(chunk)
    # Random overwrites (seek to various positions and write)
    import random as _rng
    gen = _rng.Random(42)
    with mfs.open("/random.bin", "r+b") as f:
        for _ in range(loops):
            pos = gen.randint(0, total_bytes - chunk_bytes)
            f.seek(pos)
            f.write(chunk)
    with mfs.open("/random.bin", "rb") as f:
        data = f.read()
    if len(data) != total_bytes:
        raise RuntimeError("MFS random-access benchmark validation failed")


def bench_bytesio_random_access(total_bytes: int, chunk_bytes: int) -> None:
    chunk = b"z" * chunk_bytes
    loops = total_bytes // chunk_bytes
    bio = io.BytesIO()
    for _ in range(loops):
        bio.write(chunk)
    import random as _rng
    gen = _rng.Random(42)
    for _ in range(loops):
        pos = gen.randint(0, total_bytes - chunk_bytes)
        bio.seek(pos)
        bio.write(chunk)
    data = bio.getvalue()
    if len(data) != total_bytes:
        raise RuntimeError("BytesIO random-access benchmark validation failed")


def bench_tempfs_random_access(total_bytes: int, chunk_bytes: int) -> None:
    chunk = b"z" * chunk_bytes
    loops = total_bytes // chunk_bytes
    import random as _rng
    gen = _rng.Random(42)
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "random.bin")
        with open(path, "wb") as f:
            for _ in range(loops):
                f.write(chunk)
        with open(path, "r+b") as f:
            for _ in range(loops):
                pos = gen.randint(0, total_bytes - chunk_bytes)
                f.seek(pos)
                f.write(chunk)
        with open(path, "rb") as f:
            data = f.read()
    if len(data) != total_bytes:
        raise RuntimeError("TempFS random-access benchmark validation failed")


def bench_pyfs2_random_access(total_bytes: int, chunk_bytes: int) -> None:
    MemoryFS = importlib.import_module("fs.memoryfs").MemoryFS
    chunk = b"z" * chunk_bytes
    loops = total_bytes // chunk_bytes
    import random as _rng
    gen = _rng.Random(42)
    with MemoryFS() as memfs:
        with memfs.openbin("random.bin", "w") as f:
            for _ in range(loops):
                f.write(chunk)
        with memfs.openbin("random.bin", "r+") as f:
            for _ in range(loops):
                pos = gen.randint(0, total_bytes - chunk_bytes)
                f.seek(pos)
                f.write(chunk)
        with memfs.openbin("random.bin", "r") as f:
            data = f.read()
    if len(data) != total_bytes:
        raise RuntimeError("PyFilesystem2 random-access benchmark validation failed")


# ---------------------------------------------------------------------------
#  Large stream benchmarks (512MB–2GB scale)
# ---------------------------------------------------------------------------


def bench_mfs_large_stream(total_bytes: int, chunk_bytes: int) -> None:
    mfs = MemoryFileSystem(max_quota=total_bytes * 3)
    chunk = b"L" * chunk_bytes
    loops = total_bytes // chunk_bytes
    with mfs.open("/large.bin", "wb") as f:
        for _ in range(loops):
            f.write(chunk)
    with mfs.open("/large.bin", "rb") as f:
        total_read = 0
        while True:
            data = f.read(chunk_bytes)
            if not data:
                break
            total_read += len(data)
    if total_read != total_bytes:
        raise RuntimeError("MFS large-stream benchmark validation failed")


def bench_bytesio_large_stream(total_bytes: int, chunk_bytes: int) -> None:
    chunk = b"L" * chunk_bytes
    loops = total_bytes // chunk_bytes
    bio = io.BytesIO()
    for _ in range(loops):
        bio.write(chunk)
    bio.seek(0)
    total_read = 0
    while True:
        data = bio.read(chunk_bytes)
        if not data:
            break
        total_read += len(data)
    if total_read != total_bytes:
        raise RuntimeError("BytesIO large-stream benchmark validation failed")


def bench_tempfs_large_stream(total_bytes: int, chunk_bytes: int) -> None:
    chunk = b"L" * chunk_bytes
    loops = total_bytes // chunk_bytes
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "large.bin")
        with open(path, "wb") as f:
            for _ in range(loops):
                f.write(chunk)
        with open(path, "rb") as f:
            total_read = 0
            while True:
                data = f.read(chunk_bytes)
                if not data:
                    break
                total_read += len(data)
    if total_read != total_bytes:
        raise RuntimeError("TempFS large-stream benchmark validation failed")


def bench_pyfs2_large_stream(total_bytes: int, chunk_bytes: int) -> None:
    MemoryFS = importlib.import_module("fs.memoryfs").MemoryFS
    chunk = b"L" * chunk_bytes
    loops = total_bytes // chunk_bytes
    with MemoryFS() as memfs:
        with memfs.openbin("large.bin", "w") as f:
            for _ in range(loops):
                f.write(chunk)
        with memfs.openbin("large.bin", "r") as f:
            total_read = 0
            while True:
                data = f.read(chunk_bytes)
                if not data:
                    break
                total_read += len(data)
    if total_read != total_bytes:
        raise RuntimeError("PyFilesystem2 large-stream benchmark validation failed")


# ---------------------------------------------------------------------------
#  Many small files + random read benchmarks
# ---------------------------------------------------------------------------


def bench_mfs_many_files_random(file_count: int, file_size: int) -> None:
    mfs = MemoryFileSystem(max_quota=2 * 1024 * 1024 * 1024)
    payload = b"m" * file_size
    for i in range(file_count):
        with mfs.open(f"/f{i:06d}.bin", "wb") as f:
            f.write(payload)
    import random as _rng
    gen = _rng.Random(42)
    read_count = file_count // 2
    indices = [gen.randint(0, file_count - 1) for _ in range(read_count)]
    total = 0
    for idx in indices:
        with mfs.open(f"/f{idx:06d}.bin", "rb") as f:
            total += len(f.read())
    if total != read_count * file_size:
        raise RuntimeError("MFS many-files-random benchmark validation failed")


def bench_bytesio_many_files_random(file_count: int, file_size: int) -> None:
    payload = b"m" * file_size
    files: dict[str, io.BytesIO] = {}
    for i in range(file_count):
        bio = io.BytesIO()
        bio.write(payload)
        files[f"/f{i:06d}.bin"] = bio
    import random as _rng
    gen = _rng.Random(42)
    read_count = file_count // 2
    indices = [gen.randint(0, file_count - 1) for _ in range(read_count)]
    total = 0
    for idx in indices:
        total += len(files[f"/f{idx:06d}.bin"].getvalue())
    if total != read_count * file_size:
        raise RuntimeError("BytesIO many-files-random benchmark validation failed")


def bench_tempfs_many_files_random(file_count: int, file_size: int) -> None:
    payload = b"m" * file_size
    import random as _rng
    gen = _rng.Random(42)
    read_count = file_count // 2
    indices = [gen.randint(0, file_count - 1) for _ in range(read_count)]
    with tempfile.TemporaryDirectory() as td:
        for i in range(file_count):
            path = os.path.join(td, f"f{i:06d}.bin")
            with open(path, "wb") as f:
                f.write(payload)
        total = 0
        for idx in indices:
            path = os.path.join(td, f"f{idx:06d}.bin")
            with open(path, "rb") as f:
                total += len(f.read())
    if total != read_count * file_size:
        raise RuntimeError("TempFS many-files-random benchmark validation failed")


def bench_pyfs2_many_files_random(file_count: int, file_size: int) -> None:
    MemoryFS = importlib.import_module("fs.memoryfs").MemoryFS
    payload = b"m" * file_size
    import random as _rng
    gen = _rng.Random(42)
    read_count = file_count // 2
    indices = [gen.randint(0, file_count - 1) for _ in range(read_count)]
    with MemoryFS() as memfs:
        for i in range(file_count):
            with memfs.openbin(f"f{i:06d}.bin", "w") as f:
                f.write(payload)
        total = 0
        for idx in indices:
            with memfs.openbin(f"f{idx:06d}.bin", "r") as f:
                total += len(f.read())
    if total != read_count * file_size:
        raise RuntimeError("PyFilesystem2 many-files-random benchmark validation failed")


# ---------------------------------------------------------------------------
#  Deep tree benchmarks (path resolution at depth)
# ---------------------------------------------------------------------------


def bench_mfs_deep_tree(depth: int) -> None:
    mfs = MemoryFileSystem(max_quota=1 * 1024 * 1024 * 1024)
    payload = b"d" * 1024
    parts = [f"d{i}" for i in range(depth)]
    for d in range(1, depth + 1):
        mfs.mkdir("/" + "/".join(parts[:d]), exist_ok=True)
    deep_file = "/" + "/".join(parts) + "/file.bin"
    with mfs.open(deep_file, "wb") as f:
        f.write(payload)
    total = 0
    for _ in range(1000):
        with mfs.open(deep_file, "rb") as f:
            total += len(f.read())
    if total != 1000 * 1024:
        raise RuntimeError("MFS deep-tree benchmark validation failed")


def bench_bytesio_deep_tree(depth: int) -> None:
    payload = b"d" * 1024
    parts = [f"d{i}" for i in range(depth)]
    key = "/" + "/".join(parts) + "/file.bin"
    bio = io.BytesIO()
    bio.write(payload)
    files: dict[str, io.BytesIO] = {key: bio}
    total = 0
    for _ in range(1000):
        total += len(files[key].getvalue())
    if total != 1000 * 1024:
        raise RuntimeError("BytesIO deep-tree benchmark validation failed")


def bench_tempfs_deep_tree(depth: int) -> None:
    payload = b"d" * 1024
    with tempfile.TemporaryDirectory() as td:
        parts = [f"d{i}" for i in range(depth)]
        deep_dir = os.path.join(td, *parts)
        os.makedirs(deep_dir, exist_ok=True)
        deep_file = os.path.join(deep_dir, "file.bin")
        with open(deep_file, "wb") as f:
            f.write(payload)
        total = 0
        for _ in range(1000):
            with open(deep_file, "rb") as f:
                total += len(f.read())
    if total != 1000 * 1024:
        raise RuntimeError("TempFS deep-tree benchmark validation failed")


def bench_pyfs2_deep_tree(depth: int) -> None:
    MemoryFS = importlib.import_module("fs.memoryfs").MemoryFS
    payload = b"d" * 1024
    parts = [f"d{i}" for i in range(depth)]
    deep_dir = "/".join(parts)
    with MemoryFS() as memfs:
        memfs.makedirs(deep_dir, recreate=True)
        deep_file = deep_dir + "/file.bin"
        with memfs.openbin(deep_file, "w") as f:
            f.write(payload)
        total = 0
        for _ in range(1000):
            with memfs.openbin(deep_file, "r") as f:
                total += len(f.read())
    if total != 1000 * 1024:
        raise RuntimeError("PyFilesystem2 deep-tree benchmark validation failed")


def _fmt_ms(seconds: float) -> str:
    return f"{seconds * 1000.0:.2f}"


def _fmt_kib(peak_kib: float) -> str:
    return f"{peak_kib:.1f}"


def run_case(
    backend: str,
    case: str,
    fn: Callable[[], None],
    repeat: int,
    warmup: int,
) -> CaseResult:
    for _ in range(warmup):
        fn()

    elapsed_list: list[float] = []
    peak_list: list[float] = []
    for _ in range(repeat):
        elapsed, peak_kib = _run_with_memory(fn)
        elapsed_list.append(elapsed)
        peak_list.append(peak_kib)

    return CaseResult(
        backend=backend,
        case=case,
        seconds_mean=statistics.mean(elapsed_list),
        seconds_min=min(elapsed_list),
        seconds_max=max(elapsed_list),
        peak_kib_mean=statistics.mean(peak_list),
    )


def print_table(results: list[CaseResult]) -> None:
    print("| Case | Backend | mean(ms) | min(ms) | max(ms) | peak KiB (mean) |")
    print("|---|---:|---:|---:|---:|---:|")
    for r in results:
        print(
            f"| {r.case} | {r.backend} | {_fmt_ms(r.seconds_mean)} |"
            f" {_fmt_ms(r.seconds_min)} | {_fmt_ms(r.seconds_max)} | {_fmt_kib(r.peak_kib_mean)} |"
        )


def _results_to_dict(results: list[CaseResult]) -> list[dict[str, float | str]]:
    return [
        {
            "backend": r.backend,
            "case": r.case,
            "seconds_mean": r.seconds_mean,
            "seconds_min": r.seconds_min,
            "seconds_max": r.seconds_max,
            "peak_kib_mean": r.peak_kib_mean,
        }
        for r in results
    ]


def _results_markdown(results: list[CaseResult], args: argparse.Namespace) -> str:
    lines = [
        "# Benchmark Results",
        "",
        f"- generated_at: `{datetime.now().isoformat(timespec='seconds')}`",
        f"- repeat: `{args.repeat}`",
        f"- warmup: `{args.warmup}`",
        f"- small_files: `{args.small_files}`",
        f"- small_size(bytes): `{args.small_size}`",
        f"- stream_size_mb: `{args.stream_size_mb}`",
        f"- chunk_kb: `{args.chunk_kb}`",
        f"- large_stream_mb: `{args.large_stream_mb}`",
        f"- large_chunk_kb: `{args.large_chunk_kb}`",
        f"- many_files_count: `{args.many_files_count}`",
        f"- deep_levels: `{args.deep_levels}`",
        "",
        "| Case | Backend | mean(ms) | min(ms) | max(ms) | peak KiB (mean) |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for r in results:
        lines.append(
            f"| {r.case} | {r.backend} | {_fmt_ms(r.seconds_mean)} | {_fmt_ms(r.seconds_min)}"
            f" | {_fmt_ms(r.seconds_max)} | {_fmt_kib(r.peak_kib_mean)} |"
        )
    lines.append("")
    return "\n".join(lines)


def _resolve_output_path(raw: str, ext: str) -> Path:
    if raw != "auto":
        return Path(raw)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = Path("benchmarks") / "results"
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir / f"benchmark_{ts}.{ext}"


def _current_result_path(ext: str) -> Path:
    out_dir = Path("benchmarks") / "results"
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir / f"benchmark_current_result.{ext}"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Benchmark MFS vs BytesIO vs tempfile/PyFilesystem2"
    )
    parser.add_argument("--repeat", type=int, default=5)
    parser.add_argument("--warmup", type=int, default=1)
    parser.add_argument("--small-files", type=int, default=300)
    parser.add_argument("--small-size", type=int, default=4096)
    parser.add_argument("--stream-size-mb", type=int, default=16)
    parser.add_argument("--chunk-kb", type=int, default=64)
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--save-md", default="", help="Save markdown report path (or 'auto')"
    )
    parser.add_argument(
        "--save-json", default="", help="Save json report path (or 'auto')"
    )
    parser.add_argument("--large-stream-mb", type=int, default=512)
    parser.add_argument("--large-chunk-kb", type=int, default=1024)
    parser.add_argument("--many-files-count", type=int, default=10000)
    parser.add_argument("--deep-levels", type=int, default=50)
    args = parser.parse_args()

    total_bytes = args.stream_size_mb * 1024 * 1024
    chunk_bytes = args.chunk_kb * 1024
    large_total = args.large_stream_mb * 1024 * 1024
    large_chunk = args.large_chunk_kb * 1024

    results: list[CaseResult] = []

    results.append(
        run_case(
            "MFS",
            "small_files_rw",
            lambda: bench_mfs_small_files(args.small_files, args.small_size),
            args.repeat,
            args.warmup,
        )
    )
    results.append(
        run_case(
            "BytesIO(dict)",
            "small_files_rw",
            lambda: bench_bytesio_small_files(args.small_files, args.small_size),
            args.repeat,
            args.warmup,
        )
    )
    results.append(
        run_case(
            "PyFilesystem2(MemoryFS)",
            "small_files_rw",
            lambda: bench_pyfs2_small_files(args.small_files, args.small_size),
            args.repeat,
            args.warmup,
        )
    )
    results.append(
        run_case(
            "tempfile",
            "small_files_rw",
            lambda: bench_tempfs_small_files(args.small_files, args.small_size),
            args.repeat,
            args.warmup,
        )
    )

    results.append(
        run_case(
            "MFS",
            "stream_write_read",
            lambda: bench_mfs_stream(total_bytes, chunk_bytes),
            args.repeat,
            args.warmup,
        )
    )
    results.append(
        run_case(
            "BytesIO",
            "stream_write_read",
            lambda: bench_bytesio_stream(total_bytes, chunk_bytes),
            args.repeat,
            args.warmup,
        )
    )
    results.append(
        run_case(
            "PyFilesystem2(MemoryFS)",
            "stream_write_read",
            lambda: bench_pyfs2_stream(total_bytes, chunk_bytes),
            args.repeat,
            args.warmup,
        )
    )
    results.append(
        run_case(
            "tempfile",
            "stream_write_read",
            lambda: bench_tempfs_stream(total_bytes, chunk_bytes),
            args.repeat,
            args.warmup,
        )
    )

    results.append(
        run_case(
            "MFS",
            "random_access_rw",
            lambda: bench_mfs_random_access(total_bytes, chunk_bytes),
            args.repeat,
            args.warmup,
        )
    )
    results.append(
        run_case(
            "BytesIO",
            "random_access_rw",
            lambda: bench_bytesio_random_access(total_bytes, chunk_bytes),
            args.repeat,
            args.warmup,
        )
    )
    results.append(
        run_case(
            "PyFilesystem2(MemoryFS)",
            "random_access_rw",
            lambda: bench_pyfs2_random_access(total_bytes, chunk_bytes),
            args.repeat,
            args.warmup,
        )
    )
    results.append(
        run_case(
            "tempfile",
            "random_access_rw",
            lambda: bench_tempfs_random_access(total_bytes, chunk_bytes),
            args.repeat,
            args.warmup,
        )
    )

    # --- Large stream (512MB–2GB) ---
    results.append(
        run_case(
            "MFS",
            "large_stream_write_read",
            lambda: bench_mfs_large_stream(large_total, large_chunk),
            args.repeat,
            args.warmup,
        )
    )
    results.append(
        run_case(
            "BytesIO",
            "large_stream_write_read",
            lambda: bench_bytesio_large_stream(large_total, large_chunk),
            args.repeat,
            args.warmup,
        )
    )
    results.append(
        run_case(
            "PyFilesystem2(MemoryFS)",
            "large_stream_write_read",
            lambda: bench_pyfs2_large_stream(large_total, large_chunk),
            args.repeat,
            args.warmup,
        )
    )
    results.append(
        run_case(
            "tempfile",
            "large_stream_write_read",
            lambda: bench_tempfs_large_stream(large_total, large_chunk),
            args.repeat,
            args.warmup,
        )
    )

    # --- Many files random read ---
    results.append(
        run_case(
            "MFS",
            "many_files_random_read",
            lambda: bench_mfs_many_files_random(args.many_files_count, args.small_size),
            args.repeat,
            args.warmup,
        )
    )
    results.append(
        run_case(
            "BytesIO",
            "many_files_random_read",
            lambda: bench_bytesio_many_files_random(args.many_files_count, args.small_size),
            args.repeat,
            args.warmup,
        )
    )
    results.append(
        run_case(
            "PyFilesystem2(MemoryFS)",
            "many_files_random_read",
            lambda: bench_pyfs2_many_files_random(args.many_files_count, args.small_size),
            args.repeat,
            args.warmup,
        )
    )
    results.append(
        run_case(
            "tempfile",
            "many_files_random_read",
            lambda: bench_tempfs_many_files_random(args.many_files_count, args.small_size),
            args.repeat,
            args.warmup,
        )
    )

    # --- Deep tree read ---
    results.append(
        run_case(
            "MFS",
            "deep_tree_read",
            lambda: bench_mfs_deep_tree(args.deep_levels),
            args.repeat,
            args.warmup,
        )
    )
    results.append(
        run_case(
            "BytesIO",
            "deep_tree_read",
            lambda: bench_bytesio_deep_tree(args.deep_levels),
            args.repeat,
            args.warmup,
        )
    )
    results.append(
        run_case(
            "PyFilesystem2(MemoryFS)",
            "deep_tree_read",
            lambda: bench_pyfs2_deep_tree(args.deep_levels),
            args.repeat,
            args.warmup,
        )
    )
    results.append(
        run_case(
            "tempfile",
            "deep_tree_read",
            lambda: bench_tempfs_deep_tree(args.deep_levels),
            args.repeat,
            args.warmup,
        )
    )

    if args.json:
        print(json.dumps(_results_to_dict(results), indent=2))
        return

    print_table(results)

    if args.save_md:
        md_path = _resolve_output_path(args.save_md, "md")
        md_path.parent.mkdir(parents=True, exist_ok=True)
        md_content = _results_markdown(results, args)
        md_path.write_text(md_content, encoding="utf-8")
        current_md = _current_result_path("md")
        current_md.write_text(md_content, encoding="utf-8")
        print(f"\nSaved markdown report: {md_path}")
        print(f"Updated current markdown report: {current_md}")

    if args.save_json:
        json_path = _resolve_output_path(args.save_json, "json")
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_content = json.dumps(_results_to_dict(results), indent=2)
        json_path.write_text(json_content, encoding="utf-8")
        current_json = _current_result_path("json")
        current_json.write_text(json_content, encoding="utf-8")
        print(f"Saved JSON report: {json_path}")
        print(f"Updated current JSON report: {current_json}")


if __name__ == "__main__":
    main()
