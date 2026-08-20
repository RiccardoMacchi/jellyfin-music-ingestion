"""
Gestione cover art: normalizzazione dell'immagine scaricata da yt-dlp
(spesso .webp) in un JPEG valido, e policy di scrittura di `cover.jpg`
nella directory dell'album.
"""
from __future__ import annotations

import glob
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from backend.config import settings
from backend.utils.logging import get_logger

logger = get_logger(__name__)

MIN_DIMENSION = 200  # sotto questa soglia consideriamo la thumbnail inutile


class CoverError(RuntimeError):
    pass


def find_downloaded_thumbnail(download_dir: str, filename_stem: str) -> str | None:
    """yt-dlp salva la thumbnail come <stem>.<ext> (webp/jpg/png) accanto
    all'audio quando writethumbnail=True. La cerchiamo per prefisso."""
    matches = glob.glob(f"{download_dir}/{filename_stem}.*")
    for ext in (".webp", ".jpg", ".jpeg", ".png"):
        for m in matches:
            if m.lower().endswith(ext) and not m.lower().endswith((".m4a", ".mp3", ".flac", ".part")):
                return m
    return None


def normalize_to_jpeg(source_path: str, dest_path: str, max_size: int = 1000) -> bytes:
    """Apre l'immagine sorgente (qualunque formato), la valida, la
    ridimensiona (mai upscale) e la salva come JPEG. Ritorna i bytes JPEG
    risultanti (utili per l'embed nei tag)."""
    try:
        with Image.open(source_path) as img:
            img = img.convert("RGB")
            if max(img.size) < MIN_DIMENSION:
                raise CoverError(f"Thumbnail troppo piccola: {img.size}")
            if max(img.size) > max_size:
                img.thumbnail((max_size, max_size), Image.LANCZOS)
            Path(dest_path).parent.mkdir(parents=True, exist_ok=True)
            img.save(dest_path, format="JPEG", quality=90)
    except UnidentifiedImageError as exc:
        raise CoverError(f"File immagine non valido: {exc}") from exc

    return Path(dest_path).read_bytes()


def should_write_cover(target_cover_path: str) -> bool:
    """Applica COVER_POLICY: se esiste gia' una cover nell'album e la
    policy e' 'preserve' (default), non la sovrascrive."""
    exists = Path(target_cover_path).exists()
    if not exists:
        return True
    if settings.cover_policy == "overwrite":
        return True
    logger.info("Cover gia' presente in %s, preservata (COVER_POLICY=preserve)", target_cover_path)
    return False
