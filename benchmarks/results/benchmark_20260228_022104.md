# Benchmark Results

- generated_at: `2026-02-28T02:21:04`
- repeat: `1`
- warmup: `0`
- small_files: `300`
- small_size(bytes): `4096`
- stream_size_mb: `16`
- chunk_kb: `64`
- large_stream_mb: `2048`
- large_chunk_kb: `1024`
- many_files_count: `10000`
- deep_levels: `50`

| Case | Backend | mean(ms) | min(ms) | max(ms) | peak KiB (mean) |
|---|---:|---:|---:|---:|---:|
| small_files_rw | MFS | 34.44 | 34.44 | 34.44 | 519.9 |
| small_files_rw | BytesIO(dict) | 4.51 | 4.51 | 4.51 | 1261.1 |
| small_files_rw | PyFilesystem2(MemoryFS) | 792.61 | 792.61 | 792.61 | 8640.8 |
| small_files_rw | tempfile | 164.40 | 164.40 | 164.40 | 29.2 |
| stream_write_read | MFS | 63.72 | 63.72 | 63.72 | 34463.0 |
| stream_write_read | BytesIO | 51.00 | 51.00 | 51.00 | 18064.2 |
| stream_write_read | PyFilesystem2(MemoryFS) | 60.42 | 60.42 | 60.42 | 34451.0 |
| stream_write_read | tempfile | 16.77 | 16.77 | 16.77 | 16457.3 |
| random_access_rw | MFS | 24.12 | 24.12 | 24.12 | 49221.9 |
| random_access_rw | BytesIO | 52.52 | 52.52 | 52.52 | 18067.2 |
| random_access_rw | PyFilesystem2(MemoryFS) | 65.27 | 65.27 | 65.27 | 34453.8 |
| random_access_rw | tempfile | 27.00 | 27.00 | 27.00 | 16460.1 |
| large_stream_write_read | MFS | 1438.38 | 1438.38 | 1438.38 | 4202.5 |
| large_stream_write_read | BytesIO | 7593.84 | 7593.84 | 7593.84 | 2164224.3 |
| large_stream_write_read | PyFilesystem2(MemoryFS) | 7659.31 | 7659.31 | 7659.31 | 2164227.1 |
| large_stream_write_read | tempfile | 1930.87 | 1930.87 | 1930.87 | 3081.7 |
| many_files_random_read | MFS | 776.70 | 776.70 | 776.70 | 17132.3 |
| many_files_random_read | BytesIO | 163.02 | 163.02 | 163.02 | 42034.1 |
| many_files_random_read | PyFilesystem2(MemoryFS) | 834.54 | 834.54 | 834.54 | 47166.2 |
| many_files_random_read | tempfile | 4745.31 | 4745.31 | 4745.31 | 795.4 |
| deep_tree_read | MFS | 148.29 | 148.29 | 148.29 | 26.9 |
| deep_tree_read | BytesIO | 2.15 | 2.15 | 2.15 | 4.0 |
| deep_tree_read | PyFilesystem2(MemoryFS) | 111.14 | 111.14 | 111.14 | 38.9 |
| deep_tree_read | tempfile | 284.73 | 284.73 | 284.73 | 24.7 |
