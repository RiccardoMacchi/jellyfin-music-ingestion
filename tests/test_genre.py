"""
Riconoscimento del genere e playlist per genere. Nessuna chiamata di rete:
i provider sono mockati sostituendo `_get_json`, Jellyfin con
httpx.MockTransport.
"""
import json
import shutil

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.config import settings
from backend.database.models import DownloadRecord, DownloadStatus
from backend.genre import backfill, detector
from backend.genre.normalize import canonical_genre, is_meaningful
from backend.jellyfin import playlists
from backend.queue.manager import QueueManager


# ---------------------------------------------------------------- normalize

@pytest.mark.parametrize("label, expected", [
    ("Rap/Hip Hop", "Hip-Hop"),
    ("hip-hop", "Hip-Hop"),
    ("italian trap", "Hip-Hop"),
    ("Dance", "Dance"),
    ("dance-pop", "Pop"),
    ("synth-pop", "Pop"),
    ("french house", "Electronic"),
    ("Electro", "Electronic"),
    ("dubstep", "Electronic"),
    ("dancehall", "Reggae"),
    ("R&B", "R&B"),
    ("contemporary r&b", "R&B"),
    ("Soul & Funk", "Soul & Funk"),
    ("Films/Games", "Soundtrack"),
    ("alternative rock", "Alternative"),
    ("hard rock", "Rock"),
    ("heavy metal", "Metal"),
    ("cantautorato", "Cantautori"),
    ("Pop", "Pop"),
    ("vaporwave", "Vaporwave"),  # sconosciuto: passa invariato
])
def test_canonical_genre(label, expected):
    assert canonical_genre(label) == expected


def test_short_keywords_match_whole_words_only():
    assert canonical_genre("therapy") == "Therapy"   # non "Hip-Hop" per "rap"
    assert canonical_genre("emotional") == "Emotional"  # non "Alternative" per "emo"


def test_non_genres_are_ignored():
    assert not is_meaningful("italian")
    assert not is_meaningful("80s")
    assert not is_meaningful("seen live")
    assert is_meaningful("pop")


def test_primary_artist():
    assert detector.primary_artist("A feat. B", "") == "A"
    assert detector.primary_artist("A feat. B", "A") == "A"
    assert detector.primary_artist("A", "Various Artists") == "A"


# ---------------------------------------------------------------- providers

def _fake_http(routes):
    """routes: lista di (sottostringa URL, risposta JSON o callable(params))."""
    calls = []

    async def _get_json(url, params=None, headers=None):
        calls.append((url, params))
        for fragment, response in routes:
            if fragment in url:
                return response(params) if callable(response) else response
        raise AssertionError(f"URL inatteso: {url}")

    return _get_json, calls


@pytest.fixture()
def genre_enabled(monkeypatch):
    monkeypatch.setattr(settings, "genre_autodetect", True)
    monkeypatch.setattr(settings, "genre_providers", "deezer,musicbrainz")
    # niente attese reali per il rate limit di MusicBrainz
    monkeypatch.setattr(detector, "_MB_MIN_INTERVAL_SECONDS", 0)


@pytest.mark.asyncio
async def test_deezer_match_returns_canonical_genre(monkeypatch, genre_enabled):
    fake, calls = _fake_http([
        ("/search", {"data": [
            {"title": "Other Song", "artist": {"name": "Daft Punk"}, "album": {"id": 1}},
            {"title": "One More Time", "artist": {"name": "Daft Punk"}, "album": {"id": 2}},
        ]}),
        ("/album/2", {"genres": {"data": [{"name": "Dance"}, {"name": "Electro"}]}}),
    ])
    monkeypatch.setattr(detector, "_get_json", fake)

    result = await detector.detect_genre("Daft Punk", "One More Time")

    assert result.genre == "Dance"
    assert result.source == "deezer"
    assert not any("/album/1" in url for url, _ in calls)


