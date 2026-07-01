from __future__ import annotations

from typing import List, Optional
from pydantic import BaseModel, Field


class PlayRequest(BaseModel):
    query: Optional[str] = None
    url: Optional[str] = None
    requested_by: str = "API"

    def is_url(self) -> bool:
        return self.url is not None and self.url.strip() != ""

    def get_input(self) -> str:
        if self.is_url():
            return self.url.strip()
        if self.query and self.query.strip():
            return f"ytsearch1:{self.query.strip()}"
        raise ValueError("Either 'query' or 'url' must be provided")


class RemoveRequest(BaseModel):
    position: int = Field(..., ge=1, description="1-based queue position to remove")


class TrackInfo(BaseModel):
    position: int
    title: str
    duration: str
    url: str
    thumbnail: str
    requested_by: str = "API"


class NowPlayingResponse(BaseModel):
    title: str
    channel: str
    duration: str
    elapsed: str
    remaining: str
    thumbnail: str
    source_url: str
    is_autodj: bool
    queue_position: Optional[int]
    playing: bool


class QueueResponse(BaseModel):
    queue: List[TrackInfo]
    total: int


class StatusResponse(BaseModel):
    playing: bool
    connected_to_icecast: bool
    queue_length: int
    listeners: int
    uptime: str
    cpu_usage: float
    memory_usage: float
    bitrate: int
    autodj_enabled: bool
    current_source: str


class HealthResponse(BaseModel):
    status: str
    icecast: bool
    ffmpeg: bool
    queue: bool
    player: bool
    api: bool


class StatsResponse(BaseModel):
    total_tracks_played: int
    total_skips: int
    total_errors: int
    uptime_seconds: float
    autodj_tracks_played: int
    user_tracks_played: int
    current_listeners: int
    peak_listeners: int


class PlayResponse(BaseModel):
    success: bool
    message: str
    track: Optional[TrackInfo] = None


class SkipResponse(BaseModel):
    success: bool
    message: str


class ClearResponse(BaseModel):
    success: bool
    cleared: int


class RemoveResponse(BaseModel):
    success: bool
    message: str
