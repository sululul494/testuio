from __future__ import annotations

import base64
import json
import os
import random
import re
import time
from typing import Any, Dict, List, Optional

import requests
import yt_dlp
from app.youtube.oauth_patch import _apply_youtube_oauth_patch

from app.config.settings import settings
from app.logger.setup import get_logger
from app.models.schemas import TrackInfo

logger = get_logger("ytdlp")

COOKIES_PATH = "/tmp/youtube_cookies.txt"


_COOKIES_B64_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "cookies_b64.txt",
)


def _write_cookies() -> None:
    """Decode base64 cookies from env (or cookies_b64.txt fallback) and write for yt-dlp."""
    raw_b64: str | None = settings.youtube_cookies_b64

    # Fall back to the committed cookies_b64.txt file if the env var isn't set
    if not raw_b64 and os.path.exists(_COOKIES_B64_FILE):
        try:
            raw_b64 = open(_COOKIES_B64_FILE, "r", encoding="utf-8").read().strip()
            logger.info("YOUTUBE_COOKIES_B64 not set; loaded cookies from cookies_b64.txt")
        except Exception as exc:
            logger.error(f"Failed to read cookies_b64.txt: {exc}")

    if not raw_b64:
        logger.warning("No YouTube cookies available (env var not set, cookies_b64.txt missing)")
        return

    try:
        raw = base64.b64decode(raw_b64).decode("utf-8", errors="replace")
        with open(COOKIES_PATH, "w", encoding="utf-8") as f:
            f.write(raw)
        logger.info("YouTube cookies file written to %s", COOKIES_PATH)
    except Exception as exc:
        logger.error(f"Failed to write YouTube cookies: {exc}")


# Write cookies once at module load so all yt-dlp instances use them.
_write_cookies()

# Apply the runtime patch to the yt-dlp-youtube-oauth2 plugin before it is used.
_apply_youtube_oauth_patch()

OAUTH2_TOKEN_CACHE_FILE = os.path.expanduser("~/.cache/yt-dlp/youtube-oauth2/token_data.json")


def _write_oauth2_token() -> None:
    """Decode a base64-encoded OAuth2 token from env and prime the yt-dlp cache.

    The yt-dlp-youtube-oauth2 plugin stores tokens in yt-dlp's cache. By
    writing the env-provided token to the same location, the plugin can load it
    automatically and refresh the access token as needed without prompting for a
    device code on every startup.
    """
    raw_b64: str | None = settings.youtube_oauth2_token_b64
    if not raw_b64:
        return
    try:
        token_data = json.loads(base64.b64decode(raw_b64).decode("utf-8"))
        required = ("access_token", "expires", "refresh_token", "token_type")
        if not all(k in token_data for k in required):
            logger.warning("YOUTUBE_OAUTH2_TOKEN_B64 is missing required keys; ignoring")
            return
        # Store in the plugin's cache location so it is loaded automatically.
        with yt_dlp.YoutubeDL({"quiet": True, "cachedir": os.path.expanduser("~/.cache/yt-dlp")}) as ydl:
            ydl.cache.store("youtube-oauth2", "token_data", token_data)
        logger.info("YouTube OAuth2 token loaded from environment into yt-dlp cache")
    except Exception as exc:
        logger.error(f"Failed to load YouTube OAuth2 token: {exc}")


# Prime the OAuth2 token cache at module load so extractions can use it.
_write_oauth2_token()

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


class RateLimitError(ExtractionError):
    """YouTube/IP rate limit or bot block; caller should back off globally."""
    pass


# Global cooldown state for YouTube bot/rate-limit detection.
# Shared across extractor instances so rapid-fire AutoDJ retries don't
# keep hammering YouTube while the block is active.
_youtube_cooldown_until: float = 0.0
_consecutive_bot_blocks: int = 0   # tracks unbroken run of bot-blocks for backoff
_YOUTUBE_COOLDOWN_SECONDS: float = 60.0
_MAX_BACKOFF_SECONDS: float = 600.0  # 10 min hard cap


