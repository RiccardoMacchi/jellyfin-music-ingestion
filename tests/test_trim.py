"""
Taglio intro/outro: sia in fase di conversione (nuovi download) sia sui
brani gia' in libreria (stream copy + copia dei tag + move atomico).
FFmpeg/mutagen reali, nessuna rete.
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from mutagen.mp4 import MP4

from backend.audio.converter import ConversionError, _trim_args, convert_audio
from backend.database.models import DownloadRecord, DownloadStatus
from backend.library.trimmer import trim_library_file
from backend.metadata.normalizer import TrackMetadata
from backend.metadata.tagger import write_tags
from backend.queue.manager import QueueManager


def _duration(path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)],
        check=True, capture_output=True, text=True,
    ).stdout
    return float(json.loads(out)["format"]["duration"])


@pytest.fixture(scope="session")
def long_audio_file(tmp_path_factory):
    """M4A/AAC reale di 20 secondi (un tono, non silenzio)."""
    path = tmp_path_factory.mktemp("fixtures_long") / "long.m4a"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=20",
         "-c:a", "aac", "-b:a", "96k", str(path)],
        check=True, capture_output=True,
    )
    return str(path)


def test_trim_args_rejects_too_long_trim():
    with pytest.raises(ConversionError):
        _trim_args(20.0, 10, 8)


def test_trim_args_noop_when_nothing_to_trim():
    assert _trim_args(20.0, 0, 0) == []


@pytest.mark.asyncio
async def test_convert_audio_applies_trim(tmp_path, long_audio_file):
    dest = tmp_path / "out.m4a"
    await convert_audio(long_audio_file, str(dest), "m4a", trim_start=3, trim_end=5)
    assert _duration(dest) == pytest.approx(12, abs=0.3)


@pytest.mark.asyncio
async def test_convert_audio_trim_with_reencode(tmp_path, long_audio_file):
    dest = tmp_path / "out.mp3"
    await convert_audio(long_audio_file, str(dest), "mp3", trim_start=4)
    assert _duration(dest) == pytest.approx(16, abs=0.3)


@pytest.mark.asyncio
async def test_trim_library_file_keeps_tags_and_cover(configured_dirs, long_audio_file, sample_cover_bytes):
    import io
    from PIL import Image

    target = configured_dirs["music"] / "Artist" / "Singles" / "Song.m4a"
    target.parent.mkdir(parents=True)
    shutil.copyfile(long_audio_file, target)

    buf = io.BytesIO()
    Image.open(sample_cover_bytes).convert("RGB").save(buf, format="JPEG")
    write_tags(str(target), TrackMetadata(title="Song", artist="Artist", album_artist="Artist",
                                          genre="Pop"), cover_bytes=buf.getvalue())

    new_duration = await trim_library_file(str(target), 2, 3, job_id=1)

    assert new_duration == pytest.approx(15, abs=0.3)
    assert _duration(target) == pytest.approx(15, abs=0.3)
    tags = MP4(str(target))
    assert tags["\xa9nam"] == ["Song"]
    assert tags["\xa9gen"] == ["Pop"]
    assert "covr" in tags
    # nessun file temporaneo lasciato in giro
    assert not list(Path(configured_dirs["downloads"], "tmp").glob("trim_*"))


@pytest.mark.asyncio
async def test_trim_library_file_too_long_leaves_original_intact(configured_dirs, long_audio_file):
    target = configured_dirs["music"] / "Artist" / "Singles" / "Song.m4a"
    target.parent.mkdir(parents=True)
    shutil.copyfile(long_audio_file, target)
    before = target.read_bytes()

    with pytest.raises(ConversionError):
        await trim_library_file(str(target), 10, 10, job_id=2)

    assert target.read_bytes() == before


@pytest.fixture()
def client(configured_dirs, monkeypatch):
    monkeypatch.setattr(QueueManager, "start", lambda self: None)
    from backend.main import app
    with TestClient(app) as c:
        yield c


def test_api_trim_on_pending_job_only_stores_values(client):
    created = client.post("/api/download", json={
        "url": "https://youtu.be/t1", "youtube_id": "t1", "title": "T", "artist": "A",
        "trim_start_seconds": 5,
    }).json()
    assert created["trim_start_seconds"] == 5

    res = client.post(f"/api/downloads/{created['id']}/trim",
                      json={"trim_start_seconds": 8, "trim_end_seconds": 2})
    assert res.status_code == 200
    body = res.json()
    assert body["trim_start_seconds"] == 8
    assert body["trim_end_seconds"] == 2


def test_api_trim_rejects_negative_values(client):
    res = client.post("/api/download", json={
        "url": "https://youtu.be/t2", "youtube_id": "t2", "title": "T", "artist": "A",
        "trim_start_seconds": -1,
    })
    assert res.status_code == 422


def test_api_trim_completed_job_trims_file(client, configured_dirs, long_audio_file):
    from backend.database.db import Database
    from backend.database.repository import DownloadRepository
    from backend.config import settings

    target = configured_dirs["music"] / "A" / "Singles" / "T.m4a"
    target.parent.mkdir(parents=True)
    shutil.copyfile(long_audio_file, target)

    repo = DownloadRepository(Database(settings.db_path))
    record = repo.create(DownloadRecord(youtube_id="t3", url="https://youtu.be/t3", title="T", artist="A",
                                        status=DownloadStatus.COMPLETED.value, file_path=str(target),
                                        duration_seconds=20))

    res = client.post(f"/api/downloads/{record.id}/trim", json={"trim_start_seconds": 4})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["trim_start_seconds"] == 4
    assert body["duration_seconds"] == 16

    # un secondo taglio si somma al primo
    res = client.post(f"/api/downloads/{record.id}/trim", json={"trim_end_seconds": 1})
    assert res.json()["trim_end_seconds"] == 1
    assert res.json()["duration_seconds"] == 15


@pytest.mark.asyncio
async def test_pipeline_applies_trim_and_detected_genre(configured_dirs, download_repo, monkeypatch, long_audio_file):
    """Pipeline completa (yt-dlp mockato): il taglio richiesto in coda viene
    applicato, la durata aggiornata e il genere riconosciuto scritto nel tag."""
    from backend.config import settings
    from backend.downloader.ytdlp_client import VideoInfo
    from backend.genre.detector import GenreResult
    from backend.queue import worker as worker_module

    def fake_download(url, output_dir, filename_stem, progress_hook=None):
        dest = Path(output_dir) / f"{filename_stem}.m4a"
        shutil.copyfile(long_audio_file, dest)
        return str(dest), VideoInfo(id="p1", title="A - S", uploader="A", duration=20,
                                    thumbnail="", webpage_url=url, raw={})

    async def fake_detect(artist, title):
        assert artist == "Artist A"  # featuring rimosso per la ricerca
        return GenreResult(genre="Electronic", source="deezer")

    monkeypatch.setattr(worker_module, "download_audio", fake_download)
    monkeypatch.setattr(worker_module, "detect_genre", fake_detect)
    monkeypatch.setattr(settings, "genre_autodetect", True)

    record = download_repo.create(DownloadRecord(
        youtube_id="p1", url="https://youtu.be/p1", title="Song", artist="Artist A feat. B",
        trim_start_seconds=5, trim_end_seconds=3,
    ))
    await worker_module.process_job(record, download_repo)

    updated = download_repo.get(record.id)
    assert updated.status == DownloadStatus.COMPLETED.value, updated.error
    assert updated.duration_seconds == 12
    assert updated.genre == "Electronic" and updated.genre_source == "deezer"
    assert MP4(updated.file_path)["\xa9gen"] == ["Electronic"]
    assert _duration(updated.file_path) == pytest.approx(12, abs=0.3)
