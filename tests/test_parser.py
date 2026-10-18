from backend.metadata.parser import (
    build_artist_credit,
    extract_featured_artists,
    parse_title,
    strip_noise_tags,
)


def test_strip_noise_tags_removes_official_video():
    assert strip_noise_tags("Artist - Song (Official Video)") == "Artist - Song"
    assert strip_noise_tags("Artist - Song [Official Audio]") == "Artist - Song"
    assert strip_noise_tags("Artist - Song (Lyrics)") == "Artist - Song"


def test_parse_title_splits_artist_and_title():
    parsed = parse_title("Daft Punk - One More Time (Official Video)")
    assert parsed.artist == "Daft Punk"
    assert parsed.title == "One More Time"
    assert parsed.confident is True


def test_parse_title_extracts_featured_artist():
    parsed = parse_title("Artist A - Song Title (feat. Artist B)")
    assert parsed.artist == "Artist A"
    assert parsed.title == "Song Title"
    assert parsed.featured_artists == ["Artist B"]


def test_parse_title_multiple_featured_artists():
    parsed = parse_title("Artist A - Song ft. Artist B & Artist C")
    assert parsed.featured_artists == ["Artist B", "Artist C"]


def test_parse_title_no_separator_not_confident():
    parsed = parse_title("Some Random Video Title")
    assert parsed.confident is False
    assert parsed.artist == ""
    assert parsed.title == "Some Random Video Title"


def test_parse_title_never_invents_artist():
    # senza un separatore riconoscibile non dobbiamo MAI inventare un artista
    parsed = parse_title("Official Lofi Beats To Study")
    assert parsed.artist == ""


def test_extract_featured_artists_no_match():
    text, featured = extract_featured_artists("Just A Title")
    assert text == "Just A Title"
    assert featured == []


def test_build_artist_credit_with_featured():
    assert build_artist_credit("A", ["B", "C"]) == "A feat. B, C"


def test_build_artist_credit_without_featured():
    assert build_artist_credit("A", None) == "A"
    assert build_artist_credit("A", []) == "A"


# ---- rumore tipico dei titoli YouTube ---------------------------------

import pytest

from backend.metadata.parser import clean_channel_name, is_topic_channel


@pytest.mark.parametrize("raw, expected", [
    ("Artist - Song (Official Music Video)", "Artist - Song"),
    ("Artist - Song [Official Video] [4K]", "Artist - Song"),
    ("Artist - Song (Video Ufficiale)", "Artist - Song"),
    ("Artist - Song (Videoclip Ufficiale)", "Artist - Song"),
    ("Artist - Song (Official Lyric Video)", "Artist - Song"),
    ("Artist - Song (Testo)", "Artist - Song"),
    ("Artist - Song (Video Oficial)", "Artist - Song"),
    ("Artist - Song (Clip Officiel)", "Artist - Song"),
    ("Artist - Song (HD) (2019)", "Artist - Song"),
    ("Artist - Song (Remastered 2011)", "Artist - Song"),
    ("Artist - Song (2011 Remaster)", "Artist - Song"),
    ("Artist - Song (prod. by Someone)", "Artist - Song"),
    ("Artist - Song 【MV】", "Artist - Song"),
    ("Artist - Song | Official Music Video", "Artist - Song"),
    ("Artist - Song - Official Video", "Artist - Song"),
    ("Artist - Song // Lyrics", "Artist - Song"),
    ("Artist - Song Official Video", "Artist - Song"),
    ("Artist - Song #shorts #music", "Artist - Song"),
    ("Artist - Song 🔥 (Official Audio)", "Artist - Song"),
])
def test_strip_noise_tags_real_world(raw, expected):
    assert strip_noise_tags(raw) == expected


@pytest.mark.parametrize("raw, expected", [
    # le indicazioni di versione distinguono brani diversi: restano
    ("Artist - Song (Remix)", "Artist - Song (Remix)"),
    ("Artist - Song (Extended Mix)", "Artist - Song (Extended Mix)"),
    ("Artist - Song (Live at Wembley)", "Artist - Song (Live at Wembley)"),
    ("Artist - Song (Official Live Video)", "Artist - Song (Live)"),
    ("Artist - Song [Official Remix Video]", "Artist - Song [Remix]"),
    ("Artist - Song (Acoustic Version) [Official Audio]", "Artist - Song (Acoustic Version)"),
    # titoli veri che somigliano a rumore NON vanno toccati
    ("Prince - 1999", "Prince - 1999"),
    ("Artist - Product of Love", "Artist - Product of Love"),
    ("Artist - Song (Part 2)", "Artist - Song (Part 2)"),
])
def test_strip_noise_tags_keeps_real_title_parts(raw, expected):
    assert strip_noise_tags(raw) == expected


def test_parse_title_feat_before_noise_and_version():
    parsed = parse_title("Artist A - Song (feat. Artist B) [Remix] (Official Video)")
    assert parsed.artist == "Artist A"
    assert parsed.title == "Song [Remix]"
    assert parsed.featured_artists == ["Artist B"]


def test_parse_title_feat_on_artist_side():
    parsed = parse_title("Artist A ft. Artist B - Song (Official Video)")
    assert parsed.artist == "Artist A"
    assert parsed.title == "Song"
    assert parsed.featured_artists == ["Artist B"]


def test_parse_title_quoted_title_without_separator():
    parsed = parse_title('Artist A "Song Title" (Official Video)')
    assert parsed.artist == "Artist A"
    assert parsed.title == "Song Title"
    assert parsed.confident is True


def test_parse_title_quoted_title_with_separator():
    parsed = parse_title('Artist A - "Song Title"')
    assert parsed.title == "Song Title"


def test_parse_title_topic_channel_uses_channel_as_artist():
    parsed = parse_title("Song Title", channel_name="Artist A - Topic")
    assert parsed.artist == "Artist A"
    assert parsed.title == "Song Title"
    assert parsed.confident is True


def test_parse_title_pipe_noise_does_not_become_artist_split():
    parsed = parse_title("Artist - Song | Official Video")
    assert parsed.artist == "Artist"
    assert parsed.title == "Song"


def test_clean_channel_name():
    assert clean_channel_name("Artist A - Topic") == "Artist A"
    assert clean_channel_name("DaftPunkVEVO") == "DaftPunk"
    assert clean_channel_name("Artist Official") == "Artist"
    assert clean_channel_name("Plain Channel") == "Plain Channel"
    assert is_topic_channel("Artist - Topic")
    assert not is_topic_channel("Artist")


def test_strip_noise_removes_group_with_strong_noise_and_extra_text():
    assert strip_noise_tags("Måneskin - ZITTI E BUONI (Official Video - Sanremo 2021)") == "Måneskin - ZITTI E BUONI"
    # ma una versione resta riconoscibile
    assert strip_noise_tags("Artist - Song (Official Video - Live)") == "Artist - Song (Live)"


def test_parse_title_drops_trailing_album_after_pipe():
    parsed = parse_title("Bad Bunny - Tití Me Preguntó (Video Oficial) | Un Verano Sin Ti")
    assert parsed.artist == "Bad Bunny"
    assert parsed.title == "Tití Me Preguntó"


def test_parse_title_pipe_as_only_separator_still_works():
    parsed = parse_title("Artist | Song")
    assert parsed.artist == "Artist"
    assert parsed.title == "Song"
