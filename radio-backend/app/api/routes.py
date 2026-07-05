from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any, Dict

import psutil
from fastapi import APIRouter, Depends, Header, HTTPException, status
from fastapi.responses import JSONResponse

from app.autodj.manager import autodj_manager
from app.config.settings import settings
from app.ffmpeg.streamer import ffmpeg_streamer
from app.icecast.connector import icecast_connector
from app.logger.setup import get_logger
from app.models.schemas import (
    ClearResponse,
    HealthResponse,
    NowPlayingResponse,
    PlayRequest,
    PlayResponse,
    QueueResponse,
    RemoveRequest,
    RemoveResponse,
    SkipResponse,
    StatusResponse,
    StatsResponse,
    TrackInfo,
)
from app.player.controller import player
from app.queue.manager import queue_manager
from app.youtube.extractor import ExtractionError, SkippableError, extractor

logger = get_logger("api")
router = APIRouter()


def _require_debug_secret(x_api_secret: str | None = Header(None, alias="X-API-Secret")) -> None:
    """Protect debug endpoints when API_SECRET is configured; otherwise allow access."""
    if settings.api_secret and x_api_secret != settings.api_secret:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API secret",
        )


@router.get("/debug/env", dependencies=[Depends(_require_debug_secret)])
async def debug_env() -> dict:
    """Return whether YOUTUBE_COOKIES_B64 is set (value hidden)."""
    has_cookies = bool(settings.youtube_cookies_b64)
    return {
        "youtube_cookies_b64_set": has_cookies,
        "youtube_cookies_b64_length": len(settings.youtube_cookies_b64) if has_cookies else 0,
        "ytdlp_format": settings.ytdlp_format,
        "ytdlp_timeout": settings.ytdlp_timeout,
    }


@router.get("/debug/logs", dependencies=[Depends(_require_debug_secret)])
async def debug_logs(lines: int = 100) -> dict:
    """Return tail of local log files for debugging Railway/FFmpeg issues."""
    log_dir = Path(settings.log_dir)
    result: dict[str, list[str]] = {}
    for name in ["ffmpeg.log", "api.log", "player.log", "ytdlp.log", "startup.log", "errors.log"]:
        path = log_dir / name
        try:
            if path.exists():
                text = path.read_text(encoding="utf-8", errors="replace")
                result[name] = text.splitlines()[-lines:]
            else:
                result[name] = ["(file not found)"]
        except Exception as exc:
            result[name] = [f"(error reading: {exc})"]
    return {"logs": result}


@router.get("/debug/icecast-config", dependencies=[Depends(_require_debug_secret)])
async def debug_icecast_config() -> dict:
    """Return the effective Icecast XML with secrets redacted."""
    import re
    path = Path("/tmp/icecast-active.xml")
    if not path.exists():
        path = Path("/home/runner/workspace/icecast-replit.xml")
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        # Redact all password-like tags
        redacted = re.sub(r"(<[^>/]*password[^>]*>)[^<]*(</[^>]*>)", r"\1***REDACTED***\2", text, flags=re.IGNORECASE)
        return {"path": str(path), "xml": redacted}
    except Exception as exc:
        return {"error": str(exc)}


