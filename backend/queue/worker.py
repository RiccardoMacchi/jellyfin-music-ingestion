"""
Pipeline di ingestion per un singolo job: esegue in ordine tutti gli step
descritti nella filosofia del progetto (metadata -> download -> conversione
-> tag -> cover -> filename -> organizzazione -> validazione -> atomic move
-> refresh Jellyfin opzionale), aggiornando lo stato in DB ad ogni fase cosi'
che la UI possa mostrarlo in tempo (quasi) reale.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from backend.audio.converter import ConversionError, convert_audio
from backend.config import settings
from backend.cover.cover_manager import CoverError, find_downloaded_thumbnail, normalize_to_jpeg, should_write_cover
from backend.database.models import DownloadRecord, DownloadStatus
from backend.database.repository import DownloadRepository
from backend.downloader.ytdlp_client import DownloadError, download_audio
from backend.jellyfin.client import trigger_library_refresh
from backend.library.mover import MoveError, atomic_move, copy_cover_if_needed
from backend.library.path_builder import build_library_path
from backend.library.validator import ValidationError, validate_audio_file, validate_cover_file
from backend.metadata.normalizer import TrackMetadata
from backend.metadata.tagger import TaggingError, write_tags
from backend.queue.events import event_bus
from backend.utils.logging import get_logger

logger = get_logger(__name__)

# id dei job per cui e' stata richiesta la cancellazione mentre erano in
# esecuzione. Controllato dal progress_hook di yt-dlp tra un chunk e l'altro.
_cancel_requested: set[int] = set()


class JobCancelled(RuntimeError):
    pass


def request_cancel(download_id: int) -> None:
    _cancel_requested.add(download_id)


def _record_to_metadata(record: DownloadRecord) -> TrackMetadata:
    """Ricostruisce i TrackMetadata finali dai campi gia' decisi/confermati
    al momento della creazione del job (analisi + eventuali correzioni utente
    dalla UI, gia' persistite come colonne della riga `downloads`)."""
    is_compilation = record.album_artist.strip().lower() == "various artists"
    return TrackMetadata(
        title=record.title or "Unknown Title",
        artist=record.artist or "Unknown Artist",
        album_artist=record.album_artist or record.artist or "Unknown Artist",
        album=record.album or "",
        track_number=record.track_number,
        disc_number=record.disc_number,
        year=record.year,
        genre=record.genre,
        composer=record.composer,
        comment=f"Ingested from {record.url}",
        featured_artists=[],
        is_compilation=is_compilation,
        is_single=not bool((record.album or "").strip()),
    )


def _make_progress_hook(repo: DownloadRepository, download_id: int):
    def hook(status: dict) -> None:
        if download_id in _cancel_requested:
            raise JobCancelled("Download annullato dall'utente")

        if status.get("status") == "downloading":
            total = status.get("total_bytes") or status.get("total_bytes_estimate")
            downloaded = status.get("downloaded_bytes") or 0
            progress = round((downloaded / total) * 100, 1) if total else 0.0
            speed = status.get("_speed_str", "").strip()
            eta = status.get("_eta_str", "").strip()
            repo.update_progress(download_id, progress, speed, eta)
            event_bus.publish(download_id)
        elif status.get("status") == "finished":
            repo.update_progress(download_id, 100.0, "", "")
            event_bus.publish(download_id)

    return hook


async def process_job(record: DownloadRecord, repo: DownloadRepository) -> None:
    download_id = record.id
    assert download_id is not None
    stem = f"job_{download_id}"
    tmp_dir = settings.tmp_download_path
    Path(tmp_dir).mkdir(parents=True, exist_ok=True)

    downloaded_raw_path = ""
    tmp_converted_path = ""
    tmp_cover_path = ""

    try:
        repo.update_status(download_id, DownloadStatus.DOWNLOADING)
        event_bus.publish(download_id)

        hook = _make_progress_hook(repo, download_id)
        downloaded_raw_path, video_info = await asyncio.to_thread(
            download_audio, record.url, tmp_dir, stem, hook
        )

        repo.update_status(download_id, DownloadStatus.PROCESSING)
        event_bus.publish(download_id)

        metadata = _record_to_metadata(record)
        audio_ext = settings.audio_format
        tmp_converted_path = f"{tmp_dir}/{stem}.converted.{audio_ext}"

        await convert_audio(downloaded_raw_path, tmp_converted_path, audio_ext)

        cover_bytes: bytes | None = None
        thumb_source = find_downloaded_thumbnail(tmp_dir, stem)
        if thumb_source:
            tmp_cover_path = f"{tmp_dir}/{stem}.cover.jpg"
            try:
                cover_bytes = await asyncio.to_thread(normalize_to_jpeg, thumb_source, tmp_cover_path)
            except CoverError as exc:
                logger.warning("Cover scartata per job %s: %s", download_id, exc)
                cover_bytes = None

        await asyncio.to_thread(write_tags, tmp_converted_path, metadata, cover_bytes)

        file_path, album_cover_path = build_library_path(metadata, audio_ext)

        # Duplicate detection livello 3: path finale gia' occupato su disco.
        if Path(file_path).exists():
            repo.update_status(
                download_id, DownloadStatus.SKIPPED,
                error="Un file identico esiste gia' in libreria a questo percorso",
            )
            event_bus.publish(download_id)
            return

        await validate_audio_file(tmp_converted_path, audio_ext)
        if cover_bytes:
            validate_cover_file(tmp_cover_path)

        atomic_move(tmp_converted_path, file_path)
        tmp_converted_path = ""  # spostato: non va piu' ripulito da qui

        written_cover_path = ""
        if cover_bytes and album_cover_path and should_write_cover(album_cover_path):
            copy_cover_if_needed(tmp_cover_path, album_cover_path)
            written_cover_path = album_cover_path

        repo.set_file_path(download_id, file_path, written_cover_path)
        repo.update_status(download_id, DownloadStatus.COMPLETED)
        event_bus.publish(download_id)

        await trigger_library_refresh()

    except JobCancelled:
        repo.update_status(download_id, DownloadStatus.CANCELLED, error="Annullato dall'utente")
        event_bus.publish(download_id)
    except (DownloadError, ConversionError, TaggingError, CoverError, ValidationError, MoveError) as exc:
        logger.error("Job %s fallito: %s", download_id, exc)
        repo.update_status(download_id, DownloadStatus.FAILED, error=str(exc))
        event_bus.publish(download_id)
    except Exception as exc:  # ultima rete di sicurezza: mai far crashare il worker
        logger.exception("Errore inatteso nel job %s", download_id)
        repo.update_status(download_id, DownloadStatus.FAILED, error=f"Errore interno: {exc}")
        event_bus.publish(download_id)
    finally:
        _cancel_requested.discard(download_id)
        for p in (downloaded_raw_path, tmp_converted_path, tmp_cover_path):
            if p and Path(p).exists():
                try:
                    Path(p).unlink()
                except OSError:
                    pass
        # yt-dlp puo' lasciare la thumbnail originale accanto al file scaricato
        thumb = find_downloaded_thumbnail(tmp_dir, stem)
        if thumb and Path(thumb).exists():
            try:
                Path(thumb).unlink()
            except OSError:
                pass
