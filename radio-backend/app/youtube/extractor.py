from __future__ import annotations

import base64
import os
import re
import time
from typing import Any, Dict, Optional

import yt_dlp

from app.config.settings import settings
from app.logger.setup import get_logger
from app.models.schemas import TrackInfo

logger = get_logger("ytdlp")

COOKIES_PATH = "/tmp/youtube_cookies.txt"


def _write_cookies() -> None:
    """Decode base64 cookies from env and write to a netscape cookies file for yt-dlp."""
    if not settings.youtube_cookies_b64:
        return
    try:
        raw = base64.b64decode(settings.youtube_cookies_b64).decode("utf-8", errors="replace")
        with open(COOKIES_PATH, "w", encoding="utf-8") as f:
            f.write(raw)
        logger.info("YouTube cookies file written")
    except Exception as exc:
        logger.error(f"Failed to write YouTube cookies: {exc}")


# Write cookies once at module load so all yt-dlp instances use them.
_write_cookies()

PRIVATE_ERRORS = (
    "private video",
    "members-only",
    "member-only",
    "age-restricted",
    "age restricted",
    "unavailable",
    "this video has been removed",
    "video unavailable",
    "blocked",
    "not available",
    "login required",
    "sign in",
)

LIVE_STREAM_ERRORS = (
    "is a live stream",
    "live stream",
    "live event",
)


class ExtractionError(Exception):
    pass


class SkippableError(ExtractionError):
    pass


