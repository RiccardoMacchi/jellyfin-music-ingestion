"""Fixture condivise. Nessun test qui deve mai contattare la rete/YouTube:
yt-dlp e' sempre mockato (vedi fixture `mock_ytdlp`)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.config import settings  # noqa: E402
from backend.database.db import Database  # noqa: E402
from backend.database.repository import DownloadRepository, PlaylistRepository  # noqa: E402


@pytest.fixture()
def configured_dirs(tmp_path, monkeypatch):
    """Punta MUSIC_DIR/DATA_DIR/DOWNLOAD_DIR a directory temporanee isolate
    per il test corrente, mutando l'oggetto settings gia' istanziato."""
    music_dir = tmp_path / "music"
    data_dir = tmp_path / "data"
    download_dir = tmp_path / "downloads"
    for d in (music_dir, data_dir, download_dir, download_dir / "tmp"):
        d.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(settings, "music_dir", str(music_dir))
    monkeypatch.setattr(settings, "data_dir", str(data_dir))
    monkeypatch.setattr(settings, "download_dir", str(download_dir))
    return {"music": music_dir, "data": data_dir, "downloads": download_dir}


@pytest.fixture()
def db(configured_dirs):
    database = Database(str(configured_dirs["data"] / "test.db"))
    yield database


@pytest.fixture()
def download_repo(db):
    return DownloadRepository(db)


@pytest.fixture()
def playlist_repo(db):
    return PlaylistRepository(db)


@pytest.fixture(scope="session")
def sample_audio_file(tmp_path_factory):
    """Genera un file audio AAC/M4A silenzioso e reale (1s) con ffmpeg, cosi'
    i test di conversione/tag/validazione lavorano su un file davvero
    decodificabile, senza scaricare nulla da YouTube."""
    out_dir = tmp_path_factory.mktemp("fixtures")
    path = out_dir / "sample.m4a"
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono",
            "-t", "1", "-c:a", "aac", "-b:a", "64k", str(path),
        ],
        check=True, capture_output=True,
    )
    return str(path)


@pytest.fixture(scope="session")
def sample_wav_file(tmp_path_factory):
    """Variante WAV (simula un input sorgente diverso da AAC, per testare
    il path di re-encode del converter)."""
    out_dir = tmp_path_factory.mktemp("fixtures_wav")
    path = out_dir / "sample.wav"
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono",
            "-t", "1", str(path),
        ],
        check=True, capture_output=True,
    )
    return str(path)


@pytest.fixture(scope="session")
def sample_cover_bytes(tmp_path_factory):
    from PIL import Image

    out_dir = tmp_path_factory.mktemp("fixtures_cover")
    path = out_dir / "cover_source.png"
    img = Image.new("RGB", (500, 500), color=(120, 80, 40))
    img.save(path, format="PNG")
    return str(path)