def _set_youtube_cooldown(seconds: float) -> None:
    global _youtube_cooldown_until
    _youtube_cooldown_until = time.monotonic() + seconds
    logger.warning(f"YouTube rate-limit/bot detection; cooling down for {seconds:.0f}s")


def _is_youtube_cooldown_active() -> bool:
    return time.monotonic() < _youtube_cooldown_until


def _youtube_cooldown_remaining() -> float:
    return max(0.0, _youtube_cooldown_until - time.monotonic())


def _maybe_apply_youtube_backoff(msg: str) -> None:
    """Apply exponential backoff on bot/rate-limit errors."""
    global _consecutive_bot_blocks
    msg_lower = msg.lower()
    if any(k in msg_lower for k in ("429", "too many requests", "sign in", "bot", "confirm you're not a bot")):
        _consecutive_bot_blocks += 1
        # Exponential: 60s → 120s → 240s → 480s → 600s (cap)
        backoff = min(_YOUTUBE_COOLDOWN_SECONDS * (2 ** (_consecutive_bot_blocks - 1)), _MAX_BACKOFF_SECONDS)
        _set_youtube_cooldown(backoff)


def _clear_youtube_cooldown() -> None:
    """Call when a fallback/recovery succeeds to reset backoff state."""
    global _youtube_cooldown_until, _consecutive_bot_blocks
    _youtube_cooldown_until = 0.0
    _consecutive_bot_blocks = 0


