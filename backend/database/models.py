"""
Modelli dato (dataclass) per righe della tabella `downloads` e `playlists`.

Uso dataclass invece di ORM: SQLite + schema semplice non giustificano un
ORM completo, e le dataclass restano leggibili e tipizzate.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class DownloadStatus(str, Enum):
    PENDING = "PENDING"
    ANALYZING = "ANALYZING"
    DOWNLOADING = "DOWNLOADING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"
    CANCELLED = "CANCELLED"


# Stati considerati "attivi": se un job si trova in uno di questi stati al
# riavvio del processo, significa che il worker precedente e' crashato
# mentre lo stava processando -> va rimesso in PENDING per essere ripreso.
RECOVERABLE_STATUSES = (DownloadStatus.DOWNLOADING, DownloadStatus.PROCESSING, DownloadStatus.ANALYZING)


@dataclass
class DownloadRecord:
    id: Optional[int] = None
    youtube_id: str = ""
    url: str = ""

    title: str = ""
    artist: str = ""
    album: str = ""
    album_artist: str = ""
    track_number: Optional[int] = None
    disc_number: Optional[int] = None
    year: Optional[int] = None
    genre: str = ""
    composer: str = ""

    source_type: str = "single"  # single | playlist_item
    playlist_id: Optional[int] = None
    position_in_playlist: Optional[int] = None

    duration_seconds: Optional[int] = None
    thumbnail_url: str = ""

    status: str = DownloadStatus.PENDING.value
    progress: float = 0.0
    speed: str = ""
    eta: str = ""

    file_path: str = ""
    cover_path: str = ""
    error: str = ""

    retry_count: int = 0

    created_at: str = ""
    started_at: Optional[str] = None
    completed_at: Optional[str] = None


@dataclass
class PlaylistRecord:
    id: Optional[int] = None
    youtube_id: str = ""
    url: str = ""
    title: str = ""
    item_count: int = 0
    created_at: str = ""
