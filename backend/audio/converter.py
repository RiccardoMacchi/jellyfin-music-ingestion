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

Taglio intro/outro (trim): sui nuovi download si applica nello stesso
passaggio della conversione. Sui brani gia' in libreria si usa uno stream
copy (`trim_audio_file`): nessun re-encode, quindi nessuna perdita di
qualita' aggiuntiva; la precisione e' quella di un frame audio (~20-30 ms).
"""
from __future__ import annotations

import json
from pathlib import Path

from backend.config import settings
from backend.security.subprocess_utils import SubprocessError, run_subprocess

# Durata minima che deve restare dopo un taglio: evita di produrre file
# vuoti/inutili per un errore di battitura (es. 300 invece di 30).
MIN_REMAINING_SECONDS = 5.0

# Codec ffmpeg da usare per ciascun formato contenitore target
_ENCODERS = {
    "m4a": ["-c:a", "aac", "-b:a", settings.audio_bitrate],
    "mp3": ["-c:a", "libmp3lame", "-b:a", settings.audio_bitrate, "-write_id3v2", "0"],
    "flac": ["-c:a", "flac"],  # lossless: bitrate non si applica
}


class ConversionError(RuntimeError):
    pass


async def _probe_source(source_path: str) -> tuple[str, float]:
    """Ritorna (codec del primo stream audio, durata in secondi o 0)."""
    cmd = [
        "ffprobe", "-v", "error", "-select_streams", "a:0",
        "-show_entries", "stream=codec_name:format=duration",
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
    try:
        duration = float((data.get("format") or {}).get("duration") or 0)
    except (TypeError, ValueError):
        duration = 0.0
    return streams[0].get("codec_name", ""), duration


def _trim_args(duration: float, trim_start: float, trim_end: float) -> list[str]:
    """Argomenti ffmpeg (opzioni di output) per tagliare `trim_start` secondi
    all'inizio e `trim_end` alla fine. Lista vuota se non c'e' nulla da tagliare."""
    trim_start = max(0.0, float(trim_start or 0))
    trim_end = max(0.0, float(trim_end or 0))
    if not trim_start and not trim_end:
        return []
    if duration <= 0:
        raise ConversionError("Durata audio sconosciuta: impossibile applicare il taglio")
    remaining = duration - trim_start - trim_end
    if remaining < MIN_REMAINING_SECONDS:
        raise ConversionError(
            f"Taglio troppo lungo: il brano dura {duration:.0f}s, togliendo "
            f"{trim_start:g}s + {trim_end:g}s resterebbero {max(remaining, 0):.0f}s"
        )
    args: list[str] = []
    if trim_start:
        args += ["-ss", f"{trim_start:.3f}"]
    args += ["-t", f"{remaining:.3f}"]
    return args


async def convert_audio(
    source_path: str,
    dest_path: str,
    target_format: str | None = None,
    *,
    trim_start: float = 0.0,
    trim_end: float = 0.0,
) -> str:
    """Converte `source_path` nel formato target (default: settings.audio_format)
    scrivendo `dest_path`, tagliando opzionalmente `trim_start` secondi
    all'inizio e `trim_end` alla fine. Ritorna dest_path. Nessun tag viene
    scritto qui: il tagging e' un passo separato (vedi
    backend/metadata/tagger.py) cosi' la conversione resta pura e testabile."""
    target_format = target_format or settings.audio_format
    if target_format not in _ENCODERS:
        raise ConversionError(f"Formato audio non supportato: {target_format}")

    Path(dest_path).parent.mkdir(parents=True, exist_ok=True)
    source_codec, duration = await _probe_source(source_path)

    if target_format == "m4a" and source_codec == "aac":
        codec_args = ["-c:a", "copy"]
    else:
        codec_args = _ENCODERS[target_format]

    cmd = [
        "ffmpeg", "-y",
        "-i", source_path,
        "-vn",  # niente stream video/immagine embedded: la cover si gestisce a parte
        *_trim_args(duration, trim_start, trim_end),
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


async def trim_audio_file(source_path: str, dest_path: str, trim_start: float, trim_end: float) -> float:
    """Taglia un file audio GIA' nel formato finale scrivendo `dest_path` con
    la stessa estensione, senza re-encode (stream copy). I tag NON vengono
    copiati qui (vedi tagger.copy_tags). Ritorna la nuova durata in secondi."""
    _, duration = await _probe_source(source_path)
    trim_args = _trim_args(duration, trim_start, trim_end)
    if not trim_args:
        raise ConversionError("Nessun taglio richiesto")

    Path(dest_path).parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y",
        "-i", source_path,
        "-map", "0:a:0",  # solo l'audio: la cover embedded la ricopia il tagger
        *trim_args,
        "-c:a", "copy",
        dest_path,
    ]
    try:
        await run_subprocess(cmd, timeout=settings.subprocess_timeout_seconds)
    except SubprocessError as exc:
        raise ConversionError(f"Taglio audio fallito: {exc}") from exc

    if not Path(dest_path).exists() or Path(dest_path).stat().st_size == 0:
        raise ConversionError("Il file tagliato e' vuoto o mancante")

    return duration - max(0.0, trim_start) - max(0.0, trim_end)