class YouTubeExtractor:
    def __init__(self) -> None:
        self._base_opts: Dict[str, Any] = {
            "format": "bestaudio[ext=m4a]/bestaudio/best",
            "quiet": True,
            "no_warnings": False,
            "noplaylist": True,
            "socket_timeout": settings.ytdlp_timeout,
            "retries": 3,
            "fragment_retries": 3,
            "nocheckcertificate": True,
            "geo_bypass": True,
            "http_headers": {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept-Language": "en-US,en;q=0.9",
            },
            "extractor_args": {
                "youtube": {
                    # tv_embedded is treated as an embedded player — much less
                    # aggressive bot-detection from cloud IPs than android/web.
                    "player_client": ["tv_embedded", "ios", "android"],
                    "skip": ["hls", "dash"],
                }
            },
        }
        oauth2_token_present = bool(settings.youtube_oauth2_token_b64) or os.path.exists(OAUTH2_TOKEN_CACHE_FILE)
        if oauth2_token_present:
            # OAuth2 is the only auth method that reliably bypasses YouTube's
            # cloud-IP bot checks. It manages its own Authorization header, so
            # do not pass cookies at the same time.
            self._base_opts["username"] = "oauth2"
            self._base_opts["password"] = ""
            # Authenticated web client gives the richest format selection.
            self._base_opts["extractor_args"]["youtube"]["player_client"] = ["web", "ios", "android"]
            logger.info("Using YouTube OAuth2 authentication")
        else:
            if os.path.exists(COOKIES_PATH):
                self._base_opts["cookies"] = COOKIES_PATH
                logger.info("Using YouTube cookies from %s", COOKIES_PATH)

        if settings.proxy_url:
            self._base_opts["proxy"] = settings.proxy_url
            logger.info("Using proxy for yt-dlp: %s", settings.proxy_url)

    def _ydl(self, extra: Optional[Dict[str, Any]] = None) -> yt_dlp.YoutubeDL:
        opts = dict(self._base_opts)
        if extra:
            opts.update(extra)
        return yt_dlp.YoutubeDL(opts)

    def extract_info(self, url: str, requested_by: str = "API") -> TrackInfo:
        logger.info(f"Extracting info for: {url!r}")

        if _is_youtube_cooldown_active():
            remaining = _youtube_cooldown_remaining()
            logger.warning(f"YouTube cooldown active ({remaining:.0f}s left); skipping extraction")
            raise RateLimitError(f"YouTube cooldown active for {remaining:.0f}s")

        try:
            with self._ydl() as ydl:
                info = ydl.extract_info(url, download=False)
        except yt_dlp.utils.DownloadError as exc:
            msg = str(exc).lower()
            logger.warning(f"yt-dlp DownloadError for {url!r}: {msg[:200]}")
            is_true_rate_limit = any(k in msg for k in ("429", "too many requests"))
            is_bot_block = any(k in msg for k in ("sign in", "bot", "confirm you're not a bot"))
            if is_true_rate_limit:
                # HTTP 429 = server-side IP rate limit; apply global cooldown.
                _maybe_apply_youtube_backoff(msg)
                raise RateLimitError(f"YouTube HTTP 429 rate-limit for {url!r}")
            if is_bot_block:
                # Bot-check on this specific video. Skip it and let AutoDJ
                # move on to the next URL — no global cooldown needed.
                logger.warning(f"Bot-check for {url!r}; skipping this video")
                raise SkippableError(f"Bot-check blocked {url!r}")
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
        if _is_youtube_cooldown_active():
            remaining = _youtube_cooldown_remaining()
            logger.warning(f"YouTube cooldown active ({remaining:.0f}s left); skipping playlist expansion")
            return []

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
        except yt_dlp.utils.DownloadError as exc:
            msg = str(exc).lower()
            _maybe_apply_youtube_backoff(msg)
            logger.error(f"Failed to expand playlist {playlist_url!r}: {exc}")
            return []
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

    def _invidious_fallback(self, url: str, requested_by: str) -> Optional[TrackInfo]:
        """Try Invidious API when YouTube blocks the IP with bot detection."""
        # Extract video ID from URL
        match = re.search(r"[?&]v=([a-zA-Z0-9_-]{11})", url)
        if not match:
            logger.warning(f"Cannot extract video ID from {url!r} for Invidious fallback")
            return None
        video_id = match.group(1)

        # List of public Invidious instances (rotated for reliability)
        instances = [
            "https://iv.datura.network",
            "https://iv.nboeck.de",
            "https://iv.melmac.space",
            "https://iv.nboeck.de",
            "https://y.com.sb",
        ]
        random.shuffle(instances)

        for instance in instances[:3]:
            api_url = f"{instance}/api/v1/videos/{video_id}"
            try:
                logger.info(f"Trying Invidious fallback: {api_url}")
                resp = requests.get(api_url, timeout=15, headers={
                    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    "Accept": "application/json",
                })
                if resp.status_code != 200:
                    logger.warning(f"Invidious {instance} returned {resp.status_code}")
                    continue
                data = resp.json()
                title = data.get("title", "Unknown")
                duration = data.get("lengthSeconds", 0)
                thumbnail = data.get("videoThumbnails", [{}])[0].get("url", "")

                # Find best audio-only or mixed format
                formats = data.get("adaptiveFormats", []) or data.get("formatStreams", [])
                audio_url = None
                best_abr = 0
                for f in formats:
                    f_type = f.get("type", "")
                    if "audio" in f_type:
                        abr = f.get("bitrate", 0)
                        if abr > best_abr:
                            best_abr = abr
                            audio_url = f.get("url")
                if not audio_url and formats:
                    # Fallback to any format with a URL
                    for f in formats:
                        if f.get("url"):
                            audio_url = f["url"]
                            break
                if not audio_url:
                    logger.warning(f"Invidious {instance}: no URL for {video_id}")
                    continue

                track = TrackInfo(
                    position=0,
                    title=self._sanitize(title),
                    duration=self._format_duration(duration),
                    url=audio_url,
                    thumbnail=thumbnail,
                    requested_by=requested_by,
                )
                logger.info(f"Invidious fallback succeeded: {track.title!r} via {instance}")
                return track
            except Exception as exc:
                logger.warning(f"Invidious {instance} failed: {exc}")
                continue
        logger.error(f"All Invidious fallbacks failed for {video_id}")
        return None


extractor = YouTubeExtractor()
