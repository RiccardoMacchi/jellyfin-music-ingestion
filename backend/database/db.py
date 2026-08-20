"""
Accesso SQLite a basso livello.

SQLite gestisce un solo writer alla volta: invece di introdurre un driver
asincrono, uso sqlite3 sincrono protetto da un lock di processo e lo eseguo
sempre fuori dal loop asyncio tramite `asyncio.to_thread` (vedi repository.py).
Questo tiene lo schema semplice, testabile e senza dipendenze extra.
"""
from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

_SCHEMA = """
CREATE TABLE IF NOT EXISTS playlists (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    youtube_id TEXT NOT NULL,
    url TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    item_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS downloads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    youtube_id TEXT NOT NULL,
    url TEXT NOT NULL,

    title TEXT NOT NULL DEFAULT '',
    artist TEXT NOT NULL DEFAULT '',
    album TEXT NOT NULL DEFAULT '',
    album_artist TEXT NOT NULL DEFAULT '',
    track_number INTEGER,
    disc_number INTEGER,
    year INTEGER,
    genre TEXT NOT NULL DEFAULT '',
    composer TEXT NOT NULL DEFAULT '',

    source_type TEXT NOT NULL DEFAULT 'single',
    playlist_id INTEGER,
    position_in_playlist INTEGER,

    duration_seconds INTEGER,
    thumbnail_url TEXT NOT NULL DEFAULT '',

    status TEXT NOT NULL DEFAULT 'PENDING',
    progress REAL NOT NULL DEFAULT 0,
    speed TEXT NOT NULL DEFAULT '',
    eta TEXT NOT NULL DEFAULT '',

    file_path TEXT NOT NULL DEFAULT '',
    cover_path TEXT NOT NULL DEFAULT '',
    error TEXT NOT NULL DEFAULT '',

    retry_count INTEGER NOT NULL DEFAULT 0,

    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    started_at TEXT,
    completed_at TEXT,

    FOREIGN KEY (playlist_id) REFERENCES playlists(id)
);

CREATE INDEX IF NOT EXISTS idx_downloads_status ON downloads(status);
CREATE INDEX IF NOT EXISTS idx_downloads_youtube_id ON downloads(youtube_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_downloads_dedupe
    ON downloads(youtube_id)
    WHERE status NOT IN ('FAILED', 'CANCELLED');
"""

_write_lock = threading.Lock()


class Database:
    """Wrapper minimale: una connessione per thread, schema idempotente."""

    def __init__(self, path: str):
        self.path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn"):
            conn = sqlite3.connect(self.path, timeout=30, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            self._local.conn = conn
        return self._local.conn

    def _init_schema(self) -> None:
        with _write_lock:
            conn = self._connect()
            conn.executescript(_SCHEMA)
            conn.commit()

    @contextmanager
    def cursor(self) -> Iterator[sqlite3.Cursor]:
        conn = self._connect()
        cur = conn.cursor()
        try:
            yield cur
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            cur.close()

    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        with _write_lock, self.cursor() as cur:
            cur.execute(sql, params)
            return cur

    def query(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        conn = self._connect()
        cur = conn.execute(sql, params)
        rows = cur.fetchall()
        cur.close()
        return rows

    def query_one(self, sql: str, params: tuple = ()) -> sqlite3.Row | None:
        rows = self.query(sql, params)
        return rows[0] if rows else None
