from backend.downloader.ytdlp_client import VideoInfo
from backend.metadata.normalizer import normalize_metadata


def make_video_info(title="Artist A - Song Title", uploader="Artist A - Topic", **raw):
    return VideoInfo(
        id="abc123", title=title, uploader=uploader, duration=200,
        thumbnail="https://example.com/thumb.jpg", webpage_url="https://youtu.be/abc123",
        raw=raw,
    )


def test_normalize_basic_single_track_no_album():
    info = make_video_info()
    meta = normalize_metadata(info)
    assert meta.artist == "Artist A"
    assert meta.title == "Song Title"
    assert meta.album == ""
    assert meta.is_single is True


def test_normalize_album_sets_album_artist_from_primary_artist():
    info = make_video_info()
    meta = normalize_metadata(info, user_overrides={"album": "Great Album"})
    assert meta.album == "Great Album"
    assert meta.album_artist == "Artist A"
    assert meta.is_single is False


def test_normalize_compilation_sets_various_artists():
    info = make_video_info()
    meta = normalize_metadata(info, user_overrides={"album": "Now That's What I Call Music", "is_compilation": True})
    assert meta.album_artist == "Various Artists"
    assert meta.is_compilation is True


def test_normalize_user_overrides_take_priority():
    info = make_video_info()
    meta = normalize_metadata(info, user_overrides={"artist": "Custom Artist", "title": "Custom Title"})
    assert meta.artist == "Custom Artist"
    assert meta.title == "Custom Title"


def test_normalize_track_number_from_playlist_index_only_with_album():
    info = make_video_info()
    meta_no_album = normalize_metadata(info, playlist_index=5)
    assert meta_no_album.track_number is None  # nessun album confermato: non numeriamo

    meta_with_album = normalize_metadata(info, playlist_index=5, user_overrides={"album": "Compilation"})
    assert meta_with_album.track_number == 5


def test_normalize_falls_back_to_uploader_when_no_separator():
    info = make_video_info(title="Some Video With No Separator", uploader="Cool Channel")
    meta = normalize_metadata(info)
    assert meta.artist == "Cool Channel"


def test_normalize_year_from_upload_date():
    info = make_video_info(upload_date="20230615")
    meta = normalize_metadata(info)
    assert meta.year == 2023
