"""
Loop della coda persistente: pesca job PENDING dal DB e li esegue rispettando
MAX_CONCURRENT_DOWNLOADS. La coda sopravvive a restart/crash perche' vive
interamente nel DB (vedi DownloadRepository.recover_stuck_jobs, chiamato una
volta sola all'avvio dell'app in main.py).
"""
from __future__ import annotations

import asyncio

from backend.config import settings
from backend.database.repository import DownloadRepository
from backend.queue.worker import process_job
from backend.utils.logging import get_logger

logger = get_logger(__name__)

_IDLE_POLL_SECONDS = 2.0


class QueueManager:
    def __init__(self, repo: DownloadRepository):
        self.repo = repo
        self._semaphore = asyncio.Semaphore(settings.max_concurrent_downloads)
        self._task: asyncio.Task | None = None
        self._running = False

    def start(self) -> None:
        if self._task is None:
            self._running = True
            self._task = asyncio.create_task(self._loop(), name="queue-manager")
            logger.info("Queue manager avviato (max_concurrent=%s)", settings.max_concurrent_downloads)

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _loop(self) -> None:
        while self._running:
            try:
                record = await asyncio.to_thread(self.repo.next_pending)
                if record is None:
                    await asyncio.sleep(_IDLE_POLL_SECONDS)
                    continue

                await self._semaphore.acquire()
                asyncio.create_task(self._run_job(record))
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Errore nel loop della coda")
                await asyncio.sleep(_IDLE_POLL_SECONDS)

    async def _run_job(self, record) -> None:
        try:
            await process_job(record, self.repo)
        finally:
            self._semaphore.release()
