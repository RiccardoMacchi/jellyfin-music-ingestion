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
