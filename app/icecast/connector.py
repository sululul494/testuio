from __future__ import annotations

import time
from typing import Any, Dict, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from app.config.settings import settings
from app.logger.setup import get_logger

logger = get_logger("player")


class IcecastConnector:
    def __init__(self) -> None:
        self._session = self._make_session()
        self._connected: bool = False
        self._listeners: int = 0

    def _make_session(self) -> requests.Session:
        session = requests.Session()
        retry = Retry(
            total=3,
            backoff_factor=0.5,
            status_forcelist=[500, 502, 503, 504],
        )
        adapter = HTTPAdapter(max_retries=retry)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        return session

    def check_connection(self) -> bool:
        try:
            resp = self._session.get(
                settings.icecast_stats_url,
                timeout=5,
                auth=(settings.icecast_user, settings.icecast_password),
            )
            if resp.status_code == 200:
                self._connected = True
                self._parse_listeners(resp.json())
                return True
            self._connected = False
            return False
        except Exception as exc:
            logger.warning(f"Icecast connection check failed: {exc}")
            self._connected = False
            return False

    def is_connected(self) -> bool:
        return self._connected

    def get_listeners(self) -> int:
        return self._listeners

    def _parse_listeners(self, data: Any) -> None:
        try:
            icestats = data.get("icestats", {})
            source = icestats.get("source")
            if source is None:
                self._listeners = 0
                return
            if isinstance(source, list):
                sources = source
            else:
                sources = [source]
            mount = settings.icecast_mount
            for src in sources:
                if src.get("listenurl", "").endswith(mount):
                    self._listeners = int(src.get("listeners", 0))
                    return
            self._listeners = 0
        except Exception:
            self._listeners = 0

    def update_metadata(self, title: str) -> None:
        try:
            url = (
                f"http://{settings.icecast_host}:{settings.icecast_port}"
                f"/admin/metadata?mount={settings.icecast_mount}"
                f"&mode=updinfo&song={requests.utils.quote(title)}"
            )
            self._session.get(
                url,
                auth=(settings.icecast_user, settings.icecast_password),
                timeout=3,
            )
        except Exception as exc:
            logger.debug(f"Metadata update failed: {exc}")


icecast_connector = IcecastConnector()