@pytest.mark.asyncio
async def test_deezer_ignores_wrong_artist_and_falls_back_to_musicbrainz(monkeypatch, genre_enabled):
    fake, _ = _fake_http([
        ("api.deezer.com/search", {"data": [
            {"title": "Song", "artist": {"name": "Somebody Else"}, "album": {"id": 9}},
        ]}),
        ("/ws/2/recording/rec-1", {"genres": []}),
        ("/ws/2/recording", {"recordings": [{
            "id": "rec-1", "score": 100, "title": "Song",
            "artist-credit": [{"name": "Artist A", "artist": {"id": "art-1"}}],
        }]}),
        ("/ws/2/artist/art-1", {"genres": [{"name": "indie rock", "count": 3}, {"name": "pop", "count": 9}]}),
    ])
    monkeypatch.setattr(detector, "_get_json", fake)

    result = await detector.detect_genre("Artist A", "Song")

    assert result.genre == "Pop"  # il genere con piu' voti
    assert result.source == "musicbrainz"


@pytest.mark.asyncio
async def test_detect_genre_never_invents(monkeypatch, genre_enabled):
    fake, _ = _fake_http([
        ("api.deezer.com/search", {"data": []}),
        ("/ws/2/recording", {"recordings": [{
            "id": "x", "score": 40, "title": "Song",
            "artist-credit": [{"name": "Artist A", "artist": {"id": "a"}}],
        }]}),
    ])
    monkeypatch.setattr(detector, "_get_json", fake)
    assert await detector.detect_genre("Artist A", "Song") is None


@pytest.mark.asyncio
async def test_detect_genre_survives_provider_errors(monkeypatch, genre_enabled):
    async def boom(url, params=None, headers=None):
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(detector, "_get_json", boom)
    assert await detector.detect_genre("Artist A", "Song") is None


# ---------------------------------------------------------------- backfill

def _completed(repo, music_dir, youtube_id, artist, title, genre="", genre_source="", src=None):
    target = music_dir / artist / "Singles" / f"{title}.m4a"
    target.parent.mkdir(parents=True, exist_ok=True)
    if src:
        shutil.copyfile(src, target)
    else:
        target.write_bytes(b"")
    return repo.create(DownloadRecord(
        youtube_id=youtube_id, url=f"https://youtu.be/{youtube_id}", title=title, artist=artist,
        album_artist=artist, genre=genre, genre_source=genre_source,
        status=DownloadStatus.COMPLETED.value, file_path=str(target),
    ))


@pytest.mark.asyncio
async def test_backfill_tags_files_and_skips_manual(configured_dirs, download_repo, monkeypatch, sample_audio_file):
    from mutagen.mp4 import MP4

    music = configured_dirs["music"]
    auto = _completed(download_repo, music, "y1", "Artist A", "Song", src=sample_audio_file)
    manual = _completed(download_repo, music, "y2", "Artist B", "Other", genre="Jazz",
                        genre_source="manual", src=sample_audio_file)

    async def fake_detect(artist, title):
        return detector.GenreResult(genre="Pop", source="deezer", raw="Pop")

    monkeypatch.setattr(backfill, "detect_genre", fake_detect)

    assert backfill.start_backfill(download_repo, force=True)
    await backfill._task

    assert download_repo.get(auto.id).genre == "Pop"
    assert download_repo.get(auto.id).genre_source == "deezer"
    assert MP4(download_repo.get(auto.id).file_path)["\xa9gen"] == ["Pop"]
    assert download_repo.get(manual.id).genre == "Jazz"  # manuale: intoccabile
    assert backfill.get_status()["updated"] == 1


# ---------------------------------------------------------------- playlists

