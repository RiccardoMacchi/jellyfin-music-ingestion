"""Modelli Pydantic per le richieste/risposte dell'API."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field, field_validator

from backend.downloader.validator import InvalidURLError, validate_youtube_url


class AnalyzeRequest(BaseModel):
    url: str

    @field_validator("url")
    @classmethod
    def _validate_url(cls, v: str) -> str:
        try:
            return validate_youtube_url(v)
        except InvalidURLError as exc:
            raise ValueError(str(exc)) from exc


class AnalyzeResponse(BaseModel):
    youtube_id: str
    url: str
    raw_title: str
    suggested_title: str
    suggested_artist: str
    suggested_album_artist: str
    featured_artists: list[str] = Field(default_factory=list)
    duration_seconds: Optional[int] = None
    thumbnail_url: str = ""
    channel: str = ""
    is_playlist: bool = False
    parsing_confident: bool = False


class PlaylistAnalyzeRequest(BaseModel):
    url: str

    @field_validator("url")
    @classmethod
    def _validate_url(cls, v: str) -> str:
        try:
            return validate_youtube_url(v)
        except InvalidURLError as exc:
            raise ValueError(str(exc)) from exc


class PlaylistEntryOut(BaseModel):
    youtube_id: str
    title: str
    url: str
    index: int


class PlaylistAnalyzeResponse(BaseModel):
    playlist_youtube_id: str
    title: str
    entries: list[PlaylistEntryOut]


class DownloadCreateRequest(BaseModel):
    url: str
    youtube_id: Optional[str] = None

    title: Optional[str] = None
    artist: Optional[str] = None
    album: Optional[str] = ""
    album_artist: Optional[str] = None
    track_number: Optional[int] = None
    disc_number: Optional[int] = None
    year: Optional[int] = None
    genre: Optional[str] = ""
    composer: Optional[str] = ""
    is_compilation: bool = False

    source_type: str = "single"  # single | playlist_item
    playlist_id: Optional[int] = None
    position_in_playlist: Optional[int] = None
    thumbnail_url: Optional[str] = ""
    duration_seconds: Optional[int] = None

    @field_validator("url")
    @classmethod
    def _validate_url(cls, v: str) -> str:
        try:
            return validate_youtube_url(v)
        except InvalidURLError as exc:
            raise ValueError(str(exc)) from exc

    @field_validator("title", "artist")
    @classmethod
    def _limit_length(cls, v: Optional[str]) -> Optional[str]:
        if v and len(v) > 300:
            raise ValueError("Campo troppo lungo")
        return v


class DownloadOut(BaseModel):
    id: int
    youtube_id: str
    url: str
    title: str
    artist: str
    album: str
    album_artist: str
    track_number: Optional[int]
    disc_number: Optional[int]
    year: Optional[int]
    genre: str
    composer: str
    source_type: str
    playlist_id: Optional[int]
    position_in_playlist: Optional[int]
    duration_seconds: Optional[int]
    thumbnail_url: str
    status: str
    progress: float
    speed: str
    eta: str
    file_path: str
    cover_path: str
    error: str
    retry_count: int
    created_at: str
    started_at: Optional[str]
    completed_at: Optional[str]

    model_config = {"from_attributes": True}


class HealthResponse(BaseModel):
    status: str
    music_dir_writable: bool
    data_dir_writable: bool
    download_dir_writable: bool


class VersionResponse(BaseModel):
    app_name: str
    app_version: str
