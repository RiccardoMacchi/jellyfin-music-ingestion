"""
Costruzione del path finale nella libreria, pensata per il music library
scanner di Jellyfin.

Convenzioni Jellyfin seguite:
- La directory di primo livello sotto /music e' l'ALBUM ARTIST (non
  l'artista del singolo brano): questo evita che Jellyfin crei artisti
  duplicati quando un brano ha featuring diversi.
- Gli album vivono in <AlbumArtist>/<Album>/.
- Le compilation (Various Artists) vivono sotto "Various Artists" come
  album artist, cosi' Jellyfin le riconosce come raccolte.
- I brani senza un album affidabile finiscono in <Artist>/Singles/, ma
  mantengono comunque i tag Artist/Album quando disponibili, cosi' restano
  comunque agganciabili se l'utente in futuro li riorganizza in un album.
"""
from __future__ import annotations

from pathlib import Path

from backend.config import settings
from backend.library.filename import build_track_filename, sanitize_path_component
from backend.metadata.normalizer import TrackMetadata


def build_library_path(metadata: TrackMetadata, audio_ext: str) -> tuple[str, str]:
    """Ritorna (file_path_assoluto, cover_path_assoluto) sotto MUSIC_DIR."""
    root = Path(settings.music_dir)

    album_artist = sanitize_path_component(metadata.album_artist or metadata.artist, "Unknown Artist")

    if metadata.is_single:
        artist_dir_name = sanitize_path_component(metadata.artist, "Unknown Artist")
        album_dir = root / artist_dir_name / "Singles"
        cover_path = ""  # i singoli non hanno una cover.jpg di album condivisa
    else:
        album_name = sanitize_path_component(metadata.album, "Unknown Album")
        album_dir = root / album_artist / album_name
        cover_path = str(album_dir / "cover.jpg")

    filename = build_track_filename(metadata.track_number, metadata.title, audio_ext)
    file_path = album_dir / filename

    return str(file_path), cover_path
