"""
Unico punto di contatto con yt-dlp.

Nessun altro modulo deve importare `yt_dlp` direttamente: questo isola il
resto del backend da eventuali cambi di API della libreria e concentra qui
la gestione di errori/retry/timeout.

yt-dlp e' sincrono: le funzioni qui sono sincrone e vanno chiamate dai
chiamanti async tramite `asyncio.to_thread` (fatto nel queue worker).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Callable, Optional

import yt_dlp

from backend.config import settings
from backend.utils.logging import get_logger

logger = get_logger(__name__)

ProgressHook = Callable[[dict], None]


class DownloadError(RuntimeError):
    pass


@dataclass
class VideoInfo:
    id: str
    title: str
    uploader: str
    duration: Optional[int]
    thumbnail: str
    webpage_url: str
    is_playlist_item: bool = False
    playlist_id: Optional[str] = None
    playlist_title: Optional[str] = None
    playlist_index: Optional[int] = None
    raw: dict = field(default_factory=dict)


@dataclass
class PlaylistEntry:
    id: str
    title: str
    url: str
    index: int


@dataclass
class PlaylistInfo:
    id: str
    title: str
    entries: list[PlaylistEntry]


def _auth_opts() -> dict:
    """Opzioni per aggirare il blocco anti-bot di YouTube.

    - `cookiefile`: cookie di un browser loggato, se configurato. E' la via
      piu' affidabile contro "Sign in to confirm you're not a bot".
    - `extractor_args`: client YouTube alternativo, a volte sufficiente da solo.
    """
    opts: dict = {}

    cookies = (settings.youtube_cookies_file or "").strip()
    if cookies:
        if os.path.isfile(cookies):
            logger.info("yt-dlp: uso cookie file %s", cookies)
            opts["cookiefile"] = cookies
        else:
            logger.warning(
                "yt-dlp: YOUTUBE_COOKIES_FILE=%s ma il file NON esiste dentro il "
                "container (o non e' leggibile). I cookie NON verranno usati.",
                cookies,
            )
    else:
        logger.info("yt-dlp: nessun cookie file configurato (YOUTUBE_COOKIES_FILE vuoto)")

    player_client = (settings.youtube_player_client or "").strip()
    if player_client:
        clients = [c.strip() for c in player_client.split(",") if c.strip()]
        opts["extractor_args"] = {"youtube": {"player_client": clients}}

    remote = (settings.youtube_remote_components or "").strip()
    if remote:
        opts["remote_components"] = [c.strip() for c in remote.split(",") if c.strip()]

    return opts


def _base_opts(quiet: bool = True) -> dict:
    opts = {
        "quiet": quiet,
        "no_warnings": quiet,
        "noplaylist": False,
        "skip_download": True,
        "extract_flat": False,
        # In analisi vogliamo SOLO i metadata (titolo, uploader, thumbnail): non
        # deve fallire se la risoluzione dei formati e' problematica (es. YouTube
        # che forza SABR). Il formato scaricabile lo cerca il download vero.
        "ignore_no_formats_error": True,
        "socket_timeout": 30,
        "retries": 3,
        "nocheckcertificate": False,
    }
    opts.update(_auth_opts())
    return opts


def extract_video_info(url: str) -> VideoInfo:
    """Estrae i metadata di un singolo video (senza scaricare nulla)."""
    opts = _base_opts()
    opts["noplaylist"] = True
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except yt_dlp.utils.DownloadError as exc:
        raise DownloadError(f"Impossibile analizzare l'URL: {exc}") from exc

    if info is None:
        raise DownloadError("yt-dlp non ha restituito informazioni per questo URL")

    return VideoInfo(
        id=str(info.get("id")),
        title=str(info.get("title") or "Unknown Title"),
        uploader=str(info.get("uploader") or info.get("channel") or ""),
        duration=info.get("duration"),
        thumbnail=str(info.get("thumbnail") or ""),
        webpage_url=str(info.get("webpage_url") or url),
        raw=info,
    )


def extract_playlist_info(url: str, limit: int = 200) -> PlaylistInfo:
    """Estrae l'elenco (flat, veloce) delle entry di una playlist, senza
    risolvere i metadata completi di ogni video: quelli verranno estratti
    singolarmente al momento del download di ciascun item."""
    opts = _base_opts()
    opts["extract_flat"] = "in_playlist"
    opts["playlistend"] = limit

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except yt_dlp.utils.DownloadError as exc:
        raise DownloadError(f"Impossibile analizzare la playlist: {exc}") from exc

    if info is None or "entries" not in info:
        raise DownloadError("L'URL non contiene una playlist valida")

    entries = []
    for idx, entry in enumerate(info.get("entries") or [], start=1):
        if not entry:
            continue
        video_url = entry.get("url") or f"https://www.youtube.com/watch?v={entry.get('id')}"
        entries.append(
            PlaylistEntry(
                id=str(entry.get("id")),
                title=str(entry.get("title") or "Unknown Title"),
                url=video_url,
                index=idx,
            )
        )

    return PlaylistInfo(
        id=str(info.get("id") or ""),
        title=str(info.get("title") or "Playlist"),
        entries=entries,
    )


def download_audio(
    url: str,
    output_dir: str,
    filename_stem: str,
    progress_hook: Optional[ProgressHook] = None,
) -> tuple[str, VideoInfo]:
    """
    Scarica SOLO la traccia audio con la miglior qualita' sorgente
    disponibile, in un formato contenitore nativo (niente re-encode qui:
    la conversione al formato finale e' un passo separato, vedi
    backend/library o backend/metadata). Ritorna (path_file_scaricato, info).
    """
    outtmpl = f"{output_dir}/{filename_stem}.%(ext)s"

    hooks = [progress_hook] if progress_hook else []

    opts = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "format": "bestaudio/best",
        "outtmpl": outtmpl,
        "writethumbnail": True,
        "socket_timeout": 30,
        "retries": 5,
        "fragment_retries": 5,
        "progress_hooks": hooks,
        "postprocessors": [],  # nessuna conversione qui: la fa ffmpeg a valle
    }
    opts.update(_auth_opts())

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
    except yt_dlp.utils.DownloadError as exc:
        raise DownloadError(f"Download fallito: {exc}") from exc

    if info is None:
        raise DownloadError("yt-dlp non ha restituito informazioni dopo il download")

    downloaded_path = ydl.prepare_filename(info)

    video_info = VideoInfo(
        id=str(info.get("id")),
        title=str(info.get("title") or "Unknown Title"),
        uploader=str(info.get("uploader") or info.get("channel") or ""),
        duration=info.get("duration"),
        thumbnail=str(info.get("thumbnail") or ""),
        webpage_url=str(info.get("webpage_url") or url),
        raw=info,
    )
    return downloaded_path, video_info
