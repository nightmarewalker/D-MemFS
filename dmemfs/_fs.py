from __future__ import annotations

import fnmatch
import io
import posixpath
import threading
import time
from collections.abc import Iterator

from ._exceptions import MFSNodeLimitExceededError, MFSQuotaExceededError
from ._file import (
    CHUNK_OVERHEAD_ESTIMATE,
    IMemoryFile,
    RandomAccessMemoryFile,
    SequentialMemoryFile,
)
from ._handle import MemoryFileHandle
from ._lock import ReadWriteLock
from ._path import normalize_path
from ._quota import QuotaManager
from ._typing import MFSStatResult, MFSStats

# ---------------------------------------------------------------------------
#  Directory Index Layer
# ---------------------------------------------------------------------------


class DirNode:
    __slots__ = ("node_id", "children", "created_at", "modified_at")

    def __init__(self, node_id: int) -> None:
        self.node_id: int = node_id
        self.children: dict[str, int] = {}
        now = time.time()
        self.created_at: float = now
        self.modified_at: float = now


class FileNode:
    __slots__ = (
        "node_id",
        "storage",
        "_rw_lock",
        "generation",
        "created_at",
        "modified_at",
    )

    def __init__(self, node_id: int, storage: IMemoryFile) -> None:
        self.node_id: int = node_id
        self.storage: IMemoryFile = storage
        self._rw_lock: ReadWriteLock = ReadWriteLock()
        self.generation: int = 0
        now = time.time()
        self.created_at: float = now
        self.modified_at: float = now


Node = DirNode | FileNode


# ---------------------------------------------------------------------------
#  MemoryFileSystem
# ---------------------------------------------------------------------------


