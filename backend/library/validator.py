"""
Validazione del file audio PRIMA dell'inserimento definitivo in libreria.
Usa ffprobe (mai ffmpeg per la validazione: e' piu' leggero e read-only).
"""
from __future__ import annotations

import json
from pathlib import Path

from backend.security.subprocess_utils import SubprocessError, run_subprocess

_EXPECTED_CODECS = {
    "m4a": {"aac"},
    "mp3": {"mp3"},
    "flac": {"flac"},
}


class ValidationError(RuntimeError):
    pass


async def validate_audio_file(file_path: str, expected_format: str) -> dict:
    """Verifica esistenza, dimensione > 0, e che ffprobe riconosca un
    codec audio coerente col formato atteso. Ritorna i dati ffprobe."""
    path = Path(file_path)
    if not path.exists():
        raise ValidationError(f"File non trovato: {file_path}")
    if path.stat().st_size <= 0:
        raise ValidationError(f"File vuoto: {file_path}")

    cmd = [
        "ffprobe", "-v", "error",
        "-print_format", "json",
        "-show_format", "-show_streams",
        str(path),
    ]
    try:
        result = await run_subprocess(cmd, timeout=60)
    except SubprocessError as exc:
        raise ValidationError(f"ffprobe fallito: {exc}") from exc

    try:
        probe = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ValidationError(f"Output ffprobe non valido: {exc}") from exc

    audio_streams = [s for s in probe.get("streams", []) if s.get("codec_type") == "audio"]
    if not audio_streams:
        raise ValidationError("Nessuno stream audio trovato nel file")

    codec = audio_streams[0].get("codec_name", "")
    expected = _EXPECTED_CODECS.get(expected_format, set())
    if expected and codec not in expected:
        raise ValidationError(f"Codec inatteso: {codec} (atteso uno tra {expected})")

    duration = float(probe.get("format", {}).get("duration", 0) or 0)
    if duration <= 0:
        raise ValidationError("Durata audio non valida (0 secondi)")

    return probe


def validate_cover_file(cover_path: str) -> None:
    path = Path(cover_path)
    if not path.exists() or path.stat().st_size <= 0:
        raise ValidationError(f"Cover non valida: {cover_path}")
