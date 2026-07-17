#!/usr/bin/env python3
"""One-time YouTube OAuth2 setup for the Icecast radio backend.

YouTube blocks most cloud datacenter IPs (including Replit and Railway) with a
"Sign in to confirm you're not a bot" screen. Cookies alone are not enough from
these IPs. The only reliable fix is OAuth2 device-code authentication, which
gives yt-dlp a refreshable access token tied to your Google account.

Run this script once in an interactive shell, visit the URL it prints, and
enter the device code. Then copy the printed `YOUTUBE_OAUTH2_TOKEN_B64` value
into your Replit Secret / Railway variable and restart the app.
"""

from __future__ import annotations

import base64
import json
import os
import sys

import yt_dlp
from app.youtube.oauth_patch import _apply_youtube_oauth_patch

_apply_youtube_oauth_patch()

OAUTH2_TOKEN_CACHE_FILE = os.path.expanduser("~/.cache/yt-dlp/youtube-oauth2/token_data.json")


def _read_cached_token() -> dict | None:
    if not os.path.exists(OAUTH2_TOKEN_CACHE_FILE):
        return None
    try:
        with open(OAUTH2_TOKEN_CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        print(f"Warning: could not read cached token: {exc}", file=sys.stderr)
        return None


def _print_env_var(token_data: dict) -> None:
    b64 = base64.b64encode(json.dumps(token_data, separators=(",", ":")).encode("utf-8")).decode("utf-8")
    print("\n" + "=" * 60)
    print("Add this environment variable to Replit / Railway:")
    print("=" * 60)
    print(f"YOUTUBE_OAUTH2_TOKEN_B64={b64}")
    print("=" * 60)


def _run_authorization_flow() -> dict:
    """Trigger the OAuth2 device flow and return the cached token."""
    print("Starting YouTube OAuth2 device-code authorization...")
    print("When a URL and code appear, open the URL in a browser and enter the code.")
    print("(The script will wait here until you approve it.)\n")

    ydl_opts = {
        "username": "oauth2",
        "password": "",
        "format": "bestaudio/best",
        "quiet": False,
        "no_warnings": True,
        "noplaylist": True,
        "cachedir": os.path.expanduser("~/.cache/yt-dlp"),
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        # A lightweight extraction is enough to trigger _perform_login, which
        # initializes the OAuth2 flow and stores the token in the cache.
        info = ydl.extract_info(
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            download=False,
        )
        print(f"\nTest extraction succeeded: {info.get('title', 'Unknown') if info else 'n/a'}")

    token_data = _read_cached_token()
    if token_data is None:
        print("ERROR: Authorization appeared to succeed but no token was cached.", file=sys.stderr)
        sys.exit(1)
    return token_data


def main() -> None:
    cached = _read_cached_token()
    if cached is not None:
        print("A cached OAuth2 token already exists.")
        _print_env_var(cached)
        print("\nIf you want to re-authorize, delete the cache file:")
        print(f"  rm {OAUTH2_TOKEN_CACHE_FILE}")
        print("Then run this script again.")
        return

    token_data = _run_authorization_flow()
    _print_env_var(token_data)
    print("\nThen restart the application workflow so the server can use the token.")


if __name__ == "__main__":
    main()
