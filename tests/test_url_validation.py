import pytest

from backend.downloader.validator import (
    InvalidURLError,
    extract_video_id_hint,
    is_playlist_url,
    validate_youtube_url,
)


@pytest.mark.parametrize("url", [
    "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    "https://youtu.be/dQw4w9WgXcQ",
    "https://music.youtube.com/watch?v=dQw4w9WgXcQ",
    "http://m.youtube.com/watch?v=dQw4w9WgXcQ",
])
def test_valid_youtube_urls_accepted(url):
    assert validate_youtube_url(url) == url


@pytest.mark.parametrize("url", [
    "",
    "not a url",
    "https://vimeo.com/12345",
    "ftp://youtube.com/watch?v=x",
    "javascript:alert(1)",
    "https://evil.com/youtube.com/watch?v=x",
    "https://youtube.com.evil.com/watch?v=x",
])
def test_invalid_urls_rejected(url):
    with pytest.raises(InvalidURLError):
        validate_youtube_url(url)


def test_url_too_long_rejected():
    with pytest.raises(InvalidURLError):
        validate_youtube_url("https://youtube.com/watch?v=" + "a" * 3000)


def test_is_playlist_url_detects_list_param():
    assert is_playlist_url("https://www.youtube.com/watch?v=x&list=PL123") is True
    assert is_playlist_url("https://www.youtube.com/watch?v=x") is False


def test_extract_video_id_hint_valid():
    assert extract_video_id_hint({"id": "dQw4w9WgXcQ"}) == "dQw4w9WgXcQ"


def test_extract_video_id_hint_rejects_bad_id():
    with pytest.raises(InvalidURLError):
        extract_video_id_hint({"id": "../../etc/passwd"})
    with pytest.raises(InvalidURLError):
        extract_video_id_hint({"id": ""})
