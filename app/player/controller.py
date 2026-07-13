from __future__ import annotations

import threading
import time
from typing import Optional

from app.autodj.manager import autodj_manager
from app.config.settings import settings
from app.audio.pipeline import audio_pipeline
from app.icecast.connector import icecast_connector
from app.logger.setup import get_logger
from app.models.schemas import TrackInfo
from app.queue.manager import queue_manager
from app.youtube.extractor import ExtractionError, SkippableError, extractor

logger = get_logger("player")


class PlayerController:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._current_track: Optional[TrackInfo] = None
        self._is_autodj: bool = False
        self._track_started_at: float = 0.0
        self._playing: bool = False
        self._skip_event = threading.Event()
        self._player_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._stats = {
            "total_played": 0,
            "total_skips": 0,
            "total_errors": 0,
            "autodj_played": 0,
            "user_played": 0,
            "peak_listeners": 0,
        }
        self._started_at: float = time.monotonic()

    def start(self) -> None:
        logger.info("Player starting")
        self._stop_event.clear()
        if not audio_pipeline.start():
            logger.error("Audio pipeline failed to start; player will not run")
            return
        self._player_thread = threading.Thread(
            target=self._play_loop,
            daemon=True,
            name="player-loop",
        )
        self._player_thread.start()

    def stop(self) -> None:
        logger.info("Player stopping")
        self._stop_event.set()
        audio_pipeline.stop()
        if self._player_thread:
            self._player_thread.join(timeout=10)

    def skip(self) -> None:
        logger.info("Skip requested")
        with self._lock:
            self._stats["total_skips"] += 1
        self._skip_event.set()
        audio_pipeline.skip_current()

    def is_playing(self) -> bool:
        with self._lock:
            return self._playing

    def is_alive(self) -> bool:
        return (
            self._player_thread is not None
            and self._player_thread.is_alive()
        )

    def get_current_track(self) -> Optional[TrackInfo]:
        with self._lock:
            return self._current_track

    def is_autodj(self) -> bool:
        with self._lock:
            return self._is_autodj

    def elapsed_seconds(self) -> float:
        with self._lock:
            if not self._playing or not self._track_started_at:
                return 0.0
            return time.monotonic() - self._track_started_at

    def uptime_seconds(self) -> float:
        return time.monotonic() - self._started_at

    def get_stats(self) -> dict:
        with self._lock:
            return dict(self._stats)

    def update_peak_listeners(self, count: int) -> None:
        with self._lock:
            if count > self._stats["peak_listeners"]:
                self._stats["peak_listeners"] = count

    def _play_loop(self) -> None:
        logger.info("Player loop started")
        while not self._stop_event.is_set():
            self._skip_event.clear()
            track = self._get_next_track()
            if track is None:
                logger.warning("No track available; playing silence to keep stream alive")
                with self._lock:
                    self._is_autodj = False
                track = self._silence_track()
            self._play_track(track)

    def _silence_track(self) -> TrackInfo:
        return TrackInfo(
            position=0,
            title="Buffering... searching for next track",
            duration="0:30",
            url="lavfi:anullsrc=r=44100:cl=stereo:d=30",
            thumbnail="",
            requested_by="system",
        )

    def _get_next_track(self) -> Optional[TrackInfo]:
        next_queued = queue_manager.pop_next()
        if next_queued is not None:
            logger.info(f"Playing user-requested track: {next_queued.title!r}")
            with self._lock:
                self._is_autodj = False
            return next_queued

        if not autodj_manager.is_enabled():
            return None

        logger.debug("Queue empty; fetching AutoDJ track")
        try:
            track = autodj_manager.next_track()
            if track is not None:
                with self._lock:
                    self._is_autodj = True
            return track
        except Exception as exc:
            logger.error(f"AutoDJ error: {exc}", exc_info=True)
            return None

    def _play_track(self, track: TrackInfo) -> None:
        logger.info(f"Now playing: {track.title!r}")
        # Generated silence decodes at machine speed, so we must hold the loop
        # for its intended real-time duration rather than wait for the decoder.
        is_silence = track.url == "lavfi:anullsrc=r=44100:cl=stereo:d=30"
        with self._lock:
            self._current_track = track
            self._track_started_at = time.monotonic()
            self._playing = True
            if not is_silence:
                self._stats["total_played"] += 1
                if self._is_autodj:
                    self._stats["autodj_played"] += 1
                else:
                    self._stats["user_played"] += 1

        icecast_connector.update_metadata(track.title)

        started = audio_pipeline.play(track.url, track_title=track.title)
        if not started:
            logger.error(f"Audio pipeline failed to feed track {track.title!r}")
            with self._lock:
                self._playing = False
                self._stats["total_errors"] += 1
            return

        silence_deadline = time.monotonic() + 30.0 if is_silence else None

        while not self._stop_event.is_set():
            if self._skip_event.is_set():
                logger.info(f"Skipping: {track.title!r}")
                break
            # The encoder writer loop handles transient errors itself. The player
            # should only give up on a real track if the encoder has been stuck
            # for a long time. Silence tracks must never be aborted, because they
            # are the bridge that keeps the stream alive while the encoder recovers.
            if not is_silence and audio_pipeline.is_encoder_stuck(threshold=30.0):
                logger.error(f"Audio pipeline stuck while playing {track.title!r}")
                with self._lock:
                    self._stats["total_errors"] += 1
                break
            if is_silence and time.monotonic() >= silence_deadline:
                logger.info(f"Finished: {track.title!r}")
                break
            if not is_silence and audio_pipeline.wait_for_track_end(timeout=0.5):
                logger.info(f"Finished: {track.title!r}")
                break
            listeners = icecast_connector.get_listeners()
            self.update_peak_listeners(listeners)

        with self._lock:
            self._playing = False
            self._current_track = None


player = PlayerController()
