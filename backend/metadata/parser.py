"""
Content analysis: prova a ricavare artist/title/feat da un titolo YouTube
grezzo, SENZA inventare informazioni quando il pattern non e' riconoscibile.

Questo modulo non chiama YouTube: lavora solo su stringhe gia' estratte da
yt-dlp (title, uploader/channel).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# Separatori comuni tra artista e titolo nei video musicali YouTube
_ARTIST_TITLE_SEPARATORS = [" - ", " – ", " — ", " | "]

# Pattern per "feat."/"ft."/"featuring" (case-insensitive), sia dentro
# parentesi che senza.
_FEAT_RE = re.compile(
    r"""[\(\[]?\s*
        (?:feat\.?|ft\.?|featuring)\s+
        (?P<featured>[^)\]]+?)
        \s*[\)\]]?$""",
    re.IGNORECASE | re.VERBOSE,
)

# Tag da rimuovere dal titolo perche' non fanno parte del titolo canzone
_NOISE_TAGS_RE = re.compile(
    r"""\s*[\(\[]\s*
        (official\s*(music\s*)?video|official\s*audio|lyric\s*video|lyrics|
         audio|hd|hq|4k|visualizer|mv|explicit|clean|remastered.*?|
         official)
        \s*[\)\]]""",
    re.IGNORECASE | re.VERBOSE,
)


@dataclass
class ParsedTitle:
    artist: str = ""
    title: str = ""
    featured_artists: list[str] | None = None
    confident: bool = False


def strip_noise_tags(raw_title: str) -> str:
    cleaned = _NOISE_TAGS_RE.sub("", raw_title)
    return re.sub(r"\s{2,}", " ", cleaned).strip(" -–—|")


def extract_featured_artists(text: str) -> tuple[str, list[str]]:
    """Rimuove 'feat. X' dal testo e ritorna (testo_pulito, [artisti])."""
    match = _FEAT_RE.search(text)
    if not match:
        return text, []
    featured_raw = match.group("featured")
    featured = [a.strip() for a in re.split(r",|&|\band\b", featured_raw) if a.strip()]
    cleaned = text[: match.start()].strip(" -–—([")
    return cleaned, featured


def parse_title(raw_title: str, channel_name: str = "") -> ParsedTitle:
    """
    Prova a separare "Artist - Title" dal titolo grezzo YouTube.

    Strategia (nessuna invenzione, solo pattern espliciti):
    1. Rimuove tag rumore tipo "(Official Video)".
    2. Cerca un separatore Artist - Title.
    3. Estrae eventuale "feat. X" dal titolo.
    4. Se non trova un separatore affidabile, ritorna confident=False e
       lascia title = titolo ripulito, artist = "" (il chiamante decide
       come gestirlo, es. fallback su channel_name senza forzare nulla).
    """
    cleaned = strip_noise_tags(raw_title)

    for sep in _ARTIST_TITLE_SEPARATORS:
        if sep in cleaned:
            left, right = cleaned.split(sep, 1)
            left, right = left.strip(), right.strip()
            if left and right:
                title_no_feat, featured = extract_featured_artists(right)
                return ParsedTitle(
                    artist=left,
                    title=title_no_feat or right,
                    featured_artists=featured or None,
                    confident=True,
                )

    # Nessun separatore riconosciuto: proviamo solo a togliere un eventuale
    # "feat." dal titolo intero, ma NON assumiamo un artista.
    title_no_feat, featured = extract_featured_artists(cleaned)
    return ParsedTitle(
        artist="",
        title=title_no_feat or cleaned,
        featured_artists=featured or None,
        confident=False,
    )


def build_artist_credit(primary_artist: str, featured_artists: list[str] | None) -> str:
    """Costruisce la stringa Artist da mostrare in tag/UI, es.
    'Artist A feat. Artist B'. Non tocca l'Album Artist (vedi normalizer)."""
    if not featured_artists:
        return primary_artist
    return f"{primary_artist} feat. {', '.join(featured_artists)}"
