from __future__ import annotations

import shlex
import subprocess
import threading
import time
from typing import Optional

from app.config.settings import settings
from app.logger.setup import get_logger

logger = get_logger("ffmpeg")


class FFmpegStreamer:
    def __init__(self) -> None:
        self._process: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()
        self._stderr_thread: Optional[threading.Thread] = None

    def start(self, audio_url: str, track_title: str = "") -> bool:
        self.stop()
        cmd = self._build_command(audio_url, track_title)
        logger.info(f"Starting FFmpeg for: {track_title!r}")
        logger.debug(f"FFmpeg command: {' '.join(cmd)}")
        try:
            with self._lock:
                self._process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    stdin=subprocess.DEVNULL,
                    close_fds=True,
                )
            self._start_stderr_reader(track_title)
            return True
        except FileNotFoundError:
            logger.error("FFmpeg binary not found. Is ffmpeg installed?")
            return False
        except Exception as exc:
            logger.error(f"Failed to start FFmpeg: {exc}", exc_info=True)
            return False

    def wait(self) -> int:
        with self._lock:
            proc = self._process
        if proc is None:
            return -1
        try:
            return proc.wait()
        except Exception as exc:
            logger.error(f"Error waiting for FFmpeg: {exc}", exc_info=True)
            return -1

    def stop(self) -> None:
        with self._lock:
            proc = self._process
            self._process = None
        if proc is None:
            return
        try:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                logger.warning("FFmpeg did not terminate; sending SIGKILL")
                proc.kill()
                proc.wait(timeout=3)
        except ProcessLookupError:
            pass
        except Exception as exc:
            logger.error(f"Error stopping FFmpeg: {exc}", exc_info=True)
        if self._stderr_thread and self._stderr_thread.is_alive():
            self._stderr_thread.join(timeout=3)

    def is_running(self) -> bool:
        with self._lock:
            return self._process is not None and self._process.poll() is None

    def get_pid(self) -> Optional[int]:
        with self._lock:
            return self._process.pid if self._process else None

    def _build_command(self, audio_url: str, track_title: str) -> list[str]:
        icecast_url = settings.icecast_url
        return [
            settings.ffmpeg_path,
            "-hide_banner",
            "-loglevel", "warning",
            "-reconnect", "1",
            "-reconnect_streamed", "1",
            "-reconnect_delay_max", str(settings.ffmpeg_reconnect_delay),
            "-timeout", "30000000",
            "-i", audio_url,
            "-vn",
            "-c:a", "libmp3lame",
            "-b:a", f"{settings.audio_bitrate}k",
            "-ar", str(settings.audio_samplerate),
            "-ac", str(settings.audio_channels),
            "-f", "mp3",
            "-ice_name", settings.icecast_name,
            "-ice_description", settings.icecast_description,
            "-ice_genre", settings.icecast_genre,
            "-ice_public", "1" if settings.icecast_public else "0",
            "-content_type", "audio/mpeg",
            icecast_url,
        ]

    def _start_stderr_reader(self, track_title: str) -> None:
        def _read() -> None:
            with self._lock:
                proc = self._process
            if proc is None or proc.stderr is None:
                return
            try:
                for raw_line in proc.stderr:
                    try:
                        line = raw_line.decode("utf-8", errors="replace").rstrip()
                    except Exception:
                        continue
                    if line:
                        logger.warning(f"[ffmpeg:{track_title!r}] {line}")
            except Exception:
                pass

        self._stderr_thread = threading.Thread(
            target=_read, daemon=True, name="ffmpeg-stderr"
        )
        self._stderr_thread.start()


ffmpeg_streamer = FFmpegStreamer()
