"""
Metadata normalization: unisce (in ordine di priorita' decrescente)

  1. correzioni manuali dell'utente (dalla UI, prima del download)
  2. content analysis del titolo (parser.py)
  3. dati grezzi yt-dlp (video/playlist info)

in un set di tag finale coerente con le convenzioni Jellyfin, e decide
Album Artist / Various Artists per gestire correttamente compilation.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from backend.downloader.ytdlp_client import VideoInfo
from backend.metadata.parser import build_artist_credit, parse_title


@dataclass
class TrackMetadata:
    title: str = "Unknown Title"
    artist: str = "Unknown Artist"
    album_artist: str = ""
    album: str = ""
    track_number: Optional[int] = None
    disc_number: Optional[int] = None
    year: Optional[int] = None
    genre: str = ""
    composer: str = ""
    comment: str = ""
    featured_artists: list[str] = field(default_factory=list)
    is_compilation: bool = False
    is_single: bool = True  # nessun album affidabile -> finisce in Artist/Singles


def normalize_metadata(
    video_info: VideoInfo,
    *,
    playlist_title: str | None = None,
    playlist_index: int | None = None,
    user_overrides: dict | None = None,
) -> TrackMetadata:
    overrides = user_overrides or {}

    parsed = parse_title(video_info.title, channel_name=video_info.uploader)

    # Artist: preferenza a override utente, poi parsing, poi canale YouTube
    # come ultima risorsa (mai lasciato vuoto in libreria).
    primary_artist = (
        overrides.get("artist")
        or parsed.artist
        or video_info.uploader
        or "Unknown Artist"
    )
    title = overrides.get("title") or parsed.title or video_info.title

    featured = parsed.featured_artists or []
    artist_credit = overrides.get("artist") and primary_artist or build_artist_credit(primary_artist, featured)

    # Album: se l'utente non lo specifica non lo inventiamo. Una playlist
    # NON e' automaticamente un album: e' solo una possibile sorgente di
    # metadata quando l'utente lo conferma esplicitamente (vedi API).
    album = overrides.get("album", "")
    album_artist = overrides.get("album_artist", "")

    is_compilation = bool(overrides.get("is_compilation", False))
    if is_compilation:
        album_artist = "Various Artists"
    elif not album_artist and album:
        # Album presente ma senza Album Artist esplicito -> usa l'artista
        # principale (senza i featuring) per evitare artisti duplicati
        # nella vista "Album" di Jellyfin.
        album_artist = primary_artist

    track_number = overrides.get("track_number")
    if track_number is None and playlist_index is not None and album:
        # Numeriamo per posizione in playlist SOLO se l'utente ha
        # confermato che la playlist rappresenta un album/raccolta.
        track_number = playlist_index

    year = overrides.get("year")
    if year is None:
        upload_date = (video_info.raw or {}).get("upload_date")  # YYYYMMDD
        if upload_date and len(str(upload_date)) == 8:
            year = int(str(upload_date)[:4])

    genre = overrides.get("genre", "")
    composer = overrides.get("composer", "")

    return TrackMetadata(
        title=title.strip() or "Unknown Title",
        artist=artist_credit.strip() or "Unknown Artist",
        album_artist=(album_artist or primary_artist).strip(),
        album=album.strip(),
        track_number=track_number,
        disc_number=overrides.get("disc_number"),
        year=year,
        genre=genre,
        composer=composer,
        comment=f"Ingested from {video_info.webpage_url}",
        featured_artists=featured,
        is_compilation=is_compilation,
        is_single=not bool(album.strip()),
    )
