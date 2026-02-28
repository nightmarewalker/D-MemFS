"""v11: async/await ラッパーのテスト."""

import asyncio
import pytest
from dmemfs._async import AsyncMemoryFileSystem
from dmemfs import MFSQuotaExceededError


@pytest.fixture
def async_mfs():
    return AsyncMemoryFileSystem(max_quota=1 * 1024 * 1024)


@pytest.mark.asyncio
async def test_async_write_read_roundtrip(async_mfs):
    await async_mfs.mkdir("/data")

    async with await async_mfs.open("/data/test.bin", "wb") as f:
        written = await f.write(b"hello async world")
        assert written == 17

    async with await async_mfs.open("/data/test.bin", "rb") as f:
        data = await f.read()
        assert data == b"hello async world"


@pytest.mark.asyncio
async def test_async_mkdir_listdir(async_mfs):
    await async_mfs.mkdir("/dir1/sub1")
    await async_mfs.mkdir("/dir1/sub2")

    entries = await async_mfs.listdir("/dir1")
    assert sorted(entries) == ["sub1", "sub2"]


@pytest.mark.asyncio
async def test_async_context_manager(async_mfs):
    async with await async_mfs.open("/test.bin", "wb") as f:
        await f.write(b"data")

    async with await async_mfs.open("/test.bin", "rb") as f:
        assert await f.read() == b"data"


@pytest.mark.asyncio
async def test_async_file_not_found(async_mfs):
    with pytest.raises(FileNotFoundError):
        await async_mfs.open("/nonexistent", "rb")


@pytest.mark.asyncio
async def test_async_quota_exceeded(async_mfs):
    with pytest.raises(MFSQuotaExceededError):
        async with await async_mfs.open("/huge.bin", "wb") as f:
            await f.write(b"\x00" * (2 * 1024 * 1024))


@pytest.mark.asyncio
async def test_async_stat(async_mfs):
    async with await async_mfs.open("/test.bin", "wb") as f:
        await f.write(b"data")

    info = await async_mfs.stat("/test.bin")
    assert info["size"] == 4
    assert "created_at" in info
    assert "modified_at" in info


@pytest.mark.asyncio
async def test_async_copy_and_remove(async_mfs):
    async with await async_mfs.open("/src.bin", "wb") as f:
        await f.write(b"copy me")

    await async_mfs.copy("/src.bin", "/dst.bin")
    async with await async_mfs.open("/dst.bin", "rb") as f:
        assert await f.read() == b"copy me"

    await async_mfs.remove("/src.bin")
    assert not await async_mfs.exists("/src.bin")


@pytest.mark.asyncio
async def test_async_export_import_tree(async_mfs):
    await async_mfs.import_tree({"/a.bin": b"aaa", "/b.bin": b"bbb"})
    tree = await async_mfs.export_tree()
    assert tree["/a.bin"] == b"aaa"
    assert tree["/b.bin"] == b"bbb"


@pytest.mark.asyncio
async def test_async_walk(async_mfs):
    await async_mfs.mkdir("/dir/sub")
    async with await async_mfs.open("/dir/f.bin", "wb") as f:
        await f.write(b"data")

    result = await async_mfs.walk("/dir")
    assert len(result) >= 1
    dirpath, dirnames, filenames = result[0]
    assert dirpath == "/dir"
    assert "sub" in dirnames
    assert "f.bin" in filenames


@pytest.mark.asyncio
async def test_async_concurrent_operations(async_mfs):
    """複数の非同期タスクが同時にMFSを操作してもクラッシュしない。"""
    await async_mfs.mkdir("/concurrent")

    async def write_task(i):
        path = f"/concurrent/file_{i}.bin"
        async with await async_mfs.open(path, "wb") as f:
            await f.write(f"data_{i}".encode())

    await asyncio.gather(*(write_task(i) for i in range(10)))

    entries = await async_mfs.listdir("/concurrent")
    assert len(entries) == 10


@pytest.mark.asyncio
async def test_async_glob(async_mfs):
    """非同期 glob が正しくマッチする。"""
    await async_mfs.mkdir("/dir/sub")
    async with await async_mfs.open("/dir/a.txt", "wb") as f:
        await f.write(b"a")
    async with await async_mfs.open("/dir/sub/b.txt", "wb") as f:
        await f.write(b"b")

    result = await async_mfs.glob("/dir/**/*.txt")
    assert "/dir/a.txt" in result
    assert "/dir/sub/b.txt" in result


@pytest.mark.asyncio
async def test_async_rename(async_mfs):
    """非同期 rename がファイルをリネームする。"""
    async with await async_mfs.open("/old.bin", "wb") as f:
        await f.write(b"data")

    await async_mfs.rename("/old.bin", "/new.bin")
    assert not await async_mfs.exists("/old.bin")
    assert await async_mfs.exists("/new.bin")
    async with await async_mfs.open("/new.bin", "rb") as f:
        assert await f.read() == b"data"


