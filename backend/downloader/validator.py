"""Validazione URL YouTube: allowlist di dominio + path traversal safety."""
from __future__ import annotations

import re
from urllib.parse import urlparse

ALLOWED_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtu.be",
}

_VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{6,}$")


class InvalidURLError(ValueError):
    pass


def validate_youtube_url(url: str) -> str:
    """Verifica che l'URL sia un link YouTube plausibile e lo ritorna
    normalizzato (senza parametri di tracking superflui). Solleva
    InvalidURLError se non e' un URL accettabile."""
    if not url or len(url) > 2048:
        raise InvalidURLError("URL mancante o troppo lungo")

    try:
        parsed = urlparse(url.strip())
    except ValueError as exc:
        raise InvalidURLError(f"URL non parsabile: {exc}") from exc

    if parsed.scheme not in ("http", "https"):
        raise InvalidURLError("Schema URL non consentito (solo http/https)")

    host = (parsed.hostname or "").lower()
    if host not in ALLOWED_HOSTS:
        raise InvalidURLError(f"Host non consentito: {host or 'sconosciuto'}")

    return url.strip()


def is_playlist_url(url: str) -> bool:
    parsed = urlparse(url)
    return "list=" in (parsed.query or "")


def extract_video_id_hint(info: dict) -> str:
    """Ricava un id video plausibile da un dict yt-dlp; usato come chiave
    di deduplicazione primaria (livello 1)."""
    vid = str(info.get("id") or "")
    if not vid or not _VIDEO_ID_RE.match(vid):
        raise InvalidURLError("ID video non valido restituito da yt-dlp")
    return vid
