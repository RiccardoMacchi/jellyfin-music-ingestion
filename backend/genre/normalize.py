"""
Normalizzazione dei generi in un insieme ridotto di generi "canonici".

I provider restituiscono etichette molto diverse tra loro: Deezer usa pochi
generi larghi ("Rap/Hip Hop", "Dance"), MusicBrainz tag di comunita' molto
granulari ("french house", "trap metal", "cantautorato"). Per creare
playlist utili servono pochi generi stabili: qui li riportiamo tutti a una
lista canonica. Un genere che non riconosciamo passa invariato (in Title
Case), cosi' non perdiamo informazione.
"""
from __future__ import annotations

import re

# Corrispondenze esatte (dopo lowercase/normalizzazione): hanno la priorita'
# sulle parole chiave, per i generi composti che le parole chiave
# classificherebbero male ("dance-pop" e' Pop, non Dance).
_EXACT = {
    "rap/hip hop": "Hip-Hop",
    "rap": "Hip-Hop",
    "hip hop": "Hip-Hop",
    "pop rap": "Hip-Hop",
    "dance": "Dance",
    "electro": "Electronic",
    "dance pop": "Pop",
    "synth pop": "Pop",
    "electropop": "Pop",
    "teen pop": "Pop",
    "k pop": "K-Pop",
    "j pop": "J-Pop",
    "pop rock": "Rock",
    "pop punk": "Punk",
    "indie pop": "Indie",
    "indie rock": "Indie",
    "indie": "Indie",
    "alternative": "Alternative",
    "alternative rock": "Alternative",
    "soul & funk": "Soul & Funk",
    "latin music": "Latin",
    "films/games": "Soundtrack",
    "film scores": "Soundtrack",
    "kids": "Kids",
    "cantautorato": "Cantautori",
    "singer songwriter": "Cantautori",
    "musica italiana": "Pop",
    "italian pop": "Pop",
}

# (genere canonico, parole chiave). L'ordine conta: vince la prima regola
# che trova una parola chiave nell'etichetta.
_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("Soundtrack", ("soundtrack", "score", "musical", "video game")),
    ("Hip-Hop", ("hip hop", "rap", "trap", "drill", "grime", "boom bap")),
    ("R&B", ("r&b", "rnb", "rhythm and blues", "neo soul", "contemporary r b")),
    ("Reggaeton", ("reggaeton", "dembow", "urbano")),
    ("Latin", ("latin", "salsa", "bachata", "cumbia", "merengue", "flamenco", "bossa")),
    ("Reggae", ("reggae", "dancehall", "ska", "dub")),
    ("Metal", ("metal", "metalcore", "deathcore", "grindcore")),
    ("Punk", ("punk", "hardcore")),
    ("Electronic", ("house", "techno", "trance", "edm", "electronic", "electro", "dubstep",
                    "drum and bass", "dnb", "garage", "big room", "hardstyle", "ambient",
                    "idm", "synthwave", "downtempo", "breakbeat", "eurodance", "electronica")),
    ("Dance", ("dance", "disco")),
    ("Jazz", ("jazz", "swing", "bebop")),
    ("Blues", ("blues",)),
    ("Classical", ("classical", "baroque", "opera", "orchestral", "symphon", "chamber")),
    ("Country", ("country", "bluegrass", "americana")),
    ("Folk", ("folk",)),
    ("Soul & Funk", ("soul", "funk", "motown", "gospel")),
    ("Indie", ("indie",)),
    ("Alternative", ("alternative", "grunge", "emo", "shoegaze", "post rock")),
    ("Rock", ("rock", "britpop")),
    ("Cantautori", ("cantautor", "singer songwriter", "chanson")),
    ("Pop", ("pop",)),
]

# Etichette che NON sono generi (paesi, lingue, decenni, generiche) e vanno
# ignorate quando un provider le restituisce tra i tag.
_IGNORED = {
    "music", "musica", "all", "seen live", "favorites", "favourite", "other", "unknown",
    "italian", "italiano", "italia", "italy", "english", "british", "american", "uk",
    "usa", "french", "german", "spanish", "female vocalists", "male vocalists",
}


def _key(label: str) -> str:
    text = label.strip().lower()
    text = re.sub(r"[-_]+", " ", text)
    return re.sub(r"\s+", " ", text)


def is_meaningful(label: str) -> bool:
    key = _key(label)
    if not key or key in _IGNORED:
        return False
    return not re.fullmatch(r"\d{2,4}s?", key)  # "80s", "2010s"


def canonical_genre(label: str) -> str:
    """'rap/hip hop' -> 'Hip-Hop', 'french house' -> 'Electronic',
    'dance-pop' -> 'Pop'. Etichette sconosciute -> Title Case invariato."""
    key = _key(label)
    if not key:
        return ""
    if key in _EXACT:
        return _EXACT[key]
    padded = f" {key} "
    for canonical, keywords in _KEYWORDS:
        for kw in keywords:
            # parole chiave corte (rap, ska, dub, emo, edm...) devono essere
            # parole intere: "rap" non deve scattare su "trapani" o "therapy".
            if len(kw) <= 4:
                if re.search(rf"(?<![a-z]){re.escape(kw)}(?![a-z])", key):
                    return canonical
            elif kw in padded:
                return canonical
    return " ".join(w[:1].upper() + w[1:] for w in key.split(" "))
