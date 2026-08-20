"""
Test end-to-end della pipeline di ingestion (backend/queue/worker.py) con
yt-dlp completamente mockato (nessuna rete) ma FFmpeg/mutagen REALI: verifica
che un file audio finisca davvero, taggato e validato, al percorso giusto
sotto MUSIC_DIR, in modo atomico.
"""
import shutil
from pathlib import Path

import pytest

from backend.database.models import DownloadRecord, DownloadStatus
from backend.downloader.ytdlp_client import VideoInfo
from backend.queue import worker as worker_module


def fake_download_audio_factory(sample_audio_file, sample_cover_bytes):
    def _fake(url, output_dir, filename_stem, progress_hook=None):
        dest_audio = Path(output_dir) / f"{filename_stem}.m4a"
        shutil.copyfile(sample_audio_file, dest_audio)
        dest_thumb = Path(output_dir) / f"{filename_stem}.png"
        shutil.copyfile(sample_cover_bytes, dest_thumb)
        if progress_hook:
            progress_hook({"status": "downloading", "downloaded_bytes": 50, "total_bytes": 100})
            progress_hook({"status": "finished"})
        info = VideoInfo(
            id="abc123", title="Artist A - Song", uploader="Artist A",
            duration=180, thumbnail="https://example.com/t.jpg",
            webpage_url=url, raw={},
        )
        return str(dest_audio), info
    return _fake


@pytest.mark.asyncio
async def test_pipeline_completes_and_places_file_in_library(
    configured_dirs, download_repo, monkeypatch, sample_audio_file, sample_cover_bytes
):
    monkeypatch.setattr(
        worker_module, "download_audio",
        fake_download_audio_factory(sample_audio_file, sample_cover_bytes),
    )

    record = download_repo.create(DownloadRecord(
        youtube_id="abc123", url="https://youtu.be/abc123",
        title="Song", artist="Artist A", album="Great Album", album_artist="Artist A",
        track_number=1,
    ))

    await worker_module.process_job(record, download_repo)

    updated = download_repo.get(record.id)
    assert updated.status == DownloadStatus.COMPLETED.value
    assert updated.file_path

    final_file = Path(updated.file_path)
    assert final_file.exists()
    assert final_file.parent.name == "Great Album"
    assert final_file.parent.parent.name == "Artist A"
    assert (final_file.parent / "cover.jpg").exists()


@pytest.mark.asyncio
async def test_pipeline_marks_failed_on_download_error(configured_dirs, download_repo, monkeypatch):
    from backend.downloader.ytdlp_client import DownloadError

    def _boom(url, output_dir, filename_stem, progress_hook=None):
        raise DownloadError("simulated network failure")

    monkeypatch.setattr(worker_module, "download_audio", _boom)

    record = download_repo.create(DownloadRecord(
        youtube_id="fail1", url="https://youtu.be/fail1", title="X", artist="Y",
    ))
    await worker_module.process_job(record, download_repo)

    updated = download_repo.get(record.id)
    assert updated.status == DownloadStatus.FAILED.value
    assert "simulated network failure" in updated.error


@pytest.mark.asyncio
async def test_pipeline_skips_when_target_file_already_exists(
    configured_dirs, download_repo, monkeypatch, sample_audio_file, sample_cover_bytes
):
    monkeypatch.setattr(
        worker_module, "download_audio",
        fake_download_audio_factory(sample_audio_file, sample_cover_bytes),
    )

    existing_path = Path(configured_dirs["music"]) / "Artist A" / "Singles" / "Song.m4a"
    existing_path.parent.mkdir(parents=True, exist_ok=True)
    existing_path.write_bytes(b"already here")

    record = download_repo.create(DownloadRecord(
        youtube_id="dup-file", url="https://youtu.be/dup-file",
        title="Song", artist="Artist A",  # nessun album -> stesso path di un Singles esistente
    ))
    await worker_module.process_job(record, download_repo)

    updated = download_repo.get(record.id)
    assert updated.status == DownloadStatus.SKIPPED.value
    assert existing_path.read_bytes() == b"already here"  # MAI sovrascritto


def test_cancellation_hook_raises_when_requested(download_repo):
    record = download_repo.create(DownloadRecord(youtube_id="cancel1", url="https://youtu.be/cancel1"))
    worker_module.request_cancel(record.id)
    hook = worker_module._make_progress_hook(download_repo, record.id)

    with pytest.raises(worker_module.JobCancelled):
        hook({"status": "downloading", "downloaded_bytes": 1, "total_bytes": 10})

    worker_module._cancel_requested.discard(record.id)  # pulizia stato globale del modulo


def test_progress_hook_updates_repo(download_repo):
    record = download_repo.create(DownloadRecord(youtube_id="prog1", url="https://youtu.be/prog1"))
    hook = worker_module._make_progress_hook(download_repo, record.id)

    hook({"status": "downloading", "downloaded_bytes": 25, "total_bytes": 100, "_speed_str": "1MiB/s", "_eta_str": "00:05"})

    updated = download_repo.get(record.id)
    assert updated.progress == 25.0
    assert updated.speed == "1MiB/s"
    assert updated.eta == "00:05"
