"""
Riconoscimento automatico del genere di un brano a partire da artista e
titolo, interrogando servizi pubblici GRATUITI e senza API key:

1. Deezer: ottima copertura (anche musica italiana), generi larghi e stabili
   assegnati all'album -> perfetti per playlist per genere.
2. MusicBrainz (fallback): generi votati dalla comunita' sulla registrazione
   o, se assenti, sull'artista. Richiede max 1 richiesta/secondo e uno
   User-Agent identificativo: entrambi rispettati qui.

Regola del progetto: mai inventare. Se nessun provider trova una
corrispondenza affidabile (artista coerente + titolo simile) il genere resta
vuoto. Un errore di rete non fa mai fallire un download.
"""
from __future__ import annotations

import asyncio
import re
import time
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Optional

import httpx

from backend.config import settings
from backend.genre.normalize import canonical_genre, is_meaningful
from backend.utils.logging import get_logger

logger = get_logger(__name__)

DEEZER_API = "https://api.deezer.com"
MUSICBRAINZ_API = "https://musicbrainz.org/ws/2"

_HTTP_TIMEOUT = 10
_MIN_TITLE_SIMILARITY = 0.6
_MIN_MB_SCORE = 80

# MusicBrainz: al massimo 1 richiesta al secondo per client.
_MB_MIN_INTERVAL_SECONDS = 1.1
_mb_lock = asyncio.Lock()
_mb_last_call = 0.0


@dataclass
class GenreResult:
    genre: str          # genere canonico (vedi normalize.py)
    source: str         # "deezer" | "musicbrainz"
    raw: str = ""       # etichetta originale del provider


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------

def _fold(text: str) -> str:
    """Lowercase senza accenti/punteggiatura, per confronti robusti."""
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"[^\w\s]", " ", text.lower())
    return re.sub(r"\s+", " ", text).strip()


def _strip_version(title: str) -> str:
    """'Song (Remix) [Live]' -> 'Song': il genere e' quello del brano base."""
    return re.sub(r"\s*[\(\[][^\)\]]*[\)\]]", "", title).strip() or title


def _artist_matches(wanted: str, found: str) -> bool:
    a, b = _fold(wanted), _fold(found)
    if not a or not b:
        return False
    if a == b or SequenceMatcher(None, a, b).ratio() >= 0.85:
        return True
    # "Artist A" vs "Artist A & Artist B": contenimento a parole intere, e mai
    # per nomi cortissimi (evita che "A" combaci con qualunque artista).
    short, long_ = sorted((a, b), key=len)
    return len(short) >= 3 and f" {short} " in f" {long_} "


def _title_similarity(wanted: str, found: str) -> float:
    a, b = _fold(_strip_version(wanted)), _fold(_strip_version(found))
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    return SequenceMatcher(None, a, b).ratio()


def primary_artist(artist: str, album_artist: str = "") -> str:
    """Artista principale da usare nelle ricerche: niente featuring, e
    niente 'Various Artists' (non e' un artista vero)."""
    if album_artist and album_artist.strip().lower() != "various artists":
        return album_artist.strip()
    return re.split(r"\s+(?:feat\.?|ft\.?|featuring)\s+", artist or "", flags=re.IGNORECASE)[0].strip()


def _pick_genre(labels: list[str]) -> Optional[tuple[str, str]]:
    """Primo genere significativo (le liste arrivano gia' ordinate per
    rilevanza) -> (canonico, originale)."""
    for label in labels:
        if label and is_meaningful(label):
            genre = canonical_genre(label)
            if genre:
                return genre, label
    return None


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

async def _get_json(url: str, params: dict | None = None, headers: dict | None = None) -> dict:
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT, follow_redirects=True) as client:
        response = await client.get(url, params=params, headers=headers)
        if response.status_code in (429, 503):
            # MusicBrainz risponde 503 quando si supera il suo rate limit
            # (anche globale): un solo nuovo tentativo dopo una pausa.
            await asyncio.sleep(2)
            response = await client.get(url, params=params, headers=headers)
        response.raise_for_status()
        return response.json()


def _mb_headers() -> dict:
    contact = (settings.musicbrainz_contact or "").strip() or "https://github.com/"
    return {
        "User-Agent": f"JellyfinMusicIngestion/{settings.app_version} ( {contact} )",
        "Accept": "application/json",
    }


async def _mb_get(path: str, params: dict) -> dict:
    global _mb_last_call
    async with _mb_lock:
        wait = _MB_MIN_INTERVAL_SECONDS - (time.monotonic() - _mb_last_call)
        if wait > 0:
            await asyncio.sleep(wait)
        try:
            return await _get_json(f"{MUSICBRAINZ_API}/{path}", {**params, "fmt": "json"}, _mb_headers())
        finally:
            _mb_last_call = time.monotonic()


