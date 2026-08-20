"""
Repository: unico punto di accesso alle tabelle `downloads` / `playlists`.

Tutte le funzioni sono sincrone (SQLite) e vanno chiamate da codice async
tramite `asyncio.to_thread`. Questo evita di dover mockare un driver async
nei test e mantiene gli accessi al DB semplici da ragionare.
"""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from typing import Optional

from backend.database.db import Database
from backend.database.models import (
    RECOVERABLE_STATUSES,
    DownloadRecord,
    DownloadStatus,
    PlaylistRecord,
)

_DOWNLOAD_FIELDS = [
    "youtube_id", "url", "title", "artist", "album", "album_artist",
    "track_number", "disc_number", "year", "genre", "composer",
    "source_type", "playlist_id", "position_in_playlist",
    "duration_seconds", "thumbnail_url", "status", "progress", "speed",
    "eta", "file_path", "cover_path", "error", "retry_count",
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _row_to_download(row) -> DownloadRecord:
    d = dict(row)
    return DownloadRecord(**d)


class DownloadRepository:
    def __init__(self, db: Database):
        self.db = db

    # ---- creazione -------------------------------------------------
    def create(self, record: DownloadRecord) -> DownloadRecord:
        values = {k: getattr(record, k) for k in _DOWNLOAD_FIELDS}
        cols = ", ".join(values.keys())
        placeholders = ", ".join("?" for _ in values)
        cur = self.db.execute(
            f"INSERT INTO downloads ({cols}) VALUES ({placeholders})",
            tuple(values.values()),
        )
        record.id = cur.lastrowid
        row = self.db.query_one("SELECT * FROM downloads WHERE id = ?", (record.id,))
        return _row_to_download(row)

    # ---- lettura -----------------------------------------------------
    def get(self, download_id: int) -> Optional[DownloadRecord]:
        row = self.db.query_one("SELECT * FROM downloads WHERE id = ?", (download_id,))
        return _row_to_download(row) if row else None

    def list(self, status: Optional[str] = None, limit: int = 200) -> list[DownloadRecord]:
        if status:
            rows = self.db.query(
                "SELECT * FROM downloads WHERE status = ? ORDER BY id DESC LIMIT ?",
                (status, limit),
            )
        else:
            rows = self.db.query("SELECT * FROM downloads ORDER BY id DESC LIMIT ?", (limit,))
        return [_row_to_download(r) for r in rows]

    def next_pending(self) -> Optional[DownloadRecord]:
        row = self.db.query_one(
            "SELECT * FROM downloads WHERE status = ? ORDER BY id ASC LIMIT 1",
            (DownloadStatus.PENDING.value,),
        )
        return _row_to_download(row) if row else None

    # ---- duplicate detection ----------------------------------------
    def find_by_youtube_id(self, youtube_id: str) -> Optional[DownloadRecord]:
        """Livello 1/2 di duplicate detection: stesso video YouTube gia'
        presente (in coda, in corso o completato)."""
        row = self.db.query_one(
            "SELECT * FROM downloads WHERE youtube_id = ? AND status NOT IN "
            "('FAILED', 'CANCELLED') ORDER BY id DESC LIMIT 1",
            (youtube_id,),
        )
        return _row_to_download(row) if row else None

    def find_by_metadata(self, artist: str, album: str, title: str, track_number) -> Optional[DownloadRecord]:
        """Livello 4 di duplicate detection: stesso artist+album+track+title,
        usato quando lo stesso brano arriva da URL diverse (es. video
        ufficiale + lyric video)."""
        row = self.db.query_one(
            "SELECT * FROM downloads WHERE status = 'COMPLETED' AND artist = ? "
            "AND album = ? AND title = ? AND (track_number IS ? OR track_number = ?)",
            (artist, album, title, track_number, track_number),
        )
        return _row_to_download(row) if row else None

    def find_by_file_path(self, file_path: str) -> Optional[DownloadRecord]:
        """Livello 3: path finale gia' occupato da un altro download completato."""
        row = self.db.query_one(
            "SELECT * FROM downloads WHERE file_path = ? AND status = 'COMPLETED'",
            (file_path,),
        )
        return _row_to_download(row) if row else None

    # ---- aggiornamenti -------------------------------------------------
    def update_status(self, download_id: int, status: DownloadStatus, error: str = "") -> None:
        fields = ["status = ?"]
        params: list = [status.value]
        if status == DownloadStatus.DOWNLOADING:
            fields.append("started_at = COALESCE(started_at, ?)")
            params.append(_now())
        if status in (DownloadStatus.COMPLETED, DownloadStatus.FAILED, DownloadStatus.CANCELLED, DownloadStatus.SKIPPED):
            fields.append("completed_at = ?")
            params.append(_now())
        if error:
            fields.append("error = ?")
            params.append(error)
        params.append(download_id)
        self.db.execute(f"UPDATE downloads SET {', '.join(fields)} WHERE id = ?", tuple(params))

    def update_progress(self, download_id: int, progress: float, speed: str = "", eta: str = "") -> None:
        self.db.execute(
            "UPDATE downloads SET progress = ?, speed = ?, eta = ? WHERE id = ?",
            (progress, speed, eta, download_id),
        )

    def update_metadata(self, download_id: int, **fields) -> None:
        if not fields:
            return
        allowed = {k: v for k, v in fields.items() if k in _DOWNLOAD_FIELDS}
        if not allowed:
            return
        set_clause = ", ".join(f"{k} = ?" for k in allowed)
        params = tuple(allowed.values()) + (download_id,)
        self.db.execute(f"UPDATE downloads SET {set_clause} WHERE id = ?", params)

    def set_file_path(self, download_id: int, file_path: str, cover_path: str = "") -> None:
        self.db.execute(
            "UPDATE downloads SET file_path = ?, cover_path = ? WHERE id = ?",
            (file_path, cover_path, download_id),
        )

    def increment_retry(self, download_id: int) -> None:
        self.db.execute(
            "UPDATE downloads SET retry_count = retry_count + 1 WHERE id = ?",
            (download_id,),
        )

    def delete(self, download_id: int) -> None:
        self.db.execute("DELETE FROM downloads WHERE id = ?", (download_id,))

    # ---- recovery dopo crash -----------------------------------------
    def recover_stuck_jobs(self) -> int:
        """Rimette in PENDING tutti i job rimasti "in volo" da un run
        precedente (es. processo terminato durante DOWNLOADING/PROCESSING).
        Da chiamare una sola volta all'avvio dell'app."""
        placeholders = ", ".join("?" for _ in RECOVERABLE_STATUSES)
        cur = self.db.execute(
            f"UPDATE downloads SET status = ?, progress = 0, speed = '', eta = '' "
            f"WHERE status IN ({placeholders})",
            (DownloadStatus.PENDING.value, *[s.value for s in RECOVERABLE_STATUSES]),
        )
        return cur.rowcount


class PlaylistRepository:
    def __init__(self, db: Database):
        self.db = db

    def create(self, record: PlaylistRecord) -> PlaylistRecord:
        cur = self.db.execute(
            "INSERT INTO playlists (youtube_id, url, title, item_count) VALUES (?, ?, ?, ?)",
            (record.youtube_id, record.url, record.title, record.item_count),
        )
        record.id = cur.lastrowid
        return record

    def get(self, playlist_id: int) -> Optional[PlaylistRecord]:
        row = self.db.query_one("SELECT * FROM playlists WHERE id = ?", (playlist_id,))
        return PlaylistRecord(**dict(row)) if row else None
