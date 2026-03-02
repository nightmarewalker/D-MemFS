# Benchmark Results

- generated_at: `2026-03-03T03:50:21`
- repeat: `5`
- warmup: `1`
- small_files: `300`
- small_size(bytes): `4096`
- stream_size_mb: `16`
- chunk_kb: `64`
- large_stream_mb: `512`
- large_chunk_kb: `1024`
- many_files_count: `10000`
- deep_levels: `50`

| Case | Backend | mean(ms) | min(ms) | max(ms) | peak KiB (mean) |
|---|---:|---:|---:|---:|---:|
| small_files_rw | MFS | 31.08 | 30.51 | 32.20 | 512.2 |
| small_files_rw | BytesIO(dict) | 5.98 | 4.04 | 10.35 | 1261.1 |
| small_files_rw | PyFilesystem2(MemoryFS) | 32.24 | 31.51 | 33.86 | 1418.0 |
| small_files_rw | tempfile | 159.38 | 157.03 | 161.91 | 25.8 |
| stream_write_read | MFS | 66.42 | 65.14 | 68.45 | 34462.9 |
| stream_write_read | BytesIO | 55.67 | 52.94 | 58.38 | 18064.2 |
| stream_write_read | PyFilesystem2(MemoryFS) | 64.28 | 63.54 | 65.77 | 34450.9 |
| stream_write_read | tempfile | 17.20 | 16.70 | 18.18 | 16457.3 |
| random_access_rw | MFS | 25.17 | 25.00 | 25.64 | 49221.6 |
| random_access_rw | BytesIO | 58.80 | 54.67 | 63.08 | 18067.2 |
| random_access_rw | PyFilesystem2(MemoryFS) | 70.53 | 69.44 | 71.70 | 34453.6 |
| random_access_rw | tempfile | 26.01 | 25.44 | 26.78 | 16460.0 |
| large_stream_write_read | MFS | 345.40 | 335.83 | 349.35 | 4122.9 |
| large_stream_write_read | BytesIO | 2056.21 | 2032.51 | 2077.02 | 591744.3 |
| large_stream_write_read | PyFilesystem2(MemoryFS) | 2085.91 | 2071.88 | 2120.82 | 591746.9 |
| large_stream_write_read | tempfile | 486.85 | 474.48 | 497.89 | 3081.6 |
| many_files_random_read | MFS | 819.95 | 792.43 | 860.53 | 17287.5 |
| many_files_random_read | BytesIO | 171.19 | 166.09 | 176.35 | 42034.1 |
| many_files_random_read | PyFilesystem2(MemoryFS) | 849.92 | 830.76 | 893.80 | 47165.9 |
| many_files_random_read | tempfile | 4686.52 | 4668.54 | 4708.87 | 795.2 |
| deep_tree_read | MFS | 144.62 | 141.14 | 151.50 | 19.0 |
| deep_tree_read | BytesIO | 2.13 | 2.09 | 2.19 | 4.0 |
| deep_tree_read | PyFilesystem2(MemoryFS) | 113.17 | 112.19 | 114.28 | 38.8 |
| deep_tree_read | tempfile | 269.62 | 266.24 | 273.33 | 21.4 |
