from backend.library.filename import build_track_filename, sanitize_path_component


def test_sanitize_keeps_legitimate_unicode():
    assert sanitize_path_component("Beyoncé") == "Beyoncé"
    assert sanitize_path_component("Mötley Crüe") == "Mötley Crüe"


def test_sanitize_removes_forbidden_characters():
    result = sanitize_path_component('Song: "Title" / <weird>')
    for ch in '/\\:*?"<>|':
        assert ch not in result


def test_sanitize_blocks_path_traversal():
    result = sanitize_path_component("../../etc/passwd")
    assert ".." not in result
    assert "/" not in result


def test_sanitize_empty_uses_fallback():
    assert sanitize_path_component("") == "Unknown"
    assert sanitize_path_component("   ") == "Unknown"


def test_sanitize_truncates_long_names():
    long_name = "A" * 500
    result = sanitize_path_component(long_name)
    assert len(result.encode("utf-8")) <= 180


def test_build_track_filename_with_track_number():
    assert build_track_filename(3, "My Song", "m4a") == "03 - My Song.m4a"


def test_build_track_filename_without_track_number():
    assert build_track_filename(None, "My Song", "mp3") == "My Song.mp3"


def test_build_track_filename_double_digit():
    assert build_track_filename(12, "Track", "flac") == "12 - Track.flac"
