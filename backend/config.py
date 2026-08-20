"""
Configurazione centrale dell'applicazione, letta da variabili d'ambiente.

Il progetto non assume MAI percorsi host: ragiona esclusivamente in termini
dei mount point del container (/music, /data, /downloads). Il mapping verso
il filesystem reale del server e' una responsabilita' di deployment
(Coolify), non del software.
"""
from __future__ import annotations

import os
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Jellyfin Music Ingestion"
    app_version: str = "1.0.0"

    port: int = 8000

    # Mount points dentro il container. NON path host.
    music_dir: str = "/music"
    data_dir: str = "/data"
    download_dir: str = "/downloads"

    audio_format: str = "m4a"      # m4a | mp3 | flac
    audio_bitrate: str = "192K"    # ignorato per flac (lossless)

    max_concurrent_downloads: int = 1

    # Path (dentro il container) a un file cookies.txt in formato Netscape,
    # esportato da un browser loggato su YouTube. Serve ad aggirare il blocco
    # "Sign in to confirm you're not a bot" quando le richieste partono da un
    # IP server. Vuoto = nessun cookie (funziona solo se l'IP non e' bloccato).
    youtube_cookies_file: str = ""

    # Client YouTube usato dall'extractor. Un client alternativo (es. "android"
    # o "web_safari") a volte basta a sbloccare senza cookie. Vuoto = default
    # di yt-dlp. Piu' valori separati da virgola sono ammessi (fallback).
    youtube_player_client: str = ""

    cover_policy: str = "preserve"  # preserve | overwrite

    jellyfin_enabled: bool = False
    jellyfin_url: str = ""
    jellyfin_api_key: str = ""

    tz: str = "Europe/Rome"

    # Sicurezza / hardening
    subprocess_timeout_seconds: int = 900
    max_title_length: int = 180
    rate_limit_per_minute: int = 30

    @property
    def db_path(self) -> str:
        return str(Path(self.data_dir) / "app.db")

    @property
    def tmp_download_path(self) -> str:
        return str(Path(self.download_dir) / "tmp")

    def ensure_directories(self) -> None:
        for path in (self.music_dir, self.data_dir, self.download_dir, self.tmp_download_path):
            Path(path).mkdir(parents=True, exist_ok=True)


settings = Settings()

# TZ per i log/timestamp del processo
os.environ.setdefault("TZ", settings.tz)
