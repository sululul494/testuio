from __future__ import annotations

import queue
import threading
import time
from typing import List, Optional

from app.logger.setup import get_logger
from app.models.schemas import TrackInfo

logger = get_logger("player")


class QueueManager:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._items: List[TrackInfo] = []
        self._condition = threading.Condition(self._lock)

    def add(self, track: TrackInfo) -> None:
        with self._condition:
            track.position = len(self._items) + 1
            self._items.append(track)
            self._reindex()
            self._condition.notify_all()
        logger.info(f"Queued: {track.title!r} by {track.requested_by}")

    def pop_next(self) -> Optional[TrackInfo]:
        with self._condition:
            if not self._items:
                return None
            track = self._items.pop(0)
            self._reindex()
            self._condition.notify_all()
            return track

    def peek_next(self) -> Optional[TrackInfo]:
        with self._lock:
            return self._items[0] if self._items else None

    def remove_at(self, position: int) -> Optional[TrackInfo]:
        with self._condition:
            idx = position - 1
            if idx < 0 or idx >= len(self._items):
                return None
            track = self._items.pop(idx)
            self._reindex()
            self._condition.notify_all()
            logger.info(f"Removed from queue: {track.title!r}")
            return track

    def clear(self) -> int:
        with self._condition:
            count = len(self._items)
            self._items.clear()
            self._condition.notify_all()
            logger.info(f"Queue cleared ({count} items removed)")
            return count

    def list(self) -> List[TrackInfo]:
        with self._lock:
            return list(self._items)

    def size(self) -> int:
        with self._lock:
            return len(self._items)

    def is_empty(self) -> bool:
        with self._lock:
            return len(self._items) == 0

    def _reindex(self) -> None:
        for i, item in enumerate(self._items):
            item.position = i + 1

    def is_alive(self) -> bool:
        return True


queue_manager = QueueManager()
