"""Per-document locks: one writer at a time for everything that reads, changes and saves a document.

Every mutating path — a review decision, approve, reject, delete and the worker's processing run —
takes the document's lock and then RE-READS the document inside it: an object read before the lock
may be stale, or its document may be gone. The locks are re-entrant (a locked path may call another
locked helper) and live in a guarded weak-value dict, so a document's lock exists only while
someone holds or waits for it. Process-local by design: the app runs as one process (start.sh).
"""
from __future__ import annotations

import threading
import weakref
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

_GUARD = threading.Lock()
_LOCKS: weakref.WeakValueDictionary[str, Any] = weakref.WeakValueDictionary()


class LockTimeout(Exception):
    """The document stayed locked (being processed or changed) longer than the caller waits."""


def _lock_for(doc_id: str) -> Any:
    with _GUARD:
        lock = _LOCKS.get(doc_id)
        if lock is None:
            lock = threading.RLock()
            _LOCKS[doc_id] = lock
        return lock


@contextmanager
def document_lock(doc_id: str, timeout: float | None = None) -> Iterator[None]:
    """Hold `doc_id`'s lock for the block. With `timeout` (seconds), raise LockTimeout instead of
    waiting longer; without it, wait as long as it takes."""
    lock = _lock_for(doc_id)
    if not lock.acquire(timeout=-1 if timeout is None else timeout):
        raise LockTimeout(doc_id)
    try:
        yield
    finally:
        lock.release()