@router.post("/debug/ffmpeg-test", dependencies=[Depends(_require_debug_secret)])
async def debug_ffmpeg_test() -> dict:
    """Run a 10-second sine wave directly through FFmpeg and return its full stderr."""
    import subprocess
    cmd = [
        settings.ffmpeg_path,
        "-hide_banner",
        "-loglevel", "debug",
        "-f", "lavfi",
        "-i", "sine=frequency=1000:duration=10",
        "-vn",
        "-c:a", "libmp3lame",
        "-b:a", f"{settings.audio_bitrate}k",
        "-ar", str(settings.audio_samplerate),
        "-ac", str(settings.audio_channels),
        "-f", "mp3",
        "-content_type", "audio/mpeg",
        settings.icecast_url,
    ]
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        stdin=subprocess.DEVNULL,
    )
    try:
        stdout, stderr = proc.communicate(timeout=12)
    except subprocess.TimeoutExpired:
        proc.kill()
        stdout, stderr = proc.communicate()
    def _redact_url(text: str) -> str:
        import re
        return re.sub(r"icecast://[^:@\s]+:[^@\s]+@", "icecast://***:***@", text)

    return {
        "command": _redact_url(" ".join(cmd)),
        "exit_code": proc.returncode,
        "stderr": [_redact_url(line) for line in stderr.decode("utf-8", errors="replace").splitlines()],
        "stdout": stdout.decode("utf-8", errors="replace").splitlines()[:20],
    }


_test_tone_proc: Any = None


async def _run_test_tone(cmd: list[str]) -> None:
    """Background task that runs a 60-second sine wave into Icecast."""
    global _test_tone_proc
    import subprocess
    _test_tone_proc = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        close_fds=True,
    )
    try:
        _test_tone_proc.wait(timeout=65)
    except subprocess.TimeoutExpired:
        _test_tone_proc.terminate()
    finally:
        _test_tone_proc = None


@router.post("/test-tone", dependencies=[Depends(_require_debug_secret)])
async def test_tone() -> dict:
    """Feed a 60-second generated sine wave into Icecast to verify the stream path."""
    global _test_tone_proc
    if _test_tone_proc is not None:
        try:
            _test_tone_proc.terminate()
        except Exception:
            pass
        _test_tone_proc = None
        await asyncio.sleep(0.5)

    cmd = [
        settings.ffmpeg_path,
        "-hide_banner",
        "-loglevel", "warning",
        "-f", "lavfi",
        "-i", "sine=frequency=1000:duration=60",
        "-vn",
        "-c:a", "libmp3lame",
        "-b:a", f"{settings.audio_bitrate}k",
        "-ar", str(settings.audio_samplerate),
        "-ac", str(settings.audio_channels),
        "-f", "mp3",
        "-ice_name", "Itachi Hits Radio",
        "-ice_description", "Test tone",
        "-content_type", "audio/mpeg",
        settings.icecast_url,
    ]
    asyncio.create_task(_run_test_tone(cmd))
    return {"success": True, "message": "60-second test tone streaming to /stream"}