class YouTubeExtractor:
    def __init__(self) -> None:
        self._base_opts: Dict[str, Any] = {
            "format": settings.ytdlp_format,
            "quiet": True,
            "no_warnings": False,
            "noplaylist": True,
            "socket_timeout": settings.ytdlp_timeout,
            "source_address": "0.0.0.0",
            "http_headers": {
                "User-Agent": (
                    "Mozilla/5.0 (X11; Linux x86_64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                "Accept-Language": "en-US,en;q=0.9",
            },
            "extractor_args": {
                "youtube": {
                    "player_client": ["tv_embedded", "web"],
                    "player_skip": ["webpage", "configs"],
                }
            },
            "postprocessors": [],
        }
        if os.path.exists(COOKIES_PATH):
            self._base_opts["cookies"] = COOKIES_PATH
            logger.info("Using YouTube cookies from %s", COOKIES_PATH)

    def _ydl(self, extra: Optional[Dict[str, Any]] = None) -> yt_dlp.YoutubeDL:
        opts = dict(self._base_opts)
        if extra:
            opts.update(extra)
        return yt_dlp.YoutubeDL(opts)

    def extract_info(self, url: str, requested_by: str = "API") -> TrackInfo:
        logger.info(f"Extracting info for: {url!r}")
        try:
            with self._ydl() as ydl:
                info = ydl.extract_info(url, download=False)
        except yt_dlp.utils.DownloadError as exc:
            msg = str(exc).lower()
            logger.warning(f"yt-dlp DownloadError for {url!r}: {msg[:200]}")
            self._raise_for_message(msg, url)
            raise ExtractionError(f"yt-dlp error for {url!r}: {exc}") from exc
        except Exception as exc:
            logger.error(f"Unexpected yt-dlp error for {url!r}: {exc}", exc_info=True)
            raise ExtractionError(str(exc)) from exc

        if info is None:
            logger.warning(f"yt-dlp returned None for {url!r}")
            raise SkippableError(f"No info returned for {url!r}")

        if info.get("_type") == "playlist":
            entries = [e for e in (info.get("entries") or []) if e]
            if not entries:
                raise SkippableError(f"Playlist {url!r} is empty or all entries unavailable")
            info = entries[0]

        if info.get("is_live"):
            raise SkippableError(f"Live streams are not supported: {info.get('title')!r}")

        duration_secs: int = info.get("duration") or 0
        if duration_secs > settings.ytdlp_max_duration:
            raise SkippableError(
                f"Track too long ({duration_secs}s > {settings.ytdlp_max_duration}s): "
                f"{info.get('title')!r}"
            )

        audio_url = self._pick_audio_url(info)
        if not audio_url:
            raise SkippableError(f"No audio URL found for {info.get('title')!r}")

        track = TrackInfo(
            position=0,
            title=self._sanitize(info.get("title", "Unknown")),
            duration=self._format_duration(duration_secs),
            url=audio_url,
            thumbnail=info.get("thumbnail", ""),
            requested_by=requested_by,
        )
        logger.info(f"Extracted: {track.title!r} ({track.duration})")
        return track

    def extract_playlist_urls(self, playlist_url: str) -> list[str]:
        logger.info(f"Expanding playlist: {playlist_url!r}")
        opts = dict(self._base_opts)
        opts.update({
            "extract_flat": True,
            "quiet": True,
            "no_warnings": True,
            "noplaylist": False,
            "ignoreerrors": True,
            "socket_timeout": settings.ytdlp_timeout,
        })
        try:
            with self._ydl(opts) as ydl:
                info = ydl.extract_info(playlist_url, download=False)
        except Exception as exc:
            logger.error(f"Failed to expand playlist {playlist_url!r}: {exc}", exc_info=True)
            return []

        if not info:
            return []

        entries = list(info.get("entries") or [])
        urls = []
        for entry in entries:
            if not entry:
                continue
            vid_id = entry.get("id") or ""
            url = entry.get("url") or ""
            webpage = entry.get("webpage_url") or ""
            if webpage.startswith("http"):
                urls.append(webpage)
            elif url.startswith("http"):
                urls.append(url)
            elif vid_id:
                urls.append(f"https://www.youtube.com/watch?v={vid_id}")
        logger.info(f"Playlist expanded to {len(urls)} tracks")
        return urls

    def search(self, query: str, requested_by: str = "API") -> TrackInfo:
        search_url = f"ytsearch1:{query}"
        return self.extract_info(search_url, requested_by=requested_by)

    def _pick_audio_url(self, info: Dict[str, Any]) -> Optional[str]:
        url = info.get("url")
        if url:
            return url
        formats = info.get("formats") or []
        # First try audio-only formats
        audio_formats = [
            f for f in formats
            if f.get("vcodec") == "none" and f.get("url")
        ]
        if audio_formats:
            best = sorted(
                audio_formats,
                key=lambda f: f.get("abr") or f.get("tbr") or 0,
                reverse=True,
            )
            return best[0]["url"]
        # Fallback: any format with audio (ios client uses muxed audio+video)
        # Prefer formats with audio bitrate
        mixed_formats = [
            f for f in formats
            if f.get("url") and f.get("acodec") != "none"
        ]
        if mixed_formats:
            best = sorted(
                mixed_formats,
                key=lambda f: (f.get("abr") or 0, f.get("height") or 0),
                reverse=True,
            )
            return best[0]["url"]
        # Last resort: any format with a URL
        for f in formats:
            if f.get("url"):
                return f["url"]
        return None

    @staticmethod
    def _raise_for_message(msg: str, url: str) -> None:
        for phrase in PRIVATE_ERRORS:
            if phrase in msg:
                raise SkippableError(f"Skippable: {phrase!r} for {url!r}")
        for phrase in LIVE_STREAM_ERRORS:
            if phrase in msg:
                raise SkippableError(f"Live stream not supported: {url!r}")

    @staticmethod
    def _format_duration(seconds: int) -> str:
        if not seconds:
            return "0:00"
        h, rem = divmod(seconds, 3600)
        m, s = divmod(rem, 60)
        if h:
            return f"{h}:{m:02d}:{s:02d}"
        return f"{m}:{s:02d}"

    @staticmethod
    def _sanitize(text: str) -> str:
        return text.encode("utf-8", errors="replace").decode("utf-8")


extractor = YouTubeExtractor()
