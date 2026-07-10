from __future__ import annotations

import queue
import subprocess
import threading
import time
from typing import Optional

from app.config.settings import settings
from app.logger.setup import get_logger

logger = get_logger("pipeline")

CHUNK_SIZE = 4096
PCM_QUEUE_MAXSIZE = 128


class AudioEncoder:
    """Persistent ffmpeg that reads raw PCM from stdin and sends MP3 to Icecast."""

    def __init__(self) -> None:
        self._process: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()
        self._stderr_thread: Optional[threading.Thread] = None

    def start(self) -> bool:
        self.stop()
        cmd = self._build_command()
        try:
            with self._lock:
                self._process = subprocess.Popen(
                    cmd,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    close_fds=True,
                )
            self._start_stderr_reader()
            logger.info("Audio encoder started")
            return True
        except Exception as exc:
            logger.error(f"Audio encoder failed to start: {exc}", exc_info=True)
            return False

    def stop(self) -> None:
        with self._lock:
            proc = self._process
            self._process = None
        if proc is None:
            return
        try:
            if proc.stdin:
                proc.stdin.close()
        except Exception:
            pass
        try:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                logger.warning("Audio encoder did not terminate; sending SIGKILL")
                proc.kill()
                proc.wait(timeout=3)
        except ProcessLookupError:
            pass
        except Exception as exc:
            logger.error(f"Error stopping audio encoder: {exc}", exc_info=True)

    def write(self, data: bytes) -> bool:
        with self._lock:
            proc = self._process
        if proc is None or proc.stdin is None:
            return False
        try:
            proc.stdin.write(data)
            return True
        except Exception as exc:
            logger.error(f"Audio encoder write error: {exc}")
            return False

    def is_running(self) -> bool:
        with self._lock:
            return self._process is not None and self._process.poll() is None

    def _build_command(self) -> list[str]:
        return [
            settings.ffmpeg_path,
            "-hide_banner",
            "-loglevel", "info",
            "-f", "s16le",
            "-ar", str(settings.audio_samplerate),
            "-ac", str(settings.audio_channels),
            "-i", "pipe:0",
            "-vn",
            "-c:a", "libmp3lame",
            "-b:a", f"{settings.audio_bitrate}k",
            "-ar", str(settings.audio_samplerate),
            "-ac", str(settings.audio_channels),
            "-af", "loudnorm=I=-14:TP=-1:LRA=11",
            "-f", "mp3",
            "-ice_name", settings.icecast_name,
            "-ice_description", settings.icecast_description,
            "-ice_genre", settings.icecast_genre,
            "-ice_public", "1" if settings.icecast_public else "0",
            "-content_type", "audio/mpeg",
            settings.icecast_url,
        ]

    def _start_stderr_reader(self) -> None:
        def _read() -> None:
            with self._lock:
                proc = self._process
            if proc is None or proc.stderr is None:
                return
            lines: list[str] = []
            try:
                for raw_line in proc.stderr:
                    try:
                        line = raw_line.decode("utf-8", errors="replace").rstrip()
                    except Exception:
                        continue
                    if line:
                        line = self._redact_url(line)
                        lines.append(line)
                        logger.warning(f"[encoder] {line}")
                exit_code = proc.poll()
                logger.warning(
                    f"[encoder] process ended (exit_code={exit_code}). "
                    f"Last lines: {lines[-10:]!r}"
                )
            except Exception:
                pass

        self._stderr_thread = threading.Thread(
            target=_read, daemon=True, name="audio-encoder-stderr"
        )
        self._stderr_thread.start()

    @staticmethod
    def _redact_url(text: str) -> str:
        import re
        return re.sub(
            r"icecast://[^:@\s]+:[^@\s]+@",
            "icecast://***:***@",
            text,
        )


