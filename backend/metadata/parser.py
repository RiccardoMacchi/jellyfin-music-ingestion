"""
Content analysis: prova a ricavare artist/title/feat da un titolo YouTube
grezzo, SENZA inventare informazioni quando il pattern non e' riconoscibile.

Questo modulo non chiama YouTube: lavora solo su stringhe gia' estratte da
yt-dlp (title, uploader/channel).

Pulizia del "rumore" tipico dei titoli YouTube:
- gruppi tra parentesi ( ) [ ] 【 】 { } che contengono parole come
  "Official Video", "Lyrics", "Video Ufficiale", "4K", "Prod. by ..." ->
  rimossi; se il gruppo contiene ANCHE un'indicazione di versione
  ("Official Live Video", "Official Remix") resta solo la versione: "(Live)";
- segmenti finali dopo " | ", " - ", " // " fatti solo di rumore
  ("Artist - Song | Official Music Video") -> rimossi;
- frasi di rumore non tra parentesi in coda al titolo, hashtag, emoji;
- le indicazioni di versione (Remix, Live, Acoustic, Extended Mix...)
  NON sono rumore: distinguono brani diversi e restano nel titolo.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# Separatori comuni tra artista e titolo nei video musicali YouTube
_ARTIST_TITLE_SEPARATORS = [" - ", " – ", " — ", " | ", " ~ "]

# Separatori dietro cui spesso c'e' solo rumore ("Song | Official Video")
_TRAILING_SEGMENT_SEPARATORS_RE = re.compile(r"\s+(?:\||//|-|–|—|~)\s+")

# Parole/frasi che, da sole, non fanno mai parte del titolo di una canzone.
# Ordinate dalle piu' lunghe alle piu' corte: l'alternanza regex prende la
# prima che combacia, cosi' "official music video" vince su "official".
_NOISE_PHRASES = [
    r"official\s+(?:music\s+|lyrics?\s+|hd\s+|4k\s+)?(?:video|videoclip|clip|audio|visuali[sz]er)",
    r"(?:music|lyrics?|vertical)\s+video", r"lyric\s+visuali[sz]er",
    r"video\s*clip\s+ufficiale", r"video\s+ufficiale", r"audio\s+ufficiale",
    r"videoclip", r"video\s+oficial", r"audio\s+oficial", r"clip\s+officiel",
    r"vid[eé]o\s+officielle", r"offizielles\s+(?:musik)?video",
    r"prod(?:\.\s*|uced\s+|\s+)(?:by\s+)?[^)\]】}|]*",
    r"free\s+download", r"out\s+now", r"full\s+(?:song|audio|album|hd)",
    r"audio\s+only", r"ncs\s+release", r"color\s+coded(?:\s+lyrics)?",
    r"(?:eng|english|ita|esp)\s+sub(?:s|titles)?", r"sub\s+(?:español|ita|eng)",
    r"con\s+testo", r"with\s+lyrics", r"lyrics?", r"testo", r"letra", r"paroles",
    r"official", r"ufficiale", r"oficial", r"officiel",
    r"visuali[sz]er", r"premiere", r"vevo", r"audio", r"video",
    r"explicit", r"clean", r"uncensored", r"remaster(?:ed)?(?:\s+\d{4})?",
    r"\d{4}\s+remaster(?:ed)?",
    r"hd", r"hq", r"4k", r"8k", r"uhd", r"\d{3,4}p", r"360°?", r"m/?v",
]
_NOISE_TOKEN_RE = re.compile(
    r"(?<![\w])(?:" + "|".join(_NOISE_PHRASES) + r")(?![\w])",
    re.IGNORECASE,
)
# Tra parentesi e' rumore anche un anno da solo: "(2019)". Fuori dalle
# parentesi no: "Prince - 1999" e' un titolo vero.
_BRACKET_NOISE_TOKEN_RE = re.compile(
    r"(?<![\w])(?:" + "|".join(_NOISE_PHRASES + [r"(?:19|20)\d{2}"]) + r")(?![\w])",
    re.IGNORECASE,
)

# Frasi di rumore "forti": un gruppo tra parentesi che ne contiene una e' da
# rimuovere per intero anche se contiene altro, es.
# "(Official Video - Sanremo 2021)", "[Video Ufficiale | 4K]".
_STRONG_NOISE_RE = re.compile(
    r"(?<![\w])(?:official\s+(?:music\s+|lyrics?\s+|hd\s+|4k\s+)?(?:video|videoclip|clip|audio|visuali[sz]er)|"
    r"(?:music|lyrics?)\s+video|video\s*clip\s+ufficiale|video\s+ufficiale|audio\s+ufficiale|"
    r"video\s+oficial|audio\s+oficial|clip\s+officiel|vid[eé]o\s+officielle)(?![\w])",
    re.IGNORECASE,
)

# Indicazioni di versione: rendono il brano diverso dall'originale, vanno
# conservate anche se nello stesso gruppo c'e' rumore.
_VERSION_RE = re.compile(
    r"\b(?:live|remix|rmx|acoustic|acustica|unplugged|cover|version|versione|"
    r"edit|mix|instrumental|strumentale|karaoke|demo|reprise|sped\s*up|slowed|"
    r"reverb|nightcore|bootleg|mashup|rework|vip)\b",
    re.IGNORECASE,
)

# Gruppo tra parentesi di qualsiasi tipo (non annidato)
_BRACKET_GROUP_RE = re.compile(r"\s*([\(\[【{])([^\(\)\[\]【】{}]*)([\)\]】}])")

# Frasi di rumore NON tra parentesi in coda al titolo
# ("Artist - Song Official Video"). Solo frasi multi-parola, inequivocabili:
# "audio" o "video" da soli potrebbero far parte del titolo vero.
_TRAILING_NOISE_RE = re.compile(
    r"\s+(?:official\s+(?:music\s+|lyrics?\s+)?(?:video|audio|videoclip|visuali[sz]er)|"
    r"(?:music|lyrics?)\s+video|video\s*clip\s+ufficiale|video\s+ufficiale|"
    r"audio\s+ufficiale|video\s+oficial|clip\s+officiel)\s*$",
    re.IGNORECASE,
)

_HASHTAG_RE = re.compile(r"\s*#[\w-]+")
# Emoji e simboli pittografici (blocchi Unicode principali)
_EMOJI_RE = re.compile(
    "[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U0001F900-\U0001F9FF️‍]+"
)

# feat./ft./featuring tra parentesi in QUALSIASI posizione: "Song (feat. B) [Remix]"
_FEAT_BRACKET_RE = re.compile(
    r"\s*[\(\[]\s*(?:feat\.?|ft\.?|featuring)\s+(?P<featured>[^)\]]+?)\s*[\)\]]",
    re.IGNORECASE,
)
# feat. senza parentesi: va fino alla fine del testo
_FEAT_TRAILING_RE = re.compile(
    r"\s+(?:feat\.?|ft\.?|featuring)\s+(?P<featured>.+?)\s*$",
    re.IGNORECASE,
)

# 'Artist "Song"' (senza separatore, titolo tra virgolette)
_QUOTED_TITLE_RE = re.compile(r"^(?P<artist>[^\"“”]+?)\s+[\"“](?P<title>[^\"“”]+)[\"”]\s*$")

_QUOTES = "\"'“”‘’«»"

# Suffissi dei canali YouTube che non fanno parte del nome artista
_CHANNEL_TOPIC_RE = re.compile(r"\s+-\s+(?:topic|argomento|tema|thème|thema)$", re.IGNORECASE)
_CHANNEL_SUFFIX_RE = re.compile(r"(?:\s*VEVO|\s+(?:official|ufficiale)(?:\s+channel)?)$", re.IGNORECASE)


@dataclass
class ParsedTitle:
    artist: str = ""
    title: str = ""
    featured_artists: list[str] | None = None
    confident: bool = False


def _tidy(text: str) -> str:
    text = re.sub(r"\s{2,}", " ", text)
    return text.strip(" -–—|~/:·•,")


def _is_pure_noise(text: str, noise_re: re.Pattern = _NOISE_TOKEN_RE) -> bool:
    """True se `text` e' composto SOLO da rumore (+ punteggiatura)."""
    if not text.strip():
        return True
    remainder = noise_re.sub("", text)
    return not re.sub(r"[\W_]+", "", remainder)


