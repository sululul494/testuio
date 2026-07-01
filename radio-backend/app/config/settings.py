from __future__ import annotations

import os
from typing import List, Optional
from urllib.parse import quote
from pydantic_settings import BaseSettings
from pydantic import Field, field_validator


class Settings(BaseSettings):
    # ── API ──────────────────────────────────────────────────────────────────
    api_host: str = Field("0.0.0.0", alias="API_HOST")
    api_port: int = Field(8000, alias="API_PORT")
    api_secret: Optional[str] = Field(None, alias="API_SECRET")
    log_level: str = Field("INFO", alias="LOG_LEVEL")

    # ── Icecast ───────────────────────────────────────────────────────────────
    icecast_host: str = Field("localhost", alias="ICECAST_HOST")
    icecast_port: int = Field(8000, alias="ICECAST_PORT")
    icecast_user: str = Field("source", alias="ICECAST_USER")
    icecast_password: str = Field("hackme", alias="ICECAST_PASSWORD")
    icecast_mount: str = Field("/stream", alias="ICECAST_MOUNT")
    icecast_name: str = Field("My Radio", alias="ICECAST_NAME")
    icecast_description: str = Field("Internet Radio", alias="ICECAST_DESCRIPTION")
    icecast_genre: str = Field("Mixed", alias="ICECAST_GENRE")
    icecast_public: bool = Field(False, alias="ICECAST_PUBLIC")

    # ── Audio ─────────────────────────────────────────────────────────────────
    audio_bitrate: int = Field(128, alias="AUDIO_BITRATE")
    audio_samplerate: int = Field(44100, alias="AUDIO_SAMPLERATE")
    audio_channels: int = Field(2, alias="AUDIO_CHANNELS")

    # ── AutoDJ ────────────────────────────────────────────────────────────────
    autodj_playlists: str = Field("", alias="AUTODJ_PLAYLISTS")
    autodj_shuffle: bool = Field(True, alias="AUTODJ_SHUFFLE")
    autodj_refresh_interval: int = Field(3600, alias="AUTODJ_REFRESH_INTERVAL")
    autodj_enabled: bool = Field(True, alias="AUTODJ_ENABLED")

    # ── yt-dlp ───────────────────────────────────────────────────────────────
    ytdlp_format: str = Field("bestaudio/best", alias="YTDLP_FORMAT")
    ytdlp_max_duration: int = Field(7200, alias="YTDLP_MAX_DURATION")
    ytdlp_timeout: int = Field(30, alias="YTDLP_TIMEOUT")
    youtube_cookies_b64: Optional[str] = Field(None, alias="YOUTUBE_COOKIES_B64")

    # ── FFmpeg ────────────────────────────────────────────────────────────────
    ffmpeg_reconnect_delay: int = Field(5, alias="FFMPEG_RECONNECT_DELAY")
    ffmpeg_path: str = Field("ffmpeg", alias="FFMPEG_PATH")

    # ── Watchdog ──────────────────────────────────────────────────────────────
    watchdog_interval: int = Field(10, alias="WATCHDOG_INTERVAL")
    watchdog_max_silence: int = Field(30, alias="WATCHDOG_MAX_SILENCE")

    # ── Logs ──────────────────────────────────────────────────────────────────
    log_dir: str = Field("/app/logs", alias="LOG_DIR")
    log_max_bytes: int = Field(10 * 1024 * 1024, alias="LOG_MAX_BYTES")
    log_backup_count: int = Field(5, alias="LOG_BACKUP_COUNT")

    @field_validator("icecast_mount", mode="before")
    @classmethod
    def ensure_mount_slash(cls, v: str) -> str:
        return v if v.startswith("/") else f"/{v}"

    @property
    def autodj_playlist_list(self) -> List[str]:
        if not self.autodj_playlists:
            return []
        return [p.strip() for p in self.autodj_playlists.split(",") if p.strip()]

    @property
    def icecast_url(self) -> str:
        # URL-encode user and password so special chars (e.g. @ in joy@2007)
        # don't break FFmpeg's URL parser.
        user = quote(self.icecast_user, safe="")
        pwd = quote(self.icecast_password, safe="")
        return (
            f"icecast://{user}:{pwd}"
            f"@{self.icecast_host}:{self.icecast_port}{self.icecast_mount}"
        )

    @property
    def icecast_stats_url(self) -> str:
        return f"http://{self.icecast_host}:{self.icecast_port}/status-json.xsl"

    model_config = {"populate_by_name": True, "env_file": ".env", "extra": "ignore"}


settings = Settings()