class TrackDecoder:
    """Per-track ffmpeg that reads a YouTube URL and outputs raw PCM to stdout."""

    def __init__(self, audio_url: str, track_title: str) -> None:
        self.audio_url = audio_url
        self.track_title = track_title
        self._process: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()

    def start(self) -> bool:
        cmd = self._build_command()
        try:
            with self._lock:
                self._process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    stdin=subprocess.DEVNULL,
                    close_fds=True,
                )
            logger.info(f"Track decoder started for: {self.track_title!r}")
            return True
        except Exception as exc:
            logger.error(
                f"Track decoder failed for {self.track_title!r}: {exc}",
                exc_info=True,
            )
            return False

    def read(self, size: int) -> bytes:
        with self._lock:
            proc = self._process
        if proc is None or proc.stdout is None:
            return b""
        try:
            return proc.stdout.read(size)
        except Exception:
            return b""

    def is_running(self) -> bool:
        with self._lock:
            return self._process is not None and self._process.poll() is None

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
                proc.kill()
                proc.wait(timeout=3)
        except ProcessLookupError:
            pass
        except Exception as exc:
            logger.error(f"Error stopping track decoder: {exc}", exc_info=True)

    def _build_command(self) -> list[str]:
        if self.audio_url.startswith("lavfi:"):
            return [
                settings.ffmpeg_path,
                "-hide_banner",
                "-loglevel", "error",
                "-f", "lavfi",
                "-i", self.audio_url.removeprefix("lavfi:"),
                "-vn",
                "-f", "s16le",
                "-ar", str(settings.audio_samplerate),
                "-ac", str(settings.audio_channels),
                "pipe:1",
            ]

        user_agent = (
            "Mozilla/5.0 (X11; Linux x86_64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
        return [
            settings.ffmpeg_path,
            "-hide_banner",
            "-loglevel", "error",
            "-re",
            "-reconnect", "1",
            "-reconnect_streamed", "1",
            "-reconnect_delay_max", str(settings.ffmpeg_reconnect_delay),
            "-reconnect_on_network_error", "1",
            "-reconnect_on_http_error", "5xx,403",
            "-timeout", "30000000",
            "-user_agent", user_agent,
            "-headers",
            "Accept-Language: en-US,en;q=0.9\r\n"
            "Origin: https://www.youtube.com\r\n"
            "Referer: https://www.youtube.com/\r\n",
            "-multiple_requests", "1",
            "-seekable", "0",
            "-i", self.audio_url,
            "-vn",
            "-f", "s16le",
            "-ar", str(settings.audio_samplerate),
            "-ac", str(settings.audio_channels),
            "pipe:1",
        ]


class AudioPipeline:
    """Persistent Icecast stream with seamless track-to-track handoff.

    One encoder stays connected to Icecast for the whole session. Decoders are
    swapped per track. A bounded PCM queue between the decoder reader thread and
    the encoder writer thread absorbs jitter and provides clean backpressure.
    """

    def __init__(self) -> None:
        self._encoder = AudioEncoder()
        self._decoder: Optional[TrackDecoder] = None
        self._pcm_queue: queue.Queue = queue.Queue(maxsize=PCM_QUEUE_MAXSIZE)
        self._decoder_reader_thread: Optional[threading.Thread] = None
        self._encoder_writer_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._track_finished = threading.Event()
        self._encoder_error = threading.Event()
        self._lock = threading.Lock()
        self._current_title: str = ""
        self._generation: int = 0

    def start(self) -> bool:
        self._stop_event.clear()
        self._encoder_error.clear()
        if not self._encoder.start():
            return False
        self._encoder_writer_thread = threading.Thread(
            target=self._encoder_writer_loop,
            daemon=True,
            name="audio-encoder-writer",
        )
        self._encoder_writer_thread.start()
        return True

    def stop(self) -> None:
        self._stop_event.set()
        self._stop_decoder()
        # Closing encoder stdin unblocks any pending writer write.
        self._encoder.stop()
        if self._encoder_writer_thread and self._encoder_writer_thread.is_alive():
            self._encoder_writer_thread.join(timeout=5)

    def play(self, audio_url: str, track_title: str) -> bool:
        self._stop_decoder()
        self._track_finished.clear()
        self._encoder_error.clear()
        with self._lock:
            self._generation += 1
            self._current_title = track_title
        decoder = TrackDecoder(audio_url, track_title)
        if not decoder.start():
            logger.error(f"Failed to start track decoder for {track_title!r}")
            self._track_finished.set()
            return False
        with self._lock:
            self._decoder = decoder
        self._decoder_reader_thread = threading.Thread(
            target=self._decoder_reader_loop,
            daemon=True,
            args=(decoder, self._generation, track_title),
            name="audio-decoder-reader",
        )
        self._decoder_reader_thread.start()
        logger.info(f"Now feeding: {track_title!r}")
        return True

    def skip_current(self) -> None:
        logger.info("Skipping current track")
        self._stop_decoder()

    def wait_for_track_end(self, timeout: Optional[float] = None) -> bool:
        return self._track_finished.wait(timeout=timeout)

    def is_encoder_running(self) -> bool:
        return self._encoder.is_running()

    def has_error(self) -> bool:
        return self._encoder_error.is_set()

    def _stop_decoder(self) -> None:
        with self._lock:
            decoder = self._decoder
            self._decoder = None
        if decoder:
            decoder.stop()
        # Discard any buffered PCM from the previous track so the writer picks
        # up the new stream immediately after a skip or song change.
        self._drain_queue()

    def _drain_queue(self) -> None:
        while not self._pcm_queue.empty():
            try:
                self._pcm_queue.get_nowait()
            except queue.Empty:
                break

    def _decoder_reader_loop(
        self,
        decoder: TrackDecoder,
        generation: int,
        title: str,
    ) -> None:
        """Read decoded PCM from the decoder and feed the bounded queue."""
        while not self._stop_event.is_set():
            with self._lock:
                still_active = (
                    self._generation == generation and self._decoder is decoder
                )
            if not still_active:
                break

            try:
                chunk = decoder.read(CHUNK_SIZE)
            except Exception:
                break

            if chunk:
                while not self._stop_event.is_set():
                    with self._lock:
                        still_active = (
                            self._generation == generation and self._decoder is decoder
                        )
                    if not still_active:
                        break
                    try:
                        self._pcm_queue.put(chunk, timeout=1.0)
                        break
                    except queue.Full:
                        # Encoder is slow; retry while this track is still active.
                        continue
                continue

            if not decoder.is_running():
                break
            time.sleep(0.001)

        # Only mark the track as finished if this decoder is still the active one.
        with self._lock:
            if self._decoder is decoder and self._generation == generation:
                self._decoder = None
                self._track_finished.set()
                logger.info(f"Track decoder finished: {title!r}")

    def _encoder_writer_loop(self) -> None:
        """Pull PCM from the queue and write to the persistent encoder."""
        while not self._stop_event.is_set():
            try:
                chunk = self._pcm_queue.get(timeout=0.5)
            except queue.Empty:
                continue
            if not chunk:
                continue
            if not self._encoder.write(chunk):
                logger.error("Audio encoder write failed; pipeline entering error state")
                self._encoder_error.set()
                break


audio_pipeline = AudioPipeline()
