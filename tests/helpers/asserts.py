def assert_stats_consistent(mfs):
    s = mfs.stats()
    assert set(s.keys()) == {
        "used_bytes",
        "quota_bytes",
        "free_bytes",
        "file_count",
        "dir_count",
        "chunk_count",
        "overhead_per_chunk_estimate",
    }
    assert s["used_bytes"] >= 0
    assert s["quota_bytes"] > 0
    assert s["free_bytes"] == s["quota_bytes"] - s["used_bytes"]
    assert s["file_count"] >= 0
    assert s["dir_count"] >= 1
    assert s["overhead_per_chunk_estimate"] > 0