class MemoryFileSystem:
    def __init__(
        self,
        max_quota: int = 256 * 1024 * 1024,
        chunk_overhead_override: int | None = None,
        promotion_hard_limit: int | None = None,
        max_nodes: int | None = None,
        default_storage: str = "auto",
    ) -> None:
        if default_storage not in ("auto", "sequential", "random_access"):
            raise ValueError(
                f"Invalid default_storage value: {default_storage!r}. "
                "Expected 'auto', 'sequential', or 'random_access'."
            )
        self._quota = QuotaManager(max_quota)
        self._global_lock = threading.RLock()
        self._chunk_overhead: int = (
            chunk_overhead_override
            if chunk_overhead_override is not None
            else CHUNK_OVERHEAD_ESTIMATE
        )
        self._promotion_hard_limit: int | None = promotion_hard_limit
        self._max_nodes: int | None = max_nodes
        self._default_storage: str = default_storage
        self._nodes: dict[int, Node] = {}
        self._next_node_id: int = 0
        # Root directory
        self._root = self._alloc_dir()

    # -- node allocation helpers --

    def _create_storage(self) -> IMemoryFile:
        """Create a new file storage object according to default_storage setting."""
        if self._default_storage == "random_access":
            return RandomAccessMemoryFile()
        allow_promotion = (self._default_storage != "sequential")
        return SequentialMemoryFile(self._chunk_overhead, self._promotion_hard_limit, allow_promotion)

    def _alloc_dir(self) -> DirNode:
        if self._max_nodes is not None and len(self._nodes) >= self._max_nodes:
            raise MFSNodeLimitExceededError(len(self._nodes), self._max_nodes)
        nid = self._next_node_id
        self._next_node_id += 1
        node = DirNode(nid)
        self._nodes[nid] = node
        return node

    def _alloc_file(self, storage: IMemoryFile) -> FileNode:
        if self._max_nodes is not None and len(self._nodes) >= self._max_nodes:
            raise MFSNodeLimitExceededError(len(self._nodes), self._max_nodes)
        nid = self._next_node_id
        self._next_node_id += 1
        node = FileNode(nid, storage)
        self._nodes[nid] = node
        return node

    # -- path helpers --

    def _np(self, path: str) -> str:
        return normalize_path(path)

    def _resolve_path(self, npath: str) -> Node | None:
        if npath == "/":
            return self._root
        parts = [p for p in npath.split("/") if p]
        current: Node = self._root
        for part in parts:
            if not isinstance(current, DirNode):
                return None
            child_id = current.children.get(part)
            if child_id is None:
                return None
            current = self._nodes[child_id]
        return current

    def _resolve_parent_and_name(self, npath: str) -> tuple[DirNode, str] | None:
        parent_path = posixpath.dirname(npath) or "/"
        name = posixpath.basename(npath)
        parent_node = self._resolve_path(parent_path)
        if parent_node is None or not isinstance(parent_node, DirNode):
            return None
        return parent_node, name

    # -- public API --

    def open(
        self,
        path: str,
        mode: str = "rb",
        preallocate: int = 0,
        lock_timeout: float | None = None,
    ) -> MemoryFileHandle:
        valid_modes = {"rb", "wb", "ab", "r+b", "xb"}
        if mode not in valid_modes:
            raise ValueError(
                f"Invalid mode '{mode}'. MFS supports binary modes only: {valid_modes}"
            )
        npath = self._np(path)
        handle = None
        fnode: FileNode | None = None
        with self._global_lock:
            node = self._resolve_path(npath)
            if node is not None and isinstance(node, DirNode):
                raise IsADirectoryError(f"Is a directory: '{path}'")
            fnode = node if isinstance(node, FileNode) else None

            if mode == "rb":
                if fnode is None:
                    raise FileNotFoundError(f"No such file: '{path}'")
                fnode._rw_lock.acquire_read(timeout=lock_timeout)
                handle = MemoryFileHandle(self, fnode, npath, mode)

            elif mode == "wb":
                if fnode is None:
                    # New file: _create_file already sets timestamps
                    fnode = self._create_file(npath)
                    fnode._rw_lock.acquire_write(timeout=lock_timeout)
                    handle = MemoryFileHandle(self, fnode, npath, mode)
                else:
                    # Existing file: truncate and update metadata
                    fnode._rw_lock.acquire_write(timeout=lock_timeout)
                    fnode.storage.truncate(0, self._quota)
                    fnode.generation += 1
                    fnode.modified_at = time.time()
                    handle = MemoryFileHandle(self, fnode, npath, mode)

            elif mode == "ab":
                if fnode is None:
                    fnode = self._create_file(npath)
                fnode._rw_lock.acquire_write(timeout=lock_timeout)
                handle = MemoryFileHandle(self, fnode, npath, mode, is_append=True)

            elif mode == "r+b":
                if fnode is None:
                    raise FileNotFoundError(f"No such file: '{path}'")
                fnode._rw_lock.acquire_write(timeout=lock_timeout)
                handle = MemoryFileHandle(self, fnode, npath, mode)

            elif mode == "xb":
                if fnode is not None:
                    raise FileExistsError(f"File exists: '{path}'")
                fnode = self._create_file(npath)
                fnode._rw_lock.acquire_write(timeout=lock_timeout)
                handle = MemoryFileHandle(self, fnode, npath, mode)

            if preallocate > 0 and handle is not None and fnode is not None:
                current = fnode.storage.get_size()
                if preallocate > current:
                    try:
                        n, promoted, old_quota = fnode.storage.write_at(
                            current, bytes(preallocate - current), self._quota
                        )
                        if promoted is not None:
                            fnode.storage = promoted
                            self._quota.release(old_quota)
                        fnode.generation += 1
                    except Exception:
                        handle.close()
                        raise

        return handle  # type: ignore[return-value]

    def _create_file(self, npath: str) -> FileNode:
        pinfo = self._resolve_parent_and_name(npath)
        if pinfo is None:
            parent_path = posixpath.dirname(npath) or "/"
            raise FileNotFoundError(f"Parent directory does not exist: '{parent_path}'")
        parent, name = pinfo
        storage = self._create_storage()
        fnode = self._alloc_file(storage)
        parent.children[name] = fnode.node_id
        return fnode

    def mkdir(self, path: str, exist_ok: bool = False) -> None:
        npath = self._np(path)
        with self._global_lock:
            node = self._resolve_path(npath)
            if node is not None:
                if isinstance(node, DirNode):
                    if not exist_ok:
                        raise FileExistsError(f"Directory exists: '{path}'")
                    return
                else:
                    raise FileExistsError(f"File exists at path: '{path}'")
            self._makedirs(npath)

    def _makedirs(self, npath: str, created_dirs: list[str] | None = None) -> None:
        parts = [p for p in npath.split("/") if p]
        current = self._root
        current_path = ""
        for part in parts:
            next_path = current_path + "/" + part
            child_id = current.children.get(part)
            if child_id is not None:
                child = self._nodes[child_id]
                if isinstance(child, DirNode):
                    current = child
                else:
                    raise FileExistsError(f"A file exists at path component: '{part}'")
            else:
                new_dir = self._alloc_dir()
                current.children[part] = new_dir.node_id
                current = new_dir
                if created_dirs is not None:
                    created_dirs.append(next_path)
            current_path = next_path

    def rename(self, src: str, dst: str) -> None:
        nsrc = self._np(src)
        ndst = self._np(dst)
        if nsrc == "/":
            raise ValueError("Cannot rename the root directory.")
        with self._global_lock:
            src_node = self._resolve_path(nsrc)
            if src_node is None:
                raise FileNotFoundError(f"No such file or directory: '{src}'")
            dst_node = self._resolve_path(ndst)
            if dst_node is not None:
                raise FileExistsError(f"Destination already exists: '{dst}'")
            dst_pinfo = self._resolve_parent_and_name(ndst)
            if dst_pinfo is None:
                raise FileNotFoundError(f"Destination parent does not exist: '{dst}'")
            # Check open handles
            self._assert_no_open_handles(src_node, nsrc)
            # Detach from old parent
            src_pinfo = self._resolve_parent_and_name(nsrc)
            assert src_pinfo is not None
            src_parent, src_name = src_pinfo
            dst_parent, dst_name = dst_pinfo
            del src_parent.children[src_name]
            dst_parent.children[dst_name] = src_node.node_id

    def move(self, src: str, dst: str) -> None:
        nsrc = self._np(src)
        ndst = self._np(dst)
        if nsrc == "/":
            raise ValueError("Cannot move the root directory.")
        with self._global_lock:
            src_node = self._resolve_path(nsrc)
            if src_node is None:
                raise FileNotFoundError(f"No such file or directory: '{src}'")
            dst_node = self._resolve_path(ndst)
            if dst_node is not None:
                raise FileExistsError(f"Destination already exists: '{dst}'")
            self._assert_no_open_handles(src_node, nsrc)
            # Auto-create parent directories for dst
            dst_parent_path = posixpath.dirname(ndst) or "/"
            if self._resolve_path(dst_parent_path) is None:
                self._makedirs(dst_parent_path)
            dst_pinfo = self._resolve_parent_and_name(ndst)
            assert dst_pinfo is not None
            src_pinfo = self._resolve_parent_and_name(nsrc)
            assert src_pinfo is not None
            src_parent, src_name = src_pinfo
            dst_parent, dst_name = dst_pinfo
            del src_parent.children[src_name]
            dst_parent.children[dst_name] = src_node.node_id

    def _assert_no_open_handles(self, node: Node, path_for_error: str) -> None:
        if isinstance(node, FileNode):
            if node._rw_lock.is_locked:
                raise BlockingIOError(f"File is open: '{path_for_error}'")
        elif isinstance(node, DirNode):
            for name, child_id in node.children.items():
                child = self._nodes[child_id]
                child_path = path_for_error.rstrip("/") + "/" + name
                self._assert_no_open_handles(child, child_path)

    def remove(self, path: str) -> None:
        npath = self._np(path)
        with self._global_lock:
            node = self._resolve_path(npath)
            if node is None:
                raise FileNotFoundError(f"No such file: '{path}'")
            if isinstance(node, DirNode):
                raise IsADirectoryError(f"Is a directory: '{path}'")
            if node._rw_lock.is_locked:
                raise BlockingIOError(f"File is open: '{path}'")
            size = node.storage.get_quota_usage()
            pinfo = self._resolve_parent_and_name(npath)
            assert pinfo is not None
            parent, name = pinfo
            del parent.children[name]
            del self._nodes[node.node_id]
            self._quota.release(size)

    def rmtree(self, path: str) -> None:
        npath = self._np(path)
        if npath == "/":
            raise ValueError("Cannot remove the root directory.")
        with self._global_lock:
            node = self._resolve_path(npath)
            if node is None:
                raise FileNotFoundError(f"No such directory: '{path}'")
            if not isinstance(node, DirNode):
                raise NotADirectoryError(f"Not a directory: '{path}'")
            self._assert_no_open_handles(node, npath)
            total_released = self._calc_subtree_quota(node)
            pinfo = self._resolve_parent_and_name(npath)
            if pinfo is not None:
                parent, name = pinfo
                del parent.children[name]
            self._remove_subtree(node)
            self._quota.release(total_released)

    def _calc_subtree_quota(self, node: Node) -> int:
        total = 0
        if isinstance(node, FileNode):
            total += node.storage.get_quota_usage()
        elif isinstance(node, DirNode):
            for child_id in node.children.values():
                total += self._calc_subtree_quota(self._nodes[child_id])
        return total

    def _remove_subtree(self, node: Node) -> None:
        if isinstance(node, DirNode):
            for child_id in list(node.children.values()):
                self._remove_subtree(self._nodes[child_id])
            node.children.clear()
        if node.node_id in self._nodes:
            del self._nodes[node.node_id]

    def listdir(self, path: str) -> list[str]:
        npath = self._np(path)
        with self._global_lock:
            node = self._resolve_path(npath)
            if node is None:
                raise FileNotFoundError(f"No such directory: '{path}'")
            if not isinstance(node, DirNode):
                raise NotADirectoryError(f"Not a directory: '{path}'")
            return list(node.children.keys())

    def exists(self, path: str) -> bool:
        try:
            npath = self._np(path)
        except ValueError:
            return False
        with self._global_lock:
            return self._resolve_path(npath) is not None

    def is_dir(self, path: str) -> bool:
        try:
            npath = self._np(path)
        except ValueError:
            return False
        with self._global_lock:
            node = self._resolve_path(npath)
            return node is not None and isinstance(node, DirNode)

    def is_file(self, path: str) -> bool:
        try:
            npath = self._np(path)
        except ValueError:
            return False
        with self._global_lock:
            return isinstance(self._resolve_path(npath), FileNode)

    def stat(self, path: str) -> MFSStatResult:
        npath = self._np(path)
        with self._global_lock:
            node = self._resolve_path(npath)
            if node is None:
                raise FileNotFoundError(f"No such file or directory: '{path}'")
            if isinstance(node, DirNode):
                return MFSStatResult(
                    size=0,
                    created_at=node.created_at,
                    modified_at=node.modified_at,
                    generation=0,
                    is_dir=True,
                )
            return MFSStatResult(
                size=node.storage.get_size(),
                created_at=node.created_at,
                modified_at=node.modified_at,
                generation=node.generation,
                is_dir=False,
            )

    def stats(self) -> MFSStats:
        with self._global_lock:
            file_count = 0
            dir_count = 0
            chunk_count = 0
            for node in self._nodes.values():
                if isinstance(node, DirNode):
                    dir_count += 1
                elif isinstance(node, FileNode):
                    file_count += 1
                    if isinstance(node.storage, SequentialMemoryFile):
                        chunk_count += len(node.storage._chunks)
            quota_max, _quota_used, quota_free = self._quota.snapshot()
        return MFSStats(
            used_bytes=quota_max - quota_free,
            quota_bytes=quota_max,
            free_bytes=quota_free,
            file_count=file_count,
            dir_count=dir_count,
            chunk_count=chunk_count,
            overhead_per_chunk_estimate=self._chunk_overhead,
        )

    def get_size(self, path: str) -> int:
        npath = self._np(path)
        with self._global_lock:
            node = self._resolve_path(npath)
            if node is None:
                raise FileNotFoundError(f"No such file: '{path}'")
            if isinstance(node, DirNode):
                raise IsADirectoryError(f"Is a directory: '{path}'")
            return node.storage.get_size()

    def export_as_bytesio(self, path: str, max_size: int | None = None) -> io.BytesIO:
        """Export file contents as a BytesIO object.

        Note: The returned BytesIO object is outside quota management.
        Exporting large files may consume significant process memory
        beyond the configured quota limit.
        """
        npath = self._np(path)
        with self._global_lock:
            node = self._resolve_path(npath)
            if node is None:
                raise FileNotFoundError(f"No such file: '{path}'")
            if isinstance(node, DirNode):
                raise IsADirectoryError(f"Is a directory: '{path}'")
            fnode: FileNode = node
            fnode._rw_lock.acquire_read()
        try:
            size = fnode.storage.get_size()
            if max_size is not None and size > max_size:
                raise ValueError(f"File size {size} exceeds max_size={max_size}.")
            data = fnode.storage.read_at(0, size)
        finally:
            fnode._rw_lock.release_read()
        return io.BytesIO(data)

    def export_tree(
        self, prefix: str = "/", only_dirty: bool = False
    ) -> dict[str, bytes]:
        return dict(self.iter_export_tree(prefix=prefix, only_dirty=only_dirty))

    def iter_export_tree(
        self, prefix: str = "/", only_dirty: bool = False
    ) -> Iterator[tuple[str, bytes]]:
        nprefix = self._np(prefix)
        with self._global_lock:
            entries: list[tuple[str, FileNode]] = []
            self._collect_files(self._resolve_path(nprefix), nprefix, entries)
            if only_dirty:
                entries = [(p, fn) for p, fn in entries if fn.generation > 0]
        for fpath, fnode in entries:
            if fnode.node_id not in self._nodes:
                continue
            fnode._rw_lock.acquire_read()
            try:
                data = fnode.storage.read_at(0, fnode.storage.get_size())
            finally:
                fnode._rw_lock.release_read()
            yield fpath, data

    def _collect_files(
        self, node: Node | None, current_path: str, result: list[tuple[str, FileNode]]
    ) -> None:
        if node is None:
            return
        if isinstance(node, FileNode):
            result.append((current_path, node))
        elif isinstance(node, DirNode):
            for name, child_id in node.children.items():
                child = self._nodes[child_id]
                child_path = current_path.rstrip("/") + "/" + name
                self._collect_files(child, child_path, result)

    def import_tree(self, tree: dict[str, bytes]) -> None:
        if not tree:
            return
        with self._global_lock:
            normalized: dict[str, bytes] = {}
            for path, data in tree.items():
                npath = self._np(path)
                normalized[npath] = data

            # Check for open files
            for npath in normalized:
                node = self._resolve_path(npath)
                if (
                    node is not None
                    and isinstance(node, FileNode)
                    and node._rw_lock.is_locked
                ):
                    raise BlockingIOError(f"Cannot import: file is open: '{npath}'")

            # Calculate quota
            old_quota = 0
            old_nodes: dict[str, FileNode | None] = {}
            for npath in normalized:
                node = self._resolve_path(npath)
                if node is not None and isinstance(node, FileNode):
                    old_quota += node.storage.get_quota_usage()
                    old_nodes[npath] = node
                else:
                    old_nodes[npath] = None

            new_quota = 0
            for npath, data in normalized.items():
                if len(data) > 0:
                    new_quota += len(data) + self._chunk_overhead

            net = new_quota - old_quota
            if net > 0:
                avail = self._quota.free
                if net > avail:
                    raise MFSQuotaExceededError(requested=net, available=avail)

            written_npaths: list[str] = []
            new_fnodes: dict[str, FileNode] = {}
            created_dirs: list[str] = []

            try:
                for npath, data in normalized.items():
                    self._ensure_parents(npath, created_dirs)
                    storage = self._create_storage()
                    storage._bulk_load(data)
                    fnode = self._alloc_file(storage)
                    fnode.generation = 0
                    # Insert into parent
                    pinfo = self._resolve_parent_and_name(npath)
                    assert pinfo is not None
                    parent, name = pinfo
                    # Remove old node if exists
                    old_node = old_nodes.get(npath)
                    if old_node is not None:
                        del self._nodes[old_node.node_id]
                    parent.children[name] = fnode.node_id
                    new_fnodes[npath] = fnode
                    written_npaths.append(npath)
            except Exception:
                # Rollback
                for npath in written_npaths:
                    fn = new_fnodes.get(npath)
                    if fn is not None and fn.node_id in self._nodes:
                        del self._nodes[fn.node_id]
                    old_fn = old_nodes.get(npath)
                    pinfo = self._resolve_parent_and_name(npath)
                    if pinfo is not None:
                        parent, name = pinfo
                        if old_fn is not None:
                            self._nodes[old_fn.node_id] = old_fn
                            parent.children[name] = old_fn.node_id
                        elif name in parent.children:
                            del parent.children[name]
                self._rollback_created_dirs(created_dirs)
                raise

            if net > 0:
                self._quota._force_reserve(net)
            elif net < 0:
                self._quota.release(-net)

    def _rollback_created_dirs(self, created_dirs: list[str]) -> None:
        for dpath in reversed(created_dirs):
            node = self._resolve_path(dpath)
            if node is None or not isinstance(node, DirNode):
                continue
            if node.children:
                continue
            pinfo = self._resolve_parent_and_name(dpath)
            if pinfo is None:
                continue
            parent, name = pinfo
            child_id = parent.children.get(name)
            if child_id != node.node_id:
                continue
            del parent.children[name]
            if node.node_id in self._nodes:
                del self._nodes[node.node_id]

    def _ensure_parents(
        self, npath: str, created_dirs: list[str] | None = None
    ) -> None:
        parent_path = posixpath.dirname(npath) or "/"
        if self._resolve_path(parent_path) is None:
            self._makedirs(parent_path, created_dirs)

    def copy(self, src: str, dst: str) -> None:
        nsrc = self._np(src)
        ndst = self._np(dst)
        with self._global_lock:
            src_node = self._resolve_path(nsrc)
            if src_node is None:
                raise FileNotFoundError(f"No such file: '{src}'")
            if isinstance(src_node, DirNode):
                raise IsADirectoryError(f"Is a directory: '{src}'")
            if self._resolve_path(ndst) is not None:
                raise FileExistsError(f"Destination already exists: '{dst}'")
            src_node._rw_lock.acquire_read()
            try:
                data = src_node.storage.read_at(0, src_node.storage.get_size())
            finally:
                src_node._rw_lock.release_read()
            fnode = self._create_file(ndst)
            if data:
                n, promoted, old_quota = fnode.storage.write_at(0, data, self._quota)
                if promoted is not None:
                    fnode.storage = promoted
                    self._quota.release(old_quota)
                fnode.generation += 1

    def copy_tree(self, src: str, dst: str) -> None:
        nsrc = self._np(src)
        ndst = self._np(dst)
        with self._global_lock:
            src_node = self._resolve_path(nsrc)
            if src_node is None:
                raise FileNotFoundError(f"No such file or directory: '{src}'")
            if not isinstance(src_node, DirNode):
                raise NotADirectoryError(f"Not a directory: '{src}'")
            if self._resolve_path(ndst) is not None:
                raise FileExistsError(f"Destination already exists: '{dst}'")
            dst_pinfo = self._resolve_parent_and_name(ndst)
            if dst_pinfo is None:
                raise FileNotFoundError(f"Destination parent does not exist: '{dst}'")
            # Calculate total data to copy for quota pre-check
            total_data = self._calc_subtree_quota(src_node)
            if total_data > 0:
                avail = self._quota.free
                if total_data > avail:
                    raise MFSQuotaExceededError(requested=total_data, available=avail)
            # Deep copy the subtree with rollback on failure
            dst_parent, dst_name = dst_pinfo
            created_node_ids: list[int] = []
            try:
                new_root = self._deep_copy_subtree(src_node, created_node_ids)
            except Exception:
                for nid in reversed(created_node_ids):
                    self._nodes.pop(nid, None)
                raise
            dst_parent.children[dst_name] = new_root.node_id
            if total_data > 0:
                self._quota._force_reserve(total_data)

    def _deep_copy_subtree(
        self, node: Node, created_node_ids: list[int]
    ) -> Node:
        if isinstance(node, FileNode):
            # Read data under read lock
            node._rw_lock.acquire_read()
            try:
                data = node.storage.read_at(0, node.storage.get_size())
            finally:
                node._rw_lock.release_read()
            storage = self._create_storage()
            storage._bulk_load(data)
            new_fnode = self._alloc_file(storage)
            created_node_ids.append(new_fnode.node_id)
            new_fnode.generation = 0
            return new_fnode
        elif isinstance(node, DirNode):
            new_dir = self._alloc_dir()
            created_node_ids.append(new_dir.node_id)
            for name, child_id in node.children.items():
                child = self._nodes[child_id]
                new_child = self._deep_copy_subtree(child, created_node_ids)
                new_dir.children[name] = new_child.node_id
            return new_dir
        raise TypeError(f"Unknown node type: {type(node)}")

    def walk(self, path: str = "/") -> Iterator[tuple[str, list[str], list[str]]]:
        """Recursively walk the directory tree (top-down).

        .. warning::
            Thread Safety (Weak Consistency):
            walk() does not hold _global_lock across iterations.
            Structural changes by other threads may cause inconsistencies.
            Deleted entries are skipped (no crash).
        """
        npath = self._np(path)
        with self._global_lock:
            node = self._resolve_path(npath)
            if node is None:
                raise FileNotFoundError(f"No such directory: '{path}'")
            if not isinstance(node, DirNode):
                raise NotADirectoryError(f"Not a directory: '{path}'")
        yield from self._walk_dir(npath, node)

    def _walk_dir(
        self, dir_path: str, dir_node: DirNode
    ) -> Iterator[tuple[str, list[str], list[str]]]:
        dirnames: list[str] = []
        filenames: list[str] = []
        child_dirs: list[tuple[str, DirNode]] = []
        with self._global_lock:
            snapshot = list(dir_node.children.items())
        for name, child_id in snapshot:
            child = self._nodes.get(child_id)
            if child is None:
                continue
            if isinstance(child, DirNode):
                dirnames.append(name)
                child_dirs.append((dir_path.rstrip("/") + "/" + name, child))
            else:
                filenames.append(name)
        yield dir_path, dirnames, filenames
        for child_path, child_dir in child_dirs:
            if child_dir.node_id in self._nodes:
                yield from self._walk_dir(child_path, child_dir)

    def glob(self, pattern: str) -> list[str]:
        """Return a sorted list of paths matching *pattern*.

        Supports `*` (single dir), `**` (recursive), `?`, `[seq]`.
        """
        pattern = pattern.replace("\\", "/")
        if not pattern.startswith("/"):
            pattern = "/" + pattern
        parts = [p for p in pattern.split("/") if p]
        results: list[str] = []
        self._glob_match(self._root, "/", parts, 0, results)
        return sorted(results)

    def _glob_match(
        self,
        node: Node,
        current_path: str,
        parts: list[str],
        idx: int,
        results: list[str],
    ) -> None:
        if not isinstance(node, DirNode):
            return
        if idx >= len(parts):
            return
        part = parts[idx]
        is_last = idx == len(parts) - 1

        with self._global_lock:
            snapshot = list(node.children.items())

        if part == "**":
            # --- Zero-depth match: skip ** and try next part at current node ---
            if idx + 1 < len(parts):
                self._glob_match(node, current_path, parts, idx + 1, results)
            else:
                # ** at end of pattern: collect everything recursively
                self._collect_all_paths(node, current_path, results)

            # --- One-or-more depth match: recurse into children ---
            for name, child_id in snapshot:
                child = self._nodes.get(child_id)
                if child is None:
                    continue
                child_path = current_path.rstrip("/") + "/" + name
                if isinstance(child, DirNode):
                    # Continue recursive ** expansion into subdirectories
                    self._glob_match(child, child_path, parts, idx, results)
                elif isinstance(child, FileNode):
                    if idx + 1 < len(parts):
                        # ** before more parts: match file against next part
                        next_part = parts[idx + 1]
                        if (
                            fnmatch.fnmatch(name, next_part)
                            and idx + 1 == len(parts) - 1
                        ):
                            results.append(child_path)
                    else:
                        # ** at end: file matches
                        results.append(child_path)
        else:
            for name, child_id in snapshot:
                if not fnmatch.fnmatch(name, part):
                    continue
                child = self._nodes.get(child_id)
                if child is None:
                    continue
                child_path = current_path.rstrip("/") + "/" + name
                if is_last:
                    results.append(child_path)
                elif isinstance(child, DirNode):
                    self._glob_match(child, child_path, parts, idx + 1, results)

    def _collect_all_paths(
        self, node: DirNode, current_path: str, results: list[str]
    ) -> None:
        with self._global_lock:
            snapshot = list(node.children.items())
        for name, child_id in snapshot:
            child = self._nodes.get(child_id)
            if child is None:
                continue
            child_path = current_path.rstrip("/") + "/" + name
            results.append(child_path)
            if isinstance(child, DirNode):
                self._collect_all_paths(child, child_path, results)
