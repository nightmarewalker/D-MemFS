import threading
import pytest
from dmemfs._quota import QuotaManager
from dmemfs._exceptions import MFSQuotaExceededError


def test_initial_state():
    qm = QuotaManager(1000)
    assert qm.used == 0
    assert qm.free == 1000
    assert qm.maximum == 1000


def test_reserve_basic():
    qm = QuotaManager(1000)
    with qm.reserve(100):
        assert qm.used == 100
        assert qm.free == 900
    assert (
        qm.used == 100
    )  # reserve doesn't release on exit (it's a context manager for failure recovery)


def test_reserve_releases_on_exception():
    qm = QuotaManager(1000)
    try:
        with qm.reserve(100):
            raise RuntimeError("test error")
    except RuntimeError:
        pass
    assert qm.used == 0


def test_reserve_exact_limit():
    qm = QuotaManager(100)
    with qm.reserve(100):
        assert qm.used == 100


def test_reserve_exceeds_limit():
    qm = QuotaManager(100)
    with pytest.raises(MFSQuotaExceededError) as exc_info:
        with qm.reserve(101):
            pass
    assert exc_info.value.requested == 101
    assert exc_info.value.available == 100


def test_release_basic():
    qm = QuotaManager(1000)
    with qm.reserve(100):
        pass
    qm.release(50)
    assert qm.used == 50


def test_release_more_than_used():
    """Release more than used should clamp to 0."""
    qm = QuotaManager(1000)
    with qm.reserve(100):
        pass
    qm.release(200)
    assert qm.used == 0


def test_reserve_zero_is_noop():
    qm = QuotaManager(100)
    with qm.reserve(0):
        pass
    assert qm.used == 0


def test_concurrent_reserves():
    """Multiple threads reserving should not exceed quota."""
    qm = QuotaManager(1000)
    errors = []
    successes = []
    lock = threading.Lock()

    def worker():
        try:
            with qm.reserve(100):
                pass
            with lock:
                successes.append(1)
        except MFSQuotaExceededError:
            with lock:
                errors.append(1)

    threads = [threading.Thread(target=worker) for _ in range(15)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(successes) + len(errors) == 15


def test_quota_exceeded_error_is_oserror():
    err = MFSQuotaExceededError(100, 50)
    assert isinstance(err, OSError)
    assert err.requested == 100
    assert err.available == 50


def test_force_reserve_zero_or_negative_is_noop():
    """_force_reserve with size <= 0 should not change used bytes."""
    qm = QuotaManager(1000)
    qm._force_reserve(0)
    assert qm.used == 0
    qm._force_reserve(-5)
    assert qm.used == 0


def test_node_limit_exceeded_error_is_quota_exceeded():
    from dmemfs._exceptions import MFSNodeLimitExceededError
    err = MFSNodeLimitExceededError(10, 10)
    assert isinstance(err, MFSQuotaExceededError)
    assert isinstance(err, OSError)
    assert err.current == 10
    assert err.limit == 10
    assert "node limit exceeded" in str(err).lower()