def _clean_bracket_group(match: re.Match) -> str:
    opening, content, closing = match.group(1), match.group(2), match.group(3)
    # I featuring vengono estratti piu' avanti: non sono rumore.
    if re.match(r"\s*(?:feat\.?|ft\.?|featuring)\s", content, re.IGNORECASE):
        return match.group(0)
    if _is_pure_noise(content, _BRACKET_NOISE_TOKEN_RE):
        return ""
    if _STRONG_NOISE_RE.search(content) and not _VERSION_RE.search(content):
        return ""
    if _NOISE_TOKEN_RE.search(content) and _VERSION_RE.search(content):
        # "(Official Live Video)" -> "(Live)", "[Official Remix]" -> "[Remix]"
        reduced = _tidy(_NOISE_TOKEN_RE.sub("", content))
        if reduced:
            return f" [{reduced}]" if opening == "[" else f" ({reduced})"
    return match.group(0)


def strip_noise_tags(raw_title: str) -> str:
    text = _EMOJI_RE.sub(" ", raw_title)
    text = _HASHTAG_RE.sub("", text)
    text = _BRACKET_GROUP_RE.sub(_clean_bracket_group, text)

    # Segmenti finali fatti solo di rumore: "Song | Official Video",
    # "Song - Official Music Video", "Song // Lyrics". Togliamo dal fondo
    # finche' l'ultimo segmento e' rumore (mai il primo: resta almeno uno).
    parts = _TRAILING_SEGMENT_SEPARATORS_RE.split(text)
    seps = _TRAILING_SEGMENT_SEPARATORS_RE.findall(text)
    while len(parts) > 1 and _is_pure_noise(parts[-1]):
        parts.pop()
        seps.pop()
    text = parts[0] + "".join(s + p for s, p in zip(seps, parts[1:]))

    text = _TRAILING_NOISE_RE.sub("", text)
    return _tidy(text)


