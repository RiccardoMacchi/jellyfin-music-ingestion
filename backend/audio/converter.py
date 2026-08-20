"""
Audio conversion (FFmpeg).

Regola guida del progetto: "evita transcoding multipli". YouTube fornisce
quasi sempre l'audio migliore come Opus/WebM, e talvolta come AAC/M4A nativo
(itag 140). Per questo:

- Se il formato target e' m4a E la sorgente e' gia' AAC, facciamo un puro
  REMUX (stream copy, nessun re-encode: qualita' identica, operazione
  quasi istantanea).
- In tutti gli altri casi (target mp3/flac, o sorgente Opus/altro) serve un
  encode reale: lo facciamo in UN solo passaggio diretto verso il formato
  finale, mai sorgente -> intermedio -> finale.
"""
from __future__ import annotations

import json
from pathlib import Path

from backend.config import settings
from backend.security.subprocess_utils import SubprocessError, run_subprocess

# Codec ffmpeg da usare per ciascun formato contenitore target
_ENCODERS = {
    "m4a": ["-c:a", "aac", "-b:a", settings.audio_bitrate],
    "mp3": ["-c:a", "libmp3lame", "-b:a", settings.audio_bitrate, "-write_id3v2", "0"],
    "flac": ["-c:a", "flac"],  # lossless: bitrate non si applica
}


class ConversionError(RuntimeError):
    pass


async def _probe_source_codec(source_path: str) -> str:
    cmd = [
        "ffprobe", "-v", "error", "-select_streams", "a:0",
        "-show_entries", "stream=codec_name",
        "-of", "json", source_path,
    ]
    try:
        result = await run_subprocess(cmd, timeout=60)
    except SubprocessError as exc:
        raise ConversionError(f"Impossibile analizzare l'audio sorgente: {exc}") from exc
    data = json.loads(result.stdout)
    streams = data.get("streams", [])
    if not streams:
        raise ConversionError("Nessuno stream audio nel file sorgente")
    return streams[0].get("codec_name", "")


async def convert_audio(source_path: str, dest_path: str, target_format: str | None = None) -> str:
    """Converte `source_path` nel formato target (default: settings.audio_format)
    scrivendo `dest_path`. Ritorna dest_path. Nessun tag viene scritto qui:
    il tagging e' un passo separato (vedi backend/metadata/tagger.py) cosi'
    la conversione resta pura e testabile in isolamento."""
    target_format = target_format or settings.audio_format
    if target_format not in _ENCODERS:
        raise ConversionError(f"Formato audio non supportato: {target_format}")

    Path(dest_path).parent.mkdir(parents=True, exist_ok=True)
    source_codec = await _probe_source_codec(source_path)

    if target_format == "m4a" and source_codec == "aac":
        codec_args = ["-c:a", "copy"]
    else:
        codec_args = _ENCODERS[target_format]

    cmd = [
        "ffmpeg", "-y",
        "-i", source_path,
        "-vn",  # niente stream video/immagine embedded: la cover si gestisce a parte
        *codec_args,
        dest_path,
    ]

    try:
        await run_subprocess(cmd, timeout=settings.subprocess_timeout_seconds)
    except SubprocessError as exc:
        raise ConversionError(f"Conversione audio fallita: {exc}") from exc

    if not Path(dest_path).exists() or Path(dest_path).stat().st_size == 0:
        raise ConversionError("Il file convertito e' vuoto o mancante")

    return dest_path