def _lucene_quote(text: str) -> str:
    return '"' + re.sub(r'(["\\])', r"\\\1", text) + '"'


# ---------------------------------------------------------------------------
# Provider: Deezer
# ---------------------------------------------------------------------------

async def _deezer_lookup(artist: str, title: str) -> Optional[GenreResult]:
    headers = {"Accept-Language": "en"}  # nomi dei generi in inglese, stabili
    base_title = _strip_version(title)
    queries = [
        f'artist:"{artist}" track:"{base_title}"',
        f"{artist} {base_title}",
    ]
    for query in queries:
        data = await _get_json(f"{DEEZER_API}/search", {"q": query, "limit": 10}, headers)
        if "error" in data:
            raise RuntimeError(f"Deezer: {data['error']}")

        candidates = []
        for track in data.get("data") or []:
            if not _artist_matches(artist, (track.get("artist") or {}).get("name", "")):
                continue
            similarity = _title_similarity(title, track.get("title", ""))
            if similarity >= _MIN_TITLE_SIMILARITY and (track.get("album") or {}).get("id"):
                candidates.append((similarity, track))
        candidates.sort(key=lambda c: c[0], reverse=True)

        # Alcuni singoli su Deezer non hanno generi: proviamo i primi album.
        for _, track in candidates[:3]:
            album = await _get_json(f"{DEEZER_API}/album/{track['album']['id']}", headers=headers)
            labels = [g.get("name", "") for g in ((album.get("genres") or {}).get("data") or [])]
            picked = _pick_genre(labels)
            if picked:
                return GenreResult(genre=picked[0], source="deezer", raw=picked[1])
    return None


# ---------------------------------------------------------------------------
# Provider: MusicBrainz
# ---------------------------------------------------------------------------

def _sorted_genre_names(entity: dict) -> list[str]:
    genres = sorted(entity.get("genres") or [], key=lambda g: g.get("count", 0), reverse=True)
    return [g.get("name", "") for g in genres]


async def _musicbrainz_lookup(artist: str, title: str) -> Optional[GenreResult]:
    query = f"recording:{_lucene_quote(_strip_version(title))} AND artist:{_lucene_quote(artist)}"
    data = await _mb_get("recording", {"query": query, "limit": 10})

    for rec in data.get("recordings") or []:
        if int(rec.get("score", 0)) < _MIN_MB_SCORE:
            continue
        credits = rec.get("artist-credit") or []
        credit_name = "".join(c.get("name", "") + c.get("joinphrase", "") for c in credits)
        if not _artist_matches(artist, credit_name) or _title_similarity(title, rec.get("title", "")) < _MIN_TITLE_SIMILARITY:
            continue

        detail = await _mb_get(f"recording/{rec['id']}", {"inc": "genres"})
        picked = _pick_genre(_sorted_genre_names(detail))
        if not picked and credits and (credits[0].get("artist") or {}).get("id"):
            artist_detail = await _mb_get(f"artist/{credits[0]['artist']['id']}", {"inc": "genres"})
            picked = _pick_genre(_sorted_genre_names(artist_detail))
        if picked:
            return GenreResult(genre=picked[0], source="musicbrainz", raw=picked[1])
        return None  # match trovato ma senza generi: non tentiamo altri omonimi
    return None


# ---------------------------------------------------------------------------
# API pubblica
# ---------------------------------------------------------------------------

_PROVIDERS = {
    "deezer": _deezer_lookup,
    "musicbrainz": _musicbrainz_lookup,
}


async def detect_genre(artist: str, title: str) -> Optional[GenreResult]:
    """Ritorna il genere del brano o None. Non solleva mai: gli errori dei
    provider vengono loggati e si passa al successivo."""
    artist, title = (artist or "").strip(), (title or "").strip()
    if not artist or not title or artist.lower() == "unknown artist":
        return None

    for name in [p.strip() for p in settings.genre_providers.split(",") if p.strip()]:
        provider = _PROVIDERS.get(name)
        if provider is None:
            logger.warning("Provider di genere sconosciuto: %s", name)
            continue
        try:
            result = await provider(artist, title)
        except Exception as exc:
            logger.warning("Ricerca genere su %s fallita per '%s - %s': %s", name, artist, title, exc)
            continue
        if result:
            logger.info("Genere '%s' (%s, '%s') per '%s - %s'", result.genre, name, result.raw, artist, title)
            return result
    return None
