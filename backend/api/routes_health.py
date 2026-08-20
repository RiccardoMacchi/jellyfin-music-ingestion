"""Health/version, usati anche dal Docker HEALTHCHECK."""
from __future__ import annotations

import os

from fastapi import APIRouter

from backend.api.schemas import HealthResponse, VersionResponse
from backend.config import settings

router = APIRouter(prefix="/api", tags=["system"])


def _writable(path: str) -> bool:
    return os.access(path, os.W_OK) if os.path.isdir(path) else False


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        music_dir_writable=_writable(settings.music_dir),
        data_dir_writable=_writable(settings.data_dir),
        download_dir_writable=_writable(settings.download_dir),
    )


@router.get("/version", response_model=VersionResponse)
async def version() -> VersionResponse:
    return VersionResponse(app_name=settings.app_name, app_version=settings.app_version)
