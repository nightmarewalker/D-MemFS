"""ETL staging use case: process data through stages."""
import pytest
from dmemfs import MemoryFileSystem


@pytest.fixture
def mfs():
    return MemoryFileSystem(max_quota=16 * 1024 * 1024)


def test_stage_data_processing(mfs):
    """Simulate ETL: raw → processed → output."""
    mfs.mkdir("/raw")
    mfs.mkdir("/processed")
    mfs.mkdir("/output")
    
    # Write raw data
    raw_data = b"id,name,value\n1,foo,100\n2,bar,200\n"
    with mfs.open("/raw/data.csv", "wb") as f:
        f.write(raw_data)
    
    # Process: read raw, transform
    with mfs.open("/raw/data.csv", "rb") as f:
        data = f.read()
    processed = data.upper()
    
    with mfs.open("/processed/data.csv", "wb") as f:
        f.write(processed)
    
    # Output: read processed
    with mfs.open("/processed/data.csv", "rb") as f:
        result = f.read()
    
    assert result == raw_data.upper()


def test_staging_cleanup(mfs):
    """After ETL, staging area can be cleaned."""
    mfs.mkdir("/staging")
    with mfs.open("/staging/temp.bin", "wb") as f:
        f.write(b"x" * 10000)
    
    used_before = mfs.stats()["used_bytes"]
    mfs.rmtree("/staging")
    used_after = mfs.stats()["used_bytes"]
    
    assert used_after < used_before
    assert not mfs.exists("/staging")


def test_incremental_update(mfs):
    """Simulate incremental data update."""
    with mfs.open("/data.bin", "wb") as f:
        f.write(b"initial data\n")
    
    for i in range(5):
        with mfs.open("/data.bin", "ab") as f:
            f.write(f"update {i}\n".encode())
    
    with mfs.open("/data.bin", "rb") as f:
        content = f.read()
    
    assert b"initial data" in content
    assert b"update 4" in content


def test_parallel_stage_writes(mfs):
    """Multiple files can be written to staging in parallel."""
    import threading
    
    mfs.mkdir("/staging")
    errors = []
    
    def write_file(i):
        try:
            with mfs.open(f"/staging/file_{i}.bin", "wb") as f:
                f.write(f"data {i}".encode() * 100)
        except Exception as e:
            errors.append(e)
    
    threads = [threading.Thread(target=write_file, args=(i,)) for i in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    
    assert not errors
    assert len(mfs.listdir("/staging")) == 10
