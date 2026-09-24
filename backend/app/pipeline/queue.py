"""Background processing: one worker thread, FIFO.

Uploads return immediately (202); the worker runs `process_job` for each document in order and the
UI polls the status. Destructive-mode bytes live only in the queued job, in memory — never on disk.
On startup, documents left mid-processing by a previous run are re-queued when their original is
stored (mapping mode) and marked FAILED otherwise.
"""
from __future__ import annotations

import logging
import queue
import threading
from collections.abc import Callable
from dataclasses import dataclass

from app.config import Settings
from app.models.document import DocumentStatus
from app.pipeline.runner import process_job
from app.review.reasons import REVIEW_REASONS
from app.services.repository import DocumentRepository

logger = logging.getLogger(__name__)


@dataclass
class Job:
    doc_id: str
    data: bytes | None  # None: read the stored original (mapping mode)


class Worker:
    def __init__(self, settings: Callable[[], Settings],
                 repo: Callable[[], DocumentRepository]) -> None:
        self._settings = settings
        self._repo = repo
        self._queue: queue.Queue[Job | None] = queue.Queue()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._loop, name="fable-worker", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        if self._thread and self._thread.is_alive():
            self._queue.put(None)
            self._thread.join(timeout)

    def submit(self, job: Job) -> None:
        self._queue.put(job)

    @property
    def alive(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def recover(self) -> int:
        """Re-queue interrupted documents; returns how many were re-queued."""
        repo = self._repo()
        requeued = 0
        for doc in repo.list_documents():
            if not doc.status.processing:
                continue
            if doc.mode == "mapping" and repo.get_original(doc.id) is not None:
                doc.transition(DocumentStatus.QUEUED)
                repo.save_document(doc)
                self.submit(Job(doc.id, None))
                requeued += 1
            else:
                doc.add_reason("processing_interrupted", REVIEW_REASONS["processing_interrupted"])
                doc.transition(DocumentStatus.FAILED)
                repo.save_document(doc)
        return requeued

    def _loop(self) -> None:
        while True:
            job = self._queue.get()
            if job is None:
                return
            try:
                process_job(job.doc_id, job.data, self._settings(), self._repo())
            except Exception as e:  # noqa: BLE001 — process_job already fails closed
                logger.error("worker error: %s", type(e).__name__)
            finally:
                job.data = None  # drop destructive-mode bytes as soon as possible