@router.post("/play", response_model=PlayResponse)
async def play(req: PlayRequest) -> PlayResponse:
    logger.info(f"POST /play — query={req.query!r} url={req.url!r} by={req.requested_by!r}")
    try:
        ytinput = req.get_input()
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    try:
        # yt-dlp does blocking I/O; run it in a thread so the event loop stays free
        track = await asyncio.to_thread(
            extractor.extract_info, ytinput, requested_by=req.requested_by
        )
    except SkippableError as exc:
        logger.warning(f"Track not playable: {exc}")
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    except ExtractionError as exc:
        logger.error(f"Extraction error: {exc}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))
    except Exception as exc:
        logger.error(f"Unexpected error in /play: {exc}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    queue_manager.add(track)
    return PlayResponse(success=True, message="Track added to queue", track=track)


@router.post("/skip", response_model=SkipResponse)
async def skip() -> SkipResponse:
    logger.info("POST /skip")
    player.skip()
    return SkipResponse(success=True, message="Skip signal sent")


@router.post("/remove", response_model=RemoveResponse)
async def remove(req: RemoveRequest) -> RemoveResponse:
    logger.info(f"POST /remove — position={req.position}")
    removed = queue_manager.remove_at(req.position)
    if removed is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No track at position {req.position}",
        )
    return RemoveResponse(success=True, message=f"Removed: {removed.title!r}")


@router.post("/clear", response_model=ClearResponse)
async def clear() -> ClearResponse:
    logger.info("POST /clear")
    count = queue_manager.clear()
    return ClearResponse(success=True, cleared=count)


@router.get("/queue", response_model=QueueResponse)
async def get_queue() -> QueueResponse:
    items = queue_manager.list()
    return QueueResponse(queue=items, total=len(items))


@router.get("/nowplaying", response_model=NowPlayingResponse)
async def now_playing() -> NowPlayingResponse:
    track = player.get_current_track()
    elapsed = player.elapsed_seconds()

    if track is None:
        return NowPlayingResponse(
            title="Nothing playing",
            channel="",
            duration="0:00",
            elapsed="0:00",
            remaining="0:00",
            thumbnail="",
            source_url="",
            is_autodj=player.is_autodj(),
            queue_position=None,
            playing=False,
        )

    duration_secs = _parse_duration(track.duration)
    remaining_secs = max(0.0, duration_secs - elapsed)

    return NowPlayingResponse(
        title=track.title,
        channel="",
        duration=track.duration,
        elapsed=_format_seconds(elapsed),
        remaining=_format_seconds(remaining_secs),
        thumbnail=track.thumbnail,
        source_url=track.url,
        is_autodj=player.is_autodj(),
        queue_position=track.position if not player.is_autodj() else None,
        playing=player.is_playing(),
    )


@router.get("/status", response_model=StatusResponse)
async def status_endpoint() -> StatusResponse:
    try:
        cpu = psutil.cpu_percent(interval=0.1)
        mem = psutil.virtual_memory().percent
    except Exception:
        cpu = 0.0
        mem = 0.0

    uptime = _format_seconds(player.uptime_seconds())
    source = "AutoDJ" if player.is_autodj() else "User Queue"
    if not player.is_playing():
        source = "Idle"

    return StatusResponse(
        playing=player.is_playing(),
        connected_to_icecast=icecast_connector.is_connected(),
        queue_length=queue_manager.size(),
        listeners=icecast_connector.get_listeners(),
        uptime=uptime,
        cpu_usage=cpu,
        memory_usage=mem,
        bitrate=settings.audio_bitrate,
        autodj_enabled=autodj_manager.is_enabled(),
        current_source=source,
    )


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    icecast_ok = icecast_connector.check_connection()
    ffmpeg_ok = ffmpeg_streamer.is_running() or not player.is_playing()
    queue_ok = queue_manager.is_alive()
    player_ok = player.is_alive()
    api_ok = True

    # Icecast is a downstream dependency — its absence means degraded, not down.
    # Only core internal components (queue, player, api) determine liveness for
    # Railway's healthcheck. A 503 here causes Railway to kill the container.
    core_healthy = queue_ok and player_ok and api_ok

    response = HealthResponse(
        status="ok" if (core_healthy and icecast_ok) else "degraded",
        icecast=icecast_ok,
        ffmpeg=ffmpeg_ok,
        queue=queue_ok,
        player=player_ok,
        api=api_ok,
    )

    if not core_healthy:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=response.model_dump(),
        )
    return response


@router.get("/stats", response_model=StatsResponse)
async def stats() -> StatsResponse:
    s = player.get_stats()
    return StatsResponse(
        total_tracks_played=s.get("total_played", 0),
        total_skips=s.get("total_skips", 0),
        total_errors=s.get("total_errors", 0),
        uptime_seconds=player.uptime_seconds(),
        autodj_tracks_played=s.get("autodj_played", 0),
        user_tracks_played=s.get("user_played", 0),
        current_listeners=icecast_connector.get_listeners(),
        peak_listeners=s.get("peak_listeners", 0),
    )


def _parse_duration(duration: str) -> float:
    parts = duration.split(":")
    try:
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        if len(parts) == 2:
            return int(parts[0]) * 60 + int(parts[1])
        return float(parts[0])
    except Exception:
        return 0.0


def _format_seconds(secs: float) -> str:
    secs = int(secs)
    h, rem = divmod(secs, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"
