"""
Taglio intro/outro di un brano GIA' presente in libreria.

Stesse garanzie dell'ingestion: il file in /music non viene mai scritto
direttamente. Il taglio produce una copia in DOWNLOAD_DIR, a cui vengono
ricopiati tutti i tag (cover inclusa); la copia viene validata con ffprobe
e solo allora sostituisce l'originale con un move atomico. Se qualcosa va
storto l'originale resta intatto.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from backend.audio.converter import trim_audio_file
from backend.config import settings
from backend.library.mover import _is_within, atomic_move
from backend.library.validator import ValidationError, validate_audio_file
from backend.metadata.tagger import copy_tags


async def trim_library_file(file_path: str, trim_start: float, trim_end: float, job_id: int) -> float:
    """Taglia `file_path` (dentro MUSIC_DIR) e ritorna la nuova durata in
    secondi. Solleva ConversionError/TaggingError/ValidationError/MoveError."""
    target = Path(file_path)
    if not _is_within(target, Path(settings.music_dir)):
        raise ValidationError("Il file non si trova nella libreria musicale")
    if not target.exists():
        raise ValidationError(f"File non trovato in libreria: {file_path}")

    ext = target.suffix.lower().lstrip(".")
    tmp_dir = Path(settings.tmp_download_path)
    tmp_dir.mkdir(parents=True, exist_ok=True)
    tmp_path = tmp_dir / f"trim_{job_id}.{ext}"

    try:
        new_duration = await trim_audio_file(str(target), str(tmp_path), trim_start, trim_end)
        await asyncio.to_thread(copy_tags, str(target), str(tmp_path))
        probe = await validate_audio_file(str(tmp_path), ext)
        new_duration = float(probe.get("format", {}).get("duration") or new_duration)
        await asyncio.to_thread(atomic_move, str(tmp_path), str(target))
        return new_duration
    finally:
        tmp_path.unlink(missing_ok=True)
