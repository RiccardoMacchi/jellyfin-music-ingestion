from pathlib import Path

from backend.library.path_builder import build_library_path
from backend.metadata.normalizer import TrackMetadata


def test_album_track_path(configured_dirs):
    meta = TrackMetadata(
        title="Song", artist="Artist A", album_artist="Artist A",
        album="Great Album", track_number=3, is_single=False,
    )
    file_path, cover_path = build_library_path(meta, "m4a")
    assert file_path == str(Path(configured_dirs["music"]) / "Artist A" / "Great Album" / "03 - Song.m4a")
    assert cover_path == str(Path(configured_dirs["music"]) / "Artist A" / "Great Album" / "cover.jpg")


def test_single_track_path_has_no_shared_cover(configured_dirs):
    meta = TrackMetadata(title="Solo Song", artist="Solo Artist", album="", is_single=True)
    file_path, cover_path = build_library_path(meta, "mp3")
    assert file_path == str(Path(configured_dirs["music"]) / "Solo Artist" / "Singles" / "Solo Song.mp3")
    assert cover_path == ""


def test_compilation_track_path_uses_various_artists(configured_dirs):
    meta = TrackMetadata(
        title="Track", artist="Some Artist", album_artist="Various Artists",
        album="Now 1999", track_number=7, is_single=False, is_compilation=True,
    )
    file_path, _ = build_library_path(meta, "flac")
    assert file_path == str(Path(configured_dirs["music"]) / "Various Artists" / "Now 1999" / "07 - Track.flac")


def test_path_sanitizes_unsafe_names(configured_dirs):
    meta = TrackMetadata(title="A/B: C", artist="X/Y", album="", is_single=True)
    file_path, _ = build_library_path(meta, "m4a")
    assert "/" not in Path(file_path).name
    assert "X/Y" not in file_path