def _split_artists(raw: str) -> list[str]:
    return [a.strip(" .") for a in re.split(r",|&|\band\b|\bx\b|\be\b", raw) if a.strip(" .")]


def extract_featured_artists(text: str) -> tuple[str, list[str]]:
    """Rimuove 'feat. X' dal testo e ritorna (testo_pulito, [artisti])."""
    featured: list[str] = []

    match = _FEAT_BRACKET_RE.search(text)
    if match:
        featured = _split_artists(match.group("featured"))
        text = text[: match.start()] + text[match.end():]
    else:
        match = _FEAT_TRAILING_RE.search(text)
        if match:
            featured = _split_artists(match.group("featured"))
            text = text[: match.start()]

    if not featured:
        return text, []
    return _tidy(text), featured


def clean_channel_name(channel: str) -> str:
    """'Artist - Topic' -> 'Artist', 'ArtistVEVO' -> 'Artist',
    'Artist Official' -> 'Artist'. Mai vuoto se l'input non lo era."""
    if not channel:
        return ""
    cleaned = _CHANNEL_TOPIC_RE.sub("", channel.strip())
    cleaned = _CHANNEL_SUFFIX_RE.sub("", cleaned).strip()
    return cleaned or channel.strip()


def is_topic_channel(channel: str) -> bool:
    """I canali "Artist - Topic" sono generati da YouTube Music: il titolo
    del video e' il solo titolo del brano e l'artista e' il canale."""
    return bool(channel and _CHANNEL_TOPIC_RE.search(channel.strip()))


def _unquote(text: str) -> str:
    text = text.strip()
    if len(text) >= 2 and text[0] in _QUOTES and text[-1] in _QUOTES:
        return text[1:-1].strip()
    return text


def parse_title(raw_title: str, channel_name: str = "") -> ParsedTitle:
    """
    Prova a separare "Artist - Title" dal titolo grezzo YouTube.

    Strategia (nessuna invenzione, solo pattern espliciti):
    1. Rimuove rumore tipo "(Official Video)", "| Lyrics", hashtag.
    2. Cerca un separatore Artist - Title (o 'Artist "Title"').
    3. Estrae eventuali "feat. X" da titolo e artista.
    4. Canale "Artist - Topic" senza separatore: l'artista e' il canale.
    5. Altrimenti ritorna confident=False con artist = "" (il chiamante
       decide come gestirlo, es. fallback su channel_name).
    """
    cleaned = strip_noise_tags(raw_title)

    for sep in _ARTIST_TITLE_SEPARATORS:
        if sep in cleaned:
            left, right = cleaned.split(sep, 1)
            # "Artist - Song | Album" / "Artist - Song // Extra": dopo aver
            # separato artista e titolo, cio' che segue un ulteriore "|" o
            # "//" non e' il titolo (spesso album o nome del canale).
            right = re.split(r"\s+(?:\||//)\s+", right)[0]
            left, right = _unquote(left), _unquote(_tidy(right))
            if left and right:
                artist, featured_left = extract_featured_artists(left)
                title_no_feat, featured_right = extract_featured_artists(right)
                featured = featured_left + [a for a in featured_right if a not in featured_left]
                return ParsedTitle(
                    artist=artist or left,
                    title=_unquote(title_no_feat) or right,
                    featured_artists=featured or None,
                    confident=True,
                )

    quoted = _QUOTED_TITLE_RE.match(cleaned)
    if quoted:
        artist, featured_left = extract_featured_artists(quoted.group("artist").strip())
        title_no_feat, featured_right = extract_featured_artists(quoted.group("title").strip())
        featured = featured_left + [a for a in featured_right if a not in featured_left]
        return ParsedTitle(
            artist=artist,
            title=title_no_feat,
            featured_artists=featured or None,
            confident=True,
        )

    title_no_feat, featured = extract_featured_artists(cleaned)
    title_no_feat = _unquote(title_no_feat) or cleaned

    if is_topic_channel(channel_name):
        return ParsedTitle(
            artist=clean_channel_name(channel_name),
            title=title_no_feat,
            featured_artists=featured or None,
            confident=True,
        )

    # Nessun separatore riconosciuto: NON assumiamo un artista.
    return ParsedTitle(
        artist="",
        title=title_no_feat,
        featured_artists=featured or None,
        confident=False,
    )


def build_artist_credit(primary_artist: str, featured_artists: list[str] | None) -> str:
    """Costruisce la stringa Artist da mostrare in tag/UI, es.
    'Artist A feat. Artist B'. Non tocca l'Album Artist (vedi normalizer)."""
    if not featured_artists:
        return primary_artist
    return f"{primary_artist} feat. {', '.join(featured_artists)}"
