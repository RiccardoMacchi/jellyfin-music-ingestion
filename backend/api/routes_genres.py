"""Endpoint per generi (modifica manuale, riconoscimento sui brani gia'
scaricati) e playlist per genere su Jellyfin."""
from __future__ import annotations

import asyncio
from dataclasses import asdict
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from backend.api.dependencies import get_download_repo
from backend.api.schemas import (
    DownloadOut,
    GenreCount,
    GenreDetectRequest,
    GenreOverview,
    GenreUpdateRequest,
    PlaylistSyncResponse,
)
from backend.config import settings
from backend.database.models import DownloadStatus
from backend.database.repository import DownloadRepository
from backend.genre import backfill
from backend.jellyfin.client import trigger_library_refresh
from backend.jellyfin.playlists import (
    PlaylistSyncError,
    playlists_available,
    schedule_playlist_sync,
    sync_genre_playlists,
)
from backend.metadata.tagger import TaggingError, write_genre
from backend.security.rate_limit import rate_limiter

# Rate limit solo sulle operazioni che scrivono/chiamano servizi esterni: la
# panoramica in sola lettura viene interrogata spesso dalla UI durante il
# riconoscimento e non deve consumare il budget delle altre richieste.
router = APIRouter(prefix="/api", tags=["genres"])
_limited = [Depends(rate_limiter)]


def _to_out(record) -> DownloadOut:
    return DownloadOut(**{k: getattr(record, k) for k in DownloadOut.model_fields})


@router.get("/genres", response_model=GenreOverview)
async def genres_overview(repo: DownloadRepository = Depends(get_download_repo)) -> GenreOverview:
    counts = await asyncio.to_thread(repo.genre_counts)
    return GenreOverview(
        genres=[GenreCount(genre=g, count=n) for g, n in counts if g],
        untagged=sum(n for g, n in counts if not g),
        backfill=backfill.get_status(),
        playlists_available=playlists_available(),
        playlist_prefix=settings.genre_playlist_prefix,
    )


@router.post("/genres/detect", dependencies=_limited)
async def detect_genres(payload: GenreDetectRequest, repo: DownloadRepository = Depends(get_download_repo)) -> dict:
    """Avvia in background il riconoscimento del genere per i brani gia'
    in libreria. Lo stato si legge da GET /api/genres."""
    started = backfill.start_backfill(repo, force=payload.force)
    if not started:
        raise HTTPException(status_code=409, detail="Riconoscimento dei generi gia' in corso")
    return {"started": True}


@router.post("/downloads/{download_id}/genre", response_model=DownloadOut, dependencies=_limited)
async def set_genre(
    download_id: int, payload: GenreUpdateRequest, repo: DownloadRepository = Depends(get_download_repo)
) -> DownloadOut:
    """Imposta il genere a mano. Su un brano completato aggiorna anche il tag
    nel file. Un genere manuale non viene mai sovrascritto dal riconoscimento
    automatico; un genere vuoto lo riabilita."""
    record = await asyncio.to_thread(repo.get, download_id)
    if not record:
        raise HTTPException(status_code=404, detail="Download non trovato")
    if record.status in (DownloadStatus.DOWNLOADING.value, DownloadStatus.PROCESSING.value):
        raise HTTPException(status_code=409, detail="Attendi la fine del download")

    genre = payload.genre.strip()
    if record.status == DownloadStatus.COMPLETED.value and record.file_path and Path(record.file_path).exists():
        try:
            await asyncio.to_thread(write_genre, record.file_path, genre)
        except TaggingError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    await asyncio.to_thread(
        repo.update_metadata, download_id, genre=genre, genre_source="manual" if genre else "",
    )

    if record.status == DownloadStatus.COMPLETED.value:
        await trigger_library_refresh()
        schedule_playlist_sync(repo)

    return _to_out(await asyncio.to_thread(repo.get, download_id))


@router.post("/playlists/sync", response_model=PlaylistSyncResponse, dependencies=_limited)
async def sync_playlists(repo: DownloadRepository = Depends(get_download_repo)) -> PlaylistSyncResponse:
    try:
        result = await sync_genre_playlists(repo)
    except PlaylistSyncError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:  # errore di rete/HTTP verso Jellyfin
        raise HTTPException(status_code=502, detail=f"Jellyfin non raggiungibile o errore API: {exc}") from exc
    return PlaylistSyncResponse(**asdict(result))
