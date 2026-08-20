"""
Test dell'API HTTP con TestClient. yt-dlp e il loop della coda sono sempre
mockati: questi test verificano il comportamento dell'API (validazione,
duplicate detection, transizioni di stato), non l'esecuzione reale della
pipeline (vedi test_worker_pipeline.py per quello).
"""
import pytest
from fastapi.testclient import TestClient

from backend.downloader.ytdlp_client import PlaylistEntry, PlaylistInfo, VideoInfo
from backend.queue.manager import QueueManager


@pytest.fixture()
def client(configured_dirs, monkeypatch):
    # Non avviare davvero il loop della coda durante i test API: la
    # pipeline reale e' gia' testata in isolamento altrove.
    monkeypatch.setattr(QueueManager, "start", lambda self: None)

    from backend.main import app
    with TestClient(app) as c:
        yield c


def fake_video_info(**overrides):
    base = dict(
        id="abc123", title="Artist A - Song Title (Official Video)",
        uploader="Artist A", duration=210, thumbnail="https://img/thumb.jpg",
        webpage_url="https://youtu.be/abc123", raw={},
    )
    base.update(overrides)
    return VideoInfo(**base)


def test_health_endpoint(client):
    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"


def test_version_endpoint(client):
    res = client.get("/api/version")
    assert res.status_code == 200
    body = res.json()
    assert "app_name" in body and "app_version" in body


def test_analyze_rejects_non_youtube_url(client):
    res = client.post("/api/analyze", json={"url": "https://vimeo.com/12345"})
    assert res.status_code == 422


def test_analyze_returns_parsed_preview(client, monkeypatch):
    import backend.api.routes_analyze as routes

    monkeypatch.setattr(routes, "extract_video_info", lambda url: fake_video_info())

    res = client.post("/api/analyze", json={"url": "https://youtu.be/abc123"})
    assert res.status_code == 200
    body = res.json()
    assert body["suggested_artist"] == "Artist A"
    assert body["suggested_title"] == "Song Title"
    assert body["is_playlist"] is False


def test_playlist_analyze_returns_entries(client, monkeypatch):
    import backend.api.routes_analyze as routes

    fake_playlist = PlaylistInfo(
        id="PL1", title="My Mix",
        entries=[
            PlaylistEntry(id="v1", title="Track 1", url="https://youtu.be/v1", index=1),
            PlaylistEntry(id="v2", title="Track 2", url="https://youtu.be/v2", index=2),
        ],
    )
    monkeypatch.setattr(routes, "extract_playlist_info", lambda url, limit=200: fake_playlist)

    res = client.post("/api/playlist/analyze", json={"url": "https://youtube.com/playlist?list=PL1"})
    assert res.status_code == 200
    body = res.json()
    assert body["title"] == "My Mix"
    assert len(body["entries"]) == 2


def test_create_download_with_full_payload(client):
    res = client.post("/api/download", json={
        "url": "https://youtu.be/abc123",
        "youtube_id": "abc123",
        "title": "Song Title",
        "artist": "Artist A",
        "album": "",
    })
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "PENDING"
    assert body["youtube_id"] == "abc123"


def test_create_download_fetches_metadata_when_missing(client, monkeypatch):
    import backend.api.routes_downloads as routes
    monkeypatch.setattr(routes, "extract_video_info", lambda url: fake_video_info())

    res = client.post("/api/download", json={"url": "https://youtu.be/abc123"})
    assert res.status_code == 200
    body = res.json()
    assert body["artist"] == "Artist A"
    assert body["title"] == "Song Title"


def test_create_download_is_idempotent_for_same_youtube_id(client):
    payload = {"url": "https://youtu.be/dupe1", "youtube_id": "dupe1", "title": "T", "artist": "A"}
    first = client.post("/api/download", json=payload).json()
    second = client.post("/api/download", json=payload).json()
    assert first["id"] == second["id"]

    all_downloads = client.get("/api/downloads").json()
    matching = [d for d in all_downloads if d["youtube_id"] == "dupe1"]
    assert len(matching) == 1  # nessun duplicato creato


def test_list_and_get_download(client):
    created = client.post("/api/download", json={
        "url": "https://youtu.be/x1", "youtube_id": "x1", "title": "T", "artist": "A",
    }).json()

    res = client.get(f"/api/downloads/{created['id']}")
    assert res.status_code == 200
    assert res.json()["id"] == created["id"]

    res_missing = client.get("/api/downloads/999999")
    assert res_missing.status_code == 404


def test_cancel_pending_download(client):
    created = client.post("/api/download", json={
        "url": "https://youtu.be/x2", "youtube_id": "x2", "title": "T", "artist": "A",
    }).json()

    res = client.post(f"/api/downloads/{created['id']}/cancel")
    assert res.status_code == 200
    assert res.json()["status"] == "CANCELLED"


def test_retry_requires_failed_or_cancelled_status(client):
    created = client.post("/api/download", json={
        "url": "https://youtu.be/x3", "youtube_id": "x3", "title": "T", "artist": "A",
    }).json()

    # ancora PENDING: retry deve rifiutare
    res = client.post(f"/api/downloads/{created['id']}/retry")
    assert res.status_code == 409

    client.post(f"/api/downloads/{created['id']}/cancel")
    res_ok = client.post(f"/api/downloads/{created['id']}/retry")
    assert res_ok.status_code == 200
    assert res_ok.json()["status"] == "PENDING"


def test_delete_download(client):
    created = client.post("/api/download", json={
        "url": "https://youtu.be/x4", "youtube_id": "x4", "title": "T", "artist": "A",
    }).json()

    res = client.delete(f"/api/downloads/{created['id']}")
    assert res.status_code == 200

    res_get = client.get(f"/api/downloads/{created['id']}")
    assert res_get.status_code == 404


def test_delete_missing_download_returns_404(client):
    res = client.delete("/api/downloads/987654")
    assert res.status_code == 404
