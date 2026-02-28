from typing import TypedDict


class MFSStats(TypedDict):
    used_bytes: int
    quota_bytes: int
    free_bytes: int
    file_count: int
    dir_count: int
    chunk_count: int
    overhead_per_chunk_estimate: int


class MFSStatResult(TypedDict):
    size: int
    created_at: float
    modified_at: float
    generation: int
    is_dir: bool
