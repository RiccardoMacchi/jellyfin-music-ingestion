"""Endpoint di analisi (preview): NON scaricano nulla, solo metadata."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException

from backend.api.schemas import (
    AnalyzeRequest,
    AnalyzeResponse,
    PlaylistAnalyzeRequest,
    PlaylistAnalyzeResponse,
    PlaylistEntryOut,
)
from backend.downloader.validator import is_playlist_url
from backend.downloader.ytdlp_client import DownloadError, extract_playlist_info, extract_video_info
from backend.metadata.parser import parse_title
from backend.security.rate_limit import rate_limiter

router = APIRouter(prefix="/api", tags=["analyze"], dependencies=[Depends(rate_limiter)])


@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze(payload: AnalyzeRequest) -> AnalyzeResponse:
    try:
        info = await asyncio.to_thread(extract_video_info, payload.url)
    except DownloadError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    parsed = parse_title(info.title, channel_name=info.uploader)

    return AnalyzeResponse(
        youtube_id=info.id,
        url=info.webpage_url,
        raw_title=info.title,
        suggested_title=parsed.title,
        suggested_artist=parsed.artist or info.uploader,
        suggested_album_artist=parsed.artist or info.uploader,
        featured_artists=parsed.featured_artists or [],
        duration_seconds=info.duration,
        thumbnail_url=info.thumbnail,
        channel=info.uploader,
        is_playlist=is_playlist_url(payload.url),
        parsing_confident=parsed.confident,
    )


@router.post("/playlist/analyze", response_model=PlaylistAnalyzeResponse)
async def analyze_playlist(payload: PlaylistAnalyzeRequest) -> PlaylistAnalyzeResponse:
    try:
        playlist = await asyncio.to_thread(extract_playlist_info, payload.url)
    except DownloadError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if not playlist.entries:
        raise HTTPException(status_code=422, detail="La playlist non contiene elementi validi")

    return PlaylistAnalyzeResponse(
        playlist_youtube_id=playlist.id,
        title=playlist.title,
        entries=[
            PlaylistEntryOut(youtube_id=e.id, title=e.title, url=e.url, index=e.index)
            for e in playlist.entries
        ],
    )