class _FakeJellyfin:
    """Mini server Jellyfin in memoria per httpx.MockTransport."""

    def __init__(self, items, existing_playlists=None):
        self.items = items  # [(id, path)]
        self.playlists = existing_playlists or {}  # id -> {"name", "entries": [(entry_id, item_id)]}
        self.requests = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path, params = request.url.path, request.url.params
        assert request.headers["X-Emby-Token"] == "secret"

        if path == "/Users":
            return httpx.Response(200, json=[
                {"Id": "u-user", "Name": "guest", "Policy": {"IsAdministrator": False}},
                {"Id": "u-admin", "Name": "admin", "Policy": {"IsAdministrator": True}},
            ])
        if path == "/Items" and params["IncludeItemTypes"] == "Audio":
            return httpx.Response(200, json={"Items": [{"Id": i, "Path": p} for i, p in self.items]})
        if path == "/Items" and params["IncludeItemTypes"] == "Playlist":
            return httpx.Response(200, json={"Items": [
                {"Id": pid, "Name": p["name"]} for pid, p in self.playlists.items()
            ]})
        if path == "/Playlists" and request.method == "POST":
            body = json.loads(request.content)
            assert body["UserId"] == "u-admin"
            pid = f"pl-{len(self.playlists) + 1}"
            self.playlists[pid] = {"name": body["Name"], "entries": [(f"e-{i}", i) for i in body["Ids"]]}
            return httpx.Response(200, json={"Id": pid})
        if path.startswith("/Playlists/") and path.endswith("/Items"):
            pid = path.split("/")[2]
            pl = self.playlists[pid]
            if request.method == "GET":
                return httpx.Response(200, json={"Items": [
                    {"Id": item, "PlaylistItemId": entry} for entry, item in pl["entries"]
                ]})
            if request.method == "POST":
                pl["entries"] += [(f"e-{i}", i) for i in params["ids"].split(",")]
                return httpx.Response(204)
            if request.method == "DELETE":
                drop = set(params["entryIds"].split(","))
                pl["entries"] = [(e, i) for e, i in pl["entries"] if e not in drop]
                return httpx.Response(204)
        return httpx.Response(404)


@pytest.fixture()
def jellyfin_on(monkeypatch):
    monkeypatch.setattr(settings, "jellyfin_enabled", True)
    monkeypatch.setattr(settings, "jellyfin_url", "http://jellyfin.local:8096")
    monkeypatch.setattr(settings, "jellyfin_api_key", "secret")
    monkeypatch.setattr(settings, "jellyfin_user", "")
    monkeypatch.setattr(settings, "genre_playlists_enabled", True)
    monkeypatch.setattr(settings, "genre_playlist_prefix", "Genere: ")
    monkeypatch.setattr(settings, "genre_playlist_min_tracks", 1)


def _use_fake(monkeypatch, fake):
    def _client():
        return httpx.AsyncClient(
            base_url=settings.jellyfin_url, headers=playlists._headers(),
            transport=httpx.MockTransport(fake.handler),
        )
    monkeypatch.setattr(playlists, "_client", _client)


@pytest.mark.asyncio
async def test_sync_creates_playlists_matching_by_relative_path(configured_dirs, download_repo, monkeypatch, jellyfin_on):
    music = configured_dirs["music"]
    _completed(download_repo, music, "a", "Artist A", "Song 1", genre="Pop")
    _completed(download_repo, music, "b", "Artist B", "Song 2", genre="Pop")
    _completed(download_repo, music, "c", "Artist C", "Song 3", genre="Rock")
    _completed(download_repo, music, "d", "Artist D", "Not Scanned", genre="Rock")
    _completed(download_repo, music, "e", "Artist E", "No Genre")

    # Jellyfin vede la libreria su un path diverso (/media/music)
    fake = _FakeJellyfin(items=[
        ("j1", "/media/music/Artist A/Singles/Song 1.m4a"),
        ("j2", "/media/music/Artist B/Singles/Song 2.m4a"),
        ("j3", "/media/music/Artist C/Singles/Song 3.m4a"),
        ("j5", "/media/music/Artist E/Singles/No Genre.m4a"),
    ])
    _use_fake(monkeypatch, fake)

    result = await playlists.sync_genre_playlists(download_repo)

    assert sorted(result.created) == ["Genere: Pop", "Genere: Rock"]
    assert result.playlists == {"Genere: Pop": 2, "Genere: Rock": 1}
    assert result.not_indexed == 1
    by_name = {p["name"]: [i for _, i in p["entries"]] for p in fake.playlists.values()}
    assert by_name == {"Genere: Pop": ["j1", "j2"], "Genere: Rock": ["j3"]}


@pytest.mark.asyncio
async def test_sync_is_idempotent_and_moves_changed_genres(configured_dirs, download_repo, monkeypatch, jellyfin_on):
    music = configured_dirs["music"]
    _completed(download_repo, music, "a", "Artist A", "Song 1", genre="Rock")  # era Pop
    fake = _FakeJellyfin(
        items=[("j1", "/music/Artist A/Singles/Song 1.m4a")],
        existing_playlists={
            "pl-pop": {"name": "Genere: Pop", "entries": [("e-old", "j1")]},
            "pl-mine": {"name": "My own playlist", "entries": [("e-x", "j1")]},
        },
    )
    _use_fake(monkeypatch, fake)

    first = await playlists.sync_genre_playlists(download_repo)
    assert first.created == ["Genere: Rock"]
    assert first.removed == 1
    assert fake.playlists["pl-pop"]["entries"] == []
    assert fake.playlists["pl-mine"]["entries"] == [("e-x", "j1")]  # non gestita: intatta

    second = await playlists.sync_genre_playlists(download_repo)
    assert second.created == [] and second.added == 0 and second.removed == 0


