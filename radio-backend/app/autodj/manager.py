from __future__ import annotations

import random
import threading
import time
from typing import Iterator, List, Optional

from app.config.settings import settings
from app.logger.setup import get_logger
from app.models.schemas import TrackInfo
from app.youtube.extractor import ExtractionError, RateLimitError, SkippableError, extractor

logger = get_logger("autodj")


class AutoDJManager:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._urls: List[str] = []
        self._index: int = 0
        self._last_refresh: float = 0.0
        self._enabled: bool = settings.autodj_enabled
        self._refresh_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    def start(self) -> None:
        if not self._enabled:
            logger.info("AutoDJ is disabled")
            return
        logger.info("AutoDJ starting — playlist load deferred to background")
        self._refresh_thread = threading.Thread(
            target=self._startup_and_loop,
            daemon=True,
            name="autodj-refresh",
        )
        self._refresh_thread.start()

    def _startup_and_loop(self) -> None:
        self._refresh_playlists()
        self._refresh_loop()

    def stop(self) -> None:
        self._stop_event.set()
        if self._refresh_thread:
            self._refresh_thread.join(timeout=5)

    def is_enabled(self) -> bool:
        return self._enabled

    def track_count(self) -> int:
        with self._lock:
            return len(self._urls)

    def next_track(self) -> Optional[TrackInfo]:
        if not self._enabled:
            return None
        attempts = 0
        max_attempts = 5
        while attempts < max_attempts:
            url = self._pick_next_url()
            if url is None:
                logger.warning("AutoDJ has no URLs to play")
                return None
            attempts += 1
            try:
                track = extractor.extract_info(url, requested_by="AutoDJ")
                logger.info(f"AutoDJ selected: {track.title!r}")
                return track
            except RateLimitError as exc:
                logger.warning(f"AutoDJ rate-limited for {url!r}: {exc}")
                # Stop retrying immediately; caller should back off and play silence.
                return None
            except SkippableError as exc:
                logger.warning(f"AutoDJ skipping {url!r}: {exc}")
                time.sleep(2)
                continue
            except ExtractionError as exc:
                logger.error(f"AutoDJ extraction error for {url!r}: {exc}")
                time.sleep(5)
                continue
            except Exception as exc:
                logger.error(f"AutoDJ unexpected error for {url!r}: {exc}", exc_info=True)
                time.sleep(5)
                continue
        logger.error("AutoDJ exhausted maximum attempts without finding a playable track")
        return None

    def _pick_next_url(self) -> Optional[str]:
        with self._lock:
            if not self._urls:
                return None
            if self._index >= len(self._urls):
                self._index = 0
                if settings.autodj_shuffle:
                    random.shuffle(self._urls)
            url = self._urls[self._index]
            self._index += 1
            return url

    def _refresh_playlists(self) -> None:
        playlists = settings.autodj_playlist_list
        if not playlists:
            logger.warning("AUTODJ_PLAYLISTS not configured — AutoDJ will be idle")
            return
        all_urls: List[str] = []
        for playlist_url in playlists:
            urls = extractor.extract_playlist_urls(playlist_url)
            logger.info(f"Loaded {len(urls)} tracks from {playlist_url!r}")
            all_urls.extend(urls)
        if not all_urls:
            logger.warning("AutoDJ playlists yielded no tracks")
            return
        if settings.autodj_shuffle:
            random.shuffle(all_urls)
        with self._lock:
            self._urls = all_urls
            self._index = 0
        self._last_refresh = time.monotonic()
        logger.info(f"AutoDJ loaded {len(all_urls)} total tracks")

    def _refresh_loop(self) -> None:
        interval = settings.autodj_refresh_interval
        while not self._stop_event.wait(timeout=60):
            elapsed = time.monotonic() - self._last_refresh
            if elapsed >= interval:
                logger.info("AutoDJ refreshing playlists")
                try:
                    self._refresh_playlists()
                except Exception as exc:
                    logger.error(f"AutoDJ refresh error: {exc}", exc_info=True)


autodj_manager = AutoDJManager()
