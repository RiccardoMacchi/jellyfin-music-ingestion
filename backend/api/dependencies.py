"""Dependency injection FastAPI: espone Database/Repository/QueueManager
condivisi, creati una sola volta all'avvio (vedi main.py) e salvati in
`app.state`."""
from __future__ import annotations

from fastapi import Request

from backend.database.repository import DownloadRepository, PlaylistRepository
from backend.queue.manager import QueueManager


def get_download_repo(request: Request) -> DownloadRepository:
    return request.app.state.download_repo


def get_playlist_repo(request: Request) -> PlaylistRepository:
    return request.app.state.playlist_repo


def get_queue_manager(request: Request) -> QueueManager:
    return request.app.state.queue_manager
