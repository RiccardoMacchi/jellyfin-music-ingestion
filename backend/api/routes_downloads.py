"""Endpoint per creare/gestire i download in coda."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException

from backend.api.dependencies import get_download_repo
from backend.api.schemas import DownloadCreateRequest, DownloadOut
from backend.database.models import DownloadRecord, DownloadStatus
from backend.database.repository import DownloadRepository
from backend.downloader.validator import InvalidURLError, extract_video_id_hint
from backend.downloader.ytdlp_client import DownloadError, extract_video_info
from backend.metadata.parser import parse_title
from backend.queue.worker import request_cancel
from backend.security.rate_limit import rate_limiter
from backend.utils.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api", tags=["downloads"], dependencies=[Depends(rate_limiter)])

_ACTIVE_STATUSES = {DownloadStatus.PENDING.value, DownloadStatus.DOWNLOADING.value, DownloadStatus.PROCESSING.value}


def _to_out(record: DownloadRecord) -> DownloadOut:
    return DownloadOut(**{k: getattr(record, k) for k in DownloadOut.model_fields})


@router.post("/download", response_model=DownloadOut)
async def create_download(payload: DownloadCreateRequest, repo: DownloadRepository = Depends(get_download_repo)) -> DownloadOut:
    youtube_id = payload.youtube_id
    title, artist = payload.title, payload.artist
    thumbnail_url = payload.thumbnail_url or ""
    duration = payload.duration_seconds

    # Se il client non ha gia' passato i dati (es. chiamata diretta senza
    # passare da /api/analyze), li recuperiamo qui. Questo tiene l'endpoint
    # utilizzabile anche in modo standalone.
    if not youtube_id or not title or not artist:
        try:
            info = await asyncio.to_thread(extract_video_info, payload.url)
        except DownloadError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        try:
            youtube_id = youtube_id or extract_video_id_hint({"id": info.id})
        except InvalidURLError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if not title or not artist:
            parsed = parse_title(info.title, channel_name=info.uploader)
            title = title or parsed.title or info.title
            artist = artist or parsed.artist or info.uploader
        thumbnail_url = thumbnail_url or info.thumbnail
        duration = duration if duration is not None else info.duration

    # Duplicate detection livello 1/2: stesso video YouTube gia' in coda o
    # gia' completato -> non ne creiamo un altro, ritorniamo quello esistente.
    existing = await asyncio.to_thread(repo.find_by_youtube_id, youtube_id)
    if existing:
        logger.info("Download duplicato ignorato per youtube_id=%s (job esistente #%s)", youtube_id, existing.id)
        return _to_out(existing)

    album = payload.album or ""
    album_artist = payload.album_artist or ("Various Artists" if payload.is_compilation else (artist or ""))

    record = DownloadRecord(
        youtube_id=youtube_id,
        url=payload.url,
        title=title or "Unknown Title",
        artist=artist or "Unknown Artist",
        album=album,
        album_artist=album_artist,
        track_number=payload.track_number,
        disc_number=payload.disc_number,
        year=payload.year,
        genre=payload.genre or "",
        composer=payload.composer or "",
        source_type=payload.source_type,
        playlist_id=payload.playlist_id,
        position_in_playlist=payload.position_in_playlist,
        duration_seconds=duration,
        thumbnail_url=thumbnail_url,
        status=DownloadStatus.PENDING.value,
    )
    created = await asyncio.to_thread(repo.create, record)
    return _to_out(created)


@router.get("/downloads", response_model=list[DownloadOut])
async def list_downloads(status: str | None = None, repo: DownloadRepository = Depends(get_download_repo)) -> list[DownloadOut]:
    records = await asyncio.to_thread(repo.list, status)
    return [_to_out(r) for r in records]


@router.get("/downloads/{download_id}", response_model=DownloadOut)
async def get_download(download_id: int, repo: DownloadRepository = Depends(get_download_repo)) -> DownloadOut:
    record = await asyncio.to_thread(repo.get, download_id)
    if not record:
        raise HTTPException(status_code=404, detail="Download non trovato")
    return _to_out(record)


@router.post("/downloads/{download_id}/retry", response_model=DownloadOut)
async def retry_download(download_id: int, repo: DownloadRepository = Depends(get_download_repo)) -> DownloadOut:
    record = await asyncio.to_thread(repo.get, download_id)
    if not record:
        raise HTTPException(status_code=404, detail="Download non trovato")
    if record.status not in (DownloadStatus.FAILED.value, DownloadStatus.CANCELLED.value):
        raise HTTPException(status_code=409, detail=f"Impossibile ritentare un job in stato {record.status}")

    await asyncio.to_thread(repo.increment_retry, download_id)
    await asyncio.to_thread(repo.update_metadata, download_id, error="")
    await asyncio.to_thread(repo.update_status, download_id, DownloadStatus.PENDING)
    updated = await asyncio.to_thread(repo.get, download_id)
    return _to_out(updated)


@router.post("/downloads/{download_id}/cancel", response_model=DownloadOut)
async def cancel_download(download_id: int, repo: DownloadRepository = Depends(get_download_repo)) -> DownloadOut:
    record = await asyncio.to_thread(repo.get, download_id)
    if not record:
        raise HTTPException(status_code=404, detail="Download non trovato")
    if record.status not in _ACTIVE_STATUSES:
        raise HTTPException(status_code=409, detail=f"Impossibile annullare un job in stato {record.status}")

    if record.status == DownloadStatus.PENDING.value:
        await asyncio.to_thread(repo.update_status, download_id, DownloadStatus.CANCELLED, "Annullato dall'utente")
    else:
        # Job gia' in esecuzione in un thread: chiediamo la cancellazione in
        # modo cooperativo, sara' il worker a portare lo stato a CANCELLED.
        request_cancel(download_id)

    updated = await asyncio.to_thread(repo.get, download_id)
    return _to_out(updated)


@router.delete("/downloads/{download_id}")
async def delete_download(download_id: int, repo: DownloadRepository = Depends(get_download_repo)) -> dict:
    record = await asyncio.to_thread(repo.get, download_id)
    if not record:
        raise HTTPException(status_code=404, detail="Download non trovato")
    if record.status in (DownloadStatus.DOWNLOADING.value, DownloadStatus.PROCESSING.value):
        raise HTTPException(status_code=409, detail="Annulla il job prima di eliminarlo")

    await asyncio.to_thread(repo.delete, download_id)
    return {"deleted": True, "id": download_id}