@pytest.mark.asyncio
async def test_async_move(async_mfs):
    """非同期 move がファイルを移動する。"""
    await async_mfs.mkdir("/src")
    async with await async_mfs.open("/src/f.bin", "wb") as f:
        await f.write(b"moved")

    await async_mfs.move("/src/f.bin", "/dst.bin")
    assert not await async_mfs.exists("/src/f.bin")
    async with await async_mfs.open("/dst.bin", "rb") as f:
        assert await f.read() == b"moved"


@pytest.mark.asyncio
async def test_async_rmtree(async_mfs):
    """非同期 rmtree がディレクトリツリーを削除する。"""
    await async_mfs.mkdir("/dir/sub")
    async with await async_mfs.open("/dir/sub/f.bin", "wb") as f:
        await f.write(b"data")

    await async_mfs.rmtree("/dir")
    assert not await async_mfs.exists("/dir")
    assert not await async_mfs.exists("/dir/sub/f.bin")


@pytest.mark.asyncio
async def test_async_copy_tree(async_mfs):
    """非同期 copy_tree がディレクトリツリーをコピーする。"""
    await async_mfs.mkdir("/src")
    async with await async_mfs.open("/src/a.bin", "wb") as f:
        await f.write(b"aaa")
    async with await async_mfs.open("/src/b.bin", "wb") as f:
        await f.write(b"bbb")

    await async_mfs.copy_tree("/src", "/dst")
    assert await async_mfs.exists("/dst")
    async with await async_mfs.open("/dst/a.bin", "rb") as f:
        assert await f.read() == b"aaa"
    async with await async_mfs.open("/dst/b.bin", "rb") as f:
        assert await f.read() == b"bbb"


@pytest.mark.asyncio
async def test_async_handle_seek_and_tell(async_mfs):
    """AsyncMemoryFileHandle の seek / tell が正しく動作する。"""
    async with await async_mfs.open("/f.bin", "wb") as f:
        await f.write(b"hello world")

    async with await async_mfs.open("/f.bin", "rb") as f:
        pos = await f.seek(6)
        assert pos == 6
        assert await f.tell() == 6
        assert await f.read() == b"world"


@pytest.mark.asyncio
async def test_async_is_dir(async_mfs):
    """非同期 is_dir がディレクトリとファイルを正しく判別する。"""
    await async_mfs.mkdir("/mydir")
    async with await async_mfs.open("/myfile.bin", "wb") as f:
        await f.write(b"x")

    assert await async_mfs.is_dir("/mydir") is True
    assert await async_mfs.is_dir("/myfile.bin") is False
    assert await async_mfs.is_dir("/nonexistent") is False


@pytest.mark.asyncio
async def test_async_stats(async_mfs):
    """非同期 stats がファイルシステムの使用状況を返す。"""
    async with await async_mfs.open("/f.bin", "wb") as f:
        await f.write(b"data")

    s = await async_mfs.stats()
    assert s["used_bytes"] > 0
    assert s["quota_bytes"] == 1 * 1024 * 1024
    assert s["file_count"] == 1


@pytest.mark.asyncio
async def test_async_get_size(async_mfs):
    """非同期 get_size がファイルサイズを正しく返す。"""
    async with await async_mfs.open("/f.bin", "wb") as f:
        await f.write(b"hello")

    assert await async_mfs.get_size("/f.bin") == 5


@pytest.mark.asyncio
async def test_async_is_file(async_mfs):
    await async_mfs.mkdir("/d")
    async with await async_mfs.open("/d/f.bin", "wb") as f:
        await f.write(b"x")

    assert await async_mfs.is_file("/d/f.bin") is True
    assert await async_mfs.is_file("/d") is False
    assert await async_mfs.is_file("/missing.bin") is False


@pytest.mark.asyncio
async def test_async_handle_file_like_methods(async_mfs):
    async with await async_mfs.open("/f.bin", "wb") as f:
        assert await f.writable() is True
        assert await f.readable() is False
        assert await f.seekable() is True
        await f.flush()
        await f.write(b"abcdef")
        assert await f.truncate(3) == 3

    async with await async_mfs.open("/f.bin", "rb") as f:
        assert await f.read() == b"abc"


@pytest.mark.asyncio
async def test_async_export_as_bytesio(async_mfs):
    """非同期 export_as_bytesio がファイル内容を BytesIO で返す。"""
    async with await async_mfs.open("/f.bin", "wb") as f:
        await f.write(b"export me")

    bio = await async_mfs.export_as_bytesio("/f.bin")
    assert bio.read() == b"export me"
