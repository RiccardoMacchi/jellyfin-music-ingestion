"""
Filename normalization per Linux/Jellyfin.

Obiettivo: rimuovere solo cio' che romperebbe il filesystem o la lettura di
Jellyfin, senza toccare Unicode legittimo (es. "Beyonce" con accento resta
tale e quale, gli emoji/caratteri non ASCII non vengono trascritti).
"""
from __future__ import annotations

import re
import unicodedata

# Caratteri vietati o problematici su Linux/filesystem/Jellyfin
_FORBIDDEN_CHARS = r'/\:*?"<>|'
_FORBIDDEN_RE = re.compile("[" + re.escape(_FORBIDDEN_CHARS) + "]")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
_MULTI_SPACE_RE = re.compile(r"\s{2,}")

MAX_COMPONENT_LENGTH = 180  # margine di sicurezza sotto i 255 byte tipici


def sanitize_path_component(value: str, fallback: str = "Unknown") -> str:
    """Sanitizza UN singolo componente di path (nome file o directory).
    Non tocca i separatori: va chiamata per ogni segmento, mai sull'intero
    path in un colpo solo."""
    if not value:
        return fallback

    # Normalizza la forma Unicode (NFC) ma non trascrive/ascii-fica nulla:
    # "Beyoncé" resta "Beyoncé".
    value = unicodedata.normalize("NFC", value)

    value = _CONTROL_RE.sub("", value)
    value = _FORBIDDEN_RE.sub("-", value)
    value = value.replace("..", ".")  # niente path traversal via nome file
    value = _MULTI_SPACE_RE.sub(" ", value).strip(" .")

    if not value:
        return fallback

    # Tronca per byte-length (UTF-8), non per numero di caratteri, per
    # restare sotto i limiti tipici del filesystem anche con Unicode multi-byte.
    encoded = value.encode("utf-8")
    if len(encoded) > MAX_COMPONENT_LENGTH:
        encoded = encoded[:MAX_COMPONENT_LENGTH]
        value = encoded.decode("utf-8", errors="ignore").strip()

    return value or fallback


def build_track_filename(track_number: int | None, title: str, ext: str) -> str:
    title_part = sanitize_path_component(title, fallback="Untitled")
    if track_number:
        return f"{track_number:02d} - {title_part}.{ext}"
    return f"{title_part}.{ext}"
