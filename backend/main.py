"""
Entry point dell'applicazione FastAPI.

Responsabilita':
- inizializzare DB/repository/queue manager (una sola volta, in app.state);
- recuperare i job rimasti "in volo" da un eventuale crash precedente;
- avviare il loop della coda in background;
- montare le API sotto /api e servire il frontend statico sulla radice;
- gestire un graceful shutdown (SIGTERM) fermando la coda in modo pulito.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from backend.api.routes_analyze import router as analyze_router
from backend.api.routes_downloads import router as downloads_router
from backend.api.routes_events import router as events_router
from backend.api.routes_health import router as health_router
from backend.config import settings
from backend.database.db import Database
from backend.database.repository import DownloadRepository, PlaylistRepository
from backend.queue.manager import QueueManager
from backend.utils.logging import configure_logging, get_logger

configure_logging()
logger = get_logger(__name__)

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend" / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.ensure_directories()

    db = Database(settings.db_path)
    download_repo = DownloadRepository(db)
    playlist_repo = PlaylistRepository(db)

    recovered = download_repo.recover_stuck_jobs()
    if recovered:
        logger.warning("Recuperati %s job interrotti da un crash/restart precedente", recovered)

    queue_manager = QueueManager(download_repo)

    app.state.db = db
    app.state.download_repo = download_repo
    app.state.playlist_repo = playlist_repo
    app.state.queue_manager = queue_manager

    queue_manager.start()
    logger.info("%s v%s avviato", settings.app_name, settings.app_version)

    try:
        yield
    finally:
        logger.info("Arresto in corso (graceful shutdown)...")
        await queue_manager.stop()
        logger.info("Coda fermata correttamente.")


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    lifespan=lifespan,
)

app.include_router(health_router)
app.include_router(analyze_router)
app.include_router(downloads_router)
app.include_router(events_router)

if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
