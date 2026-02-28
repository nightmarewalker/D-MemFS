# Benchmark Guide

This repository includes a minimal benchmark script to compare:

- `MemoryFileSystem` (MFS)
- `io.BytesIO` (single stream or dict of streams)
- `PyFilesystem2` (`fs.memoryfs.MemoryFS`)
- `tempfile`-backed real filesystem I/O

> **Note on PyFilesystem2:** As of setuptools 82 (February 2026), `pyfilesystem2` fails to import due to its use of the deprecated `pkg_resources.declare_namespace()` API ([issue #597](https://github.com/PyFilesystem/pyfilesystem2/issues/597)). The project appears unmaintained and the fix has not been released. Benchmark results that include `PyFilesystem2` were measured in an environment with setuptools ≤ 81 and remain valid as historical comparison data, but the benchmark script will skip or error on PyFilesystem2 cases in current environments.

## Run

```bash
uvx --with-requirements requirements.txt --with-editable . python benchmarks/compare_backends.py
```

## Common options

```bash
# More stable numbers
uvx --with-requirements requirements.txt --with-editable . python benchmarks/compare_backends.py --repeat 10 --warmup 2

# Heavier workload
uvx --with-requirements requirements.txt --with-editable . python benchmarks/compare_backends.py --small-files 1000 --stream-size-mb 64

# JSON output
uvx --with-requirements requirements.txt --with-editable . python benchmarks/compare_backends.py --json

# Save reports into benchmarks/results/
uvx --with-requirements requirements.txt --with-editable . python benchmarks/compare_backends.py --save-md auto --save-json auto
```

When markdown/json reports are generated, the script also updates:

- `benchmarks/results/benchmark_current_result.md`
- `benchmarks/results/benchmark_current_result.json`

You can link `benchmark_current_result.md` from README as the latest snapshot.

## Cases

- `small_files_rw`: write/read many small files
- `stream_write_read`: write/read one larger stream in chunks

Saved reports are written under `benchmarks/results/` when `--save-md auto` or `--save-json auto` is used.

## Notes

- `tracemalloc` reports Python-heap allocations; OS page cache and kernel-level effects are not fully represented.
- `tempfile` results vary by OS, filesystem, and disk state. The included benchmark results were measured with the system `%TEMP%` directory located on a RAM disk. On a physical (SSD/HDD) disk, `tempfile` numbers will be significantly slower.
- For fair comparisons, run on an idle machine and repeat multiple times.
