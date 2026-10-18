"""
Riconoscimento del genere per i brani GIA' in libreria.

Gira in background (una sola esecuzione alla volta): per ogni brano
completato senza genere (o per tutti, con `force`) interroga i provider,
scrive il tag genere nel file e aggiorna il DB. I generi inseriti a mano
dall'utente (genre_source = "manual") non vengono mai sovrascritti.
Alla fine, se configurato, sincronizza le playlist per genere su Jellyfin.
"""
from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass
from pathlib import Path

from backend.database.repository import DownloadRepository
from backend.genre.detector import detect_genre, primary_artist
from backend.jellyfin.client import trigger_library_refresh
from backend.jellyfin.playlists import playlists_available, schedule_playlist_sync
from backend.metadata.tagger import TaggingError, write_genre
from backend.queue.events import event_bus
from backend.utils.logging import get_logger

logger = get_logger(__name__)


@dataclass
class BackfillStatus:
    running: bool = False
    total: int = 0
    processed: int = 0
    updated: int = 0
    not_found: int = 0
    errors: int = 0
    current: str = ""


status = BackfillStatus()
_task: asyncio.Task | None = None


def get_status() -> dict:
    return asdict(status)


def start_backfill(repo: DownloadRepository, force: bool = False) -> bool:
    """Avvia il backfill in background. False se ne e' gia' in corso uno."""
    global _task
    if _task and not _task.done():
        return False
    # Stato "in corso" impostato SUBITO: la UI interroga /api/genres appena
    # dopo l'avvio e, se il task non e' ancora partito, lo vedrebbe gia'
    # "concluso" smettendo di aggiornarsi.
    status.__init__(running=True)
    _task = asyncio.create_task(_run(repo, force), name="genre-backfill")
    return True


async def _run(repo: DownloadRepository, force: bool) -> None:
    try:
        records = await asyncio.to_thread(repo.list_completed)
        todo = [
            r for r in records
            if r.genre_source != "manual" and (force or not r.genre.strip())
        ]
        status.total = len(todo)
        for record in todo:
            status.current = f"{record.artist} - {record.title}"
            try:
                result = await detect_genre(primary_artist(record.artist, record.album_artist), record.title)
                if not result:
                    status.not_found += 1
                elif result.genre != record.genre:
                    if Path(record.file_path).exists():
                        await asyncio.to_thread(write_genre, record.file_path, result.genre)
                    await asyncio.to_thread(
                        repo.update_metadata, record.id, genre=result.genre, genre_source=result.source,
                    )
                    status.updated += 1
                    event_bus.publish(record.id)
            except TaggingError as exc:
                logger.warning("Genere non scritto nel file per il job %s: %s", record.id, exc)
                status.errors += 1
            except Exception:
                logger.exception("Errore inatteso nel backfill del genere (job %s)", record.id)
                status.errors += 1
            status.processed += 1
    finally:
        status.running = False
        status.current = ""

    logger.info(
        "Backfill generi completato: %s aggiornati, %s non trovati, %s errori su %s",
        status.updated, status.not_found, status.errors, status.total,
    )
    if status.updated:
        await trigger_library_refresh()
        if playlists_available():
            schedule_playlist_sync(repo)