@pytest.mark.asyncio
async def test_sync_requires_jellyfin(download_repo):
    with pytest.raises(playlists.PlaylistSyncError):
        await playlists.sync_genre_playlists(download_repo)


# ---------------------------------------------------------------- API

@pytest.fixture()
def client(configured_dirs, monkeypatch):
    monkeypatch.setattr(QueueManager, "start", lambda self: None)
    from backend.main import app
    with TestClient(app) as c:
        yield c


def test_api_genre_source_manual_vs_suggested(client):
    manual = client.post("/api/download", json={
        "url": "https://youtu.be/g1", "youtube_id": "g1", "title": "T", "artist": "A", "genre": "Pop",
    }).json()
    assert manual["genre_source"] == "manual"

    suggested = client.post("/api/download", json={
        "url": "https://youtu.be/g2", "youtube_id": "g2", "title": "T", "artist": "A",
        "genre": "Pop", "genre_source": "deezer",
    }).json()
    assert suggested["genre_source"] == "deezer"


def test_api_set_genre_updates_record(client):
    created = client.post("/api/download", json={
        "url": "https://youtu.be/g3", "youtube_id": "g3", "title": "T", "artist": "A",
    }).json()
    res = client.post(f"/api/downloads/{created['id']}/genre", json={"genre": "Jazz"})
    assert res.status_code == 200
    assert res.json()["genre"] == "Jazz"
    assert res.json()["genre_source"] == "manual"

    cleared = client.post(f"/api/downloads/{created['id']}/genre", json={"genre": ""}).json()
    assert cleared["genre"] == "" and cleared["genre_source"] == ""


def test_api_genres_overview_and_playlist_sync_unavailable(client):
    res = client.get("/api/genres")
    assert res.status_code == 200
    body = res.json()
    assert body["playlists_available"] is False
    assert body["backfill"]["running"] is False

    res = client.post("/api/playlists/sync")
    assert res.status_code == 409


def test_api_analyze_suggests_genre(client, monkeypatch):
    import backend.api.routes_analyze as routes
    from backend.downloader.ytdlp_client import VideoInfo

    monkeypatch.setattr(settings, "genre_autodetect", True)
    monkeypatch.setattr(routes, "extract_video_info", lambda url: VideoInfo(
        id="abc", title="Artist A - Song (Official Video)", uploader="Artist A", duration=200,
        thumbnail="", webpage_url="https://youtu.be/abc", raw={},
    ))

    async def fake_detect(artist, title):
        assert (artist, title) == ("Artist A", "Song")
        return detector.GenreResult(genre="Pop", source="deezer")

    monkeypatch.setattr(routes, "detect_genre", fake_detect)

    body = client.post("/api/analyze", json={"url": "https://youtu.be/abc"}).json()
    assert body["suggested_genre"] == "Pop"
    assert body["suggested_genre_source"] == "deezer"


@pytest.mark.asyncio
async def test_backfill_reports_running_immediately(configured_dirs, download_repo):
    """La UI legge lo stato subito dopo l'avvio: deve gia' risultare in corso,
    altrimenti smette di aggiornarsi credendo il lavoro concluso."""
    assert backfill.start_backfill(download_repo)
    assert backfill.get_status()["running"] is True
    await backfill._task
    status = backfill.get_status()
    assert status["running"] is False and status["total"] == 0


def test_frontend_files_are_always_revalidated(client):
    """Senza Cache-Control il browser puo' servire un app.js vecchio dopo un
    aggiornamento (HTML nuovo + JS vecchio = pulsanti senza effetto)."""
    for path in ("/", "/app.js", "/style.css", "/sw.js"):
        res = client.get(path)
        assert res.status_code == 200, path
        assert res.headers["cache-control"] == "no-cache", path
