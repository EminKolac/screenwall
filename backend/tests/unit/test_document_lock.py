"""Per-document locks (review hardening B1): app/services/locks.py."""
from __future__ import annotations

import gc
import threading

import pytest

from app.services import locks
from app.services.locks import LockTimeout, document_lock


def _try_elsewhere(doc_id: str, timeout: float) -> bool:
    """True when another thread could take the document's lock within `timeout`."""
    got: list[bool] = []

    def attempt() -> None:
        try:
            with document_lock(doc_id, timeout=timeout):
                got.append(True)
        except LockTimeout:
            got.append(False)

    t = threading.Thread(target=attempt)
    t.start()
    t.join()
    return got == [True]


def test_the_lock_is_reentrant_for_its_holder() -> None:
    with document_lock("d1"), document_lock("d1"):
        pass


def test_a_held_lock_blocks_other_threads_until_released() -> None:
    with document_lock("d2"):
        assert not _try_elsewhere("d2", timeout=0.05)
    assert _try_elsewhere("d2", timeout=0.05)


def test_documents_do_not_block_each_other() -> None:
    with document_lock("d3"):
        assert _try_elsewhere("d4", timeout=0.05)


def test_a_timeout_raises_lock_timeout_in_the_waiting_thread() -> None:
    raised: list[type] = []

    def wait() -> None:
        with pytest.raises(LockTimeout):
            with document_lock("d5", timeout=0.01):
                pass
        raised.append(LockTimeout)

    with document_lock("d5"):
        t = threading.Thread(target=wait)
        t.start()
        t.join()
    assert raised == [LockTimeout]


def test_locks_do_not_accumulate_after_use() -> None:
    for i in range(50):
        with document_lock(f"many-{i}"):
            pass
    gc.collect()
    assert not any(k.startswith("many-") for k in locks._LOCKS.keys())
