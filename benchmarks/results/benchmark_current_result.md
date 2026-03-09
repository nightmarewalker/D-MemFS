# Benchmark Results

- generated_at: `2026-03-10T00:58:39`
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
- ramdisk_dir: `X:\TEMP`
- ssd_dir: `C:\TempX`

| Case | Backend | mean(ms) | min(ms) | max(ms) | peak KiB (mean) |
|---|---:|---:|---:|---:|---:|
| small_files_rw | D-MemFS | 51.18 | 45.92 | 54.63 | 512.7 |
| small_files_rw | BytesIO(dict) | 6.09 | 5.56 | 7.51 | 1261.1 |
| small_files_rw | PyFilesystem2(MemoryFS) | 44.37 | 41.61 | 47.43 | 1418.0 |
| small_files_rw | tempfile(RAMDisk) | 206.99 | 200.11 | 219.40 | 25.8 |
| small_files_rw | tempfile(SSD) | 267.18 | 262.22 | 276.64 | 25.7 |
| stream_write_read | D-MemFS | 80.74 | 76.62 | 85.33 | 34463.3 |
| stream_write_read | BytesIO | 61.92 | 60.52 | 63.36 | 18064.2 |
| stream_write_read | PyFilesystem2(MemoryFS) | 71.45 | 70.11 | 72.91 | 34450.9 |
| stream_write_read | tempfile(RAMDisk) | 19.73 | 18.44 | 22.80 | 16457.2 |
| stream_write_read | tempfile(SSD) | 20.80 | 20.00 | 21.71 | 16457.2 |
| random_access_rw | D-MemFS | 33.82 | 31.55 | 38.91 | 49221.9 |
| random_access_rw | BytesIO | 81.70 | 65.46 | 117.53 | 18067.2 |
| random_access_rw | PyFilesystem2(MemoryFS) | 114.54 | 94.33 | 143.41 | 34453.6 |
| random_access_rw | tempfile(RAMDisk) | 36.60 | 33.02 | 40.42 | 16459.9 |
| random_access_rw | tempfile(SSD) | 35.46 | 34.73 | 36.73 | 16459.9 |
| large_stream_write_read | D-MemFS | 528.67 | 471.03 | 607.51 | 4123.2 |
| large_stream_write_read | BytesIO | 2257.73 | 2210.31 | 2378.42 | 591744.3 |
| large_stream_write_read | PyFilesystem2(MemoryFS) | 2300.66 | 2223.49 | 2340.54 | 591746.9 |
| large_stream_write_read | tempfile(RAMDisk) | 513.98 | 492.92 | 542.87 | 3081.5 |
| large_stream_write_read | tempfile(SSD) | 540.97 | 522.94 | 576.43 | 3081.5 |
| many_files_random_read | D-MemFS | 1279.69 | 1257.19 | 1312.02 | 17287.8 |
| many_files_random_read | BytesIO | 211.86 | 206.50 | 221.20 | 42034.1 |
| many_files_random_read | PyFilesystem2(MemoryFS) | 1197.67 | 1157.38 | 1326.85 | 47165.9 |
| many_files_random_read | tempfile(RAMDisk) | 6309.71 | 6170.18 | 6439.89 | 795.2 |
| many_files_random_read | tempfile(SSD) | 8601.16 | 8466.59 | 8734.31 | 795.2 |
| deep_tree_read | D-MemFS | 224.48 | 220.88 | 230.73 | 19.2 |
| deep_tree_read | BytesIO | 3.33 | 3.17 | 3.49 | 4.0 |
| deep_tree_read | PyFilesystem2(MemoryFS) | 188.10 | 180.32 | 198.27 | 38.8 |
| deep_tree_read | tempfile(RAMDisk) | 345.82 | 320.49 | 370.56 | 21.4 |
| deep_tree_read | tempfile(SSD) | 360.51 | 349.80 | 380.94 | 21.4 |
