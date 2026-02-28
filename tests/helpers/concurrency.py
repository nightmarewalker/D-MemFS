import threading


class ThreadedLockHolder:
    def __init__(self, mfs, path: str, mode: str):
        self._mfs = mfs
        self._path = path
        self._mode = mode
        self._handle = None
        self._ready = threading.Event()
        self._release = threading.Event()
        self._thread = None

    def __enter__(self):
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        self._ready.wait(timeout=5.0)
        return self

    def __exit__(self, *_):
        self._release.set()
        self._thread.join(timeout=5.0)

    def _run(self):
        with self._mfs.open(self._path, self._mode) as h:
            self._ready.set()
            self._release.wait(timeout=10.0)


def run_concurrent(target_fn, n_threads: int, timeout: float = 5.0):
    results = [None] * n_threads
    errors = [None] * n_threads
    threads = []
    start_barrier = threading.Barrier(n_threads)

    def worker(i):
        try:
            start_barrier.wait(timeout=timeout)
            results[i] = target_fn(i)
        except Exception as e:
            errors[i] = e

    for i in range(n_threads):
        t = threading.Thread(target=worker, args=(i,), daemon=True)
        threads.append(t)
        t.start()
    for t in threads:
        t.join(timeout=timeout + 1.0)
    return results, errors
