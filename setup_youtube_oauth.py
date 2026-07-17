#!/usr/bin/env python3
"""One-time YouTube OAuth2 setup for the Icecast radio backend.

YouTube blocks most cloud datacenter IPs (including Replit and Railway) with a
"Sign in to confirm you're not a bot" screen. Cookies alone are not enough from
these IPs. The only reliable fix is OAuth2 device-code authentication, which
gives yt-dlp a refreshable access token tied to your Google account.

Usage (recommended for agent/headless use):

    python3 setup_youtube_oauth.py generate
    # Visit the URL it prints and enter the device code.
    python3 setup_youtube_oauth.py finish

The first command saves the device code and prints the user-facing URL/code. The
second command polls the token endpoint, writes the token to the yt-dlp cache,
and prints the `YOUTUBE_OAUTH2_TOKEN_B64` value to add as a Replit Secret /
Railway variable.
"""

from __future__ import annotations

import argparse
import base64
import datetime
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid

import yt_dlp

CLIENT_ID = "861556708454-d6dlm3lh05idd8npek18k6be8ba3oc68.apps.googleusercontent.com"
CLIENT_SECRET = "SboVhoG9s0rNafixCSGGKXAT"
SCOPES = "https://gdata.youtube.com https://www.googleapis.com/auth/youtube"

DEVICE_CODE_FILE = os.path.expanduser("~/.cache/yt-dlp/youtube-oauth2/device_code.json")
OAUTH2_TOKEN_CACHE_FILE = os.path.expanduser("~/.cache/yt-dlp/youtube-oauth2/token_data.json")


def _cache_dir() -> str:
    return os.path.expanduser("~/.cache/yt-dlp")


def _read_cached_token() -> dict | None:
    if not os.path.exists(OAUTH2_TOKEN_CACHE_FILE):
        return None
    try:
        # yt-dlp wraps cached values in a version object. Try the official loader first.
        with yt_dlp.YoutubeDL({"quiet": True, "cachedir": _cache_dir()}) as ydl:
            return ydl.cache.load("youtube-oauth2", "token_data")
    except Exception:
        # Fallback: read the wrapper file directly and return the inner data.
        try:
            with open(OAUTH2_TOKEN_CACHE_FILE, "r", encoding="utf-8") as f:
                wrapper = json.load(f)
            return wrapper.get("data") if isinstance(wrapper.get("data"), dict) else wrapper
        except Exception:
            return None


def _write_cache_token(token_data: dict) -> None:
    os.makedirs(os.path.dirname(OAUTH2_TOKEN_CACHE_FILE), exist_ok=True)
    with yt_dlp.YoutubeDL({"quiet": True, "cachedir": _cache_dir()}) as ydl:
        ydl.cache.store("youtube-oauth2", "token_data", token_data)


def _print_env_var(token_data: dict) -> None:
    b64 = base64.b64encode(
        json.dumps(token_data, separators=(",", ":")).encode("utf-8")
    ).decode("utf-8")
    print("\n" + "=" * 60)
    print("Add this environment variable to Replit / Railway:")
    print("=" * 60)
    print(f"YOUTUBE_OAUTH2_TOKEN_B64={b64}")
    print("=" * 60)


def _request_device_code() -> dict:
    req = urllib.request.Request(
        "https://www.youtube.com/o/oauth2/device/code",
        data=json.dumps(
            {
                "client_id": CLIENT_ID,
                "scope": SCOPES,
                "device_id": uuid.uuid4().hex,
                "device_model": "ytlr::",
            }
        ).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _poll_token_endpoint(device_code: str, interval: int, timeout: int = 300) -> dict:
    data = json.dumps(
        {
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "device_code": device_code,
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
        }
    ).encode("utf-8")
    poll_interval = max(1, interval)
    deadline = time.monotonic() + timeout

    while time.monotonic() < deadline:
        req = urllib.request.Request(
            "https://www.youtube.com/o/oauth2/token",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                token_response = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            try:
                token_response = json.loads(body)
            except Exception as parse_exc:
                raise RuntimeError(
                    f"OAuth2 token endpoint returned HTTP {exc.code}: {body[:200]}"
                ) from parse_exc

        error = token_response.get("error")
        if error:
            if error == "authorization_pending":
                print("Waiting for authorization...", file=sys.stderr)
                time.sleep(poll_interval)
                continue
            elif error == "slow_down":
                poll_interval += 5
                time.sleep(poll_interval)
                continue
            elif error == "expired_token":
                raise RuntimeError(
                    "The device code has expired. Please run 'generate' again."
                )
            else:
                raise RuntimeError(f"Unhandled OAuth2 error: {error}")

        return token_response

    raise RuntimeError("Timed out waiting for OAuth2 authorization.")


def cmd_generate() -> None:
    cached = _read_cached_token()
    if cached is not None:
        print("A cached OAuth2 token already exists.")
        _print_env_var(cached)
        return

    code_response = _request_device_code()
    os.makedirs(os.path.dirname(DEVICE_CODE_FILE), exist_ok=True)
    with open(DEVICE_CODE_FILE, "w", encoding="utf-8") as f:
        json.dump(code_response, f)
    print("\nDevice code saved. Authorize this device:")
    print(f"  URL: {code_response['verification_url']}")
    print(f"  Code: {code_response['user_code']}")
    print(f"\nThen run: python3 {os.path.basename(__file__)} finish")


def cmd_finish() -> None:
    if not os.path.exists(DEVICE_CODE_FILE):
        print("No saved device code. Run 'generate' first.", file=sys.stderr)
        sys.exit(1)
    with open(DEVICE_CODE_FILE, "r", encoding="utf-8") as f:
        code_response = json.load(f)

    print("Polling for authorization...")
    token_response = _poll_token_endpoint(
        code_response["device_code"], code_response.get("interval", 5)
    )
    token_data = {
        "access_token": token_response["access_token"],
        "expires": datetime.datetime.now(datetime.timezone.utc).timestamp()
        + token_response["expires_in"],
        "refresh_token": token_response["refresh_token"],
        "token_type": token_response["token_type"],
    }
    _write_cache_token(token_data)
    print("Token written to yt-dlp cache.")
    _print_env_var(token_data)
    print("\nThen restart the application workflow so the server can use the token.")
    try:
        os.remove(DEVICE_CODE_FILE)
    except Exception:
        pass


def main() -> None:
    parser = argparse.ArgumentParser(
        description="YouTube OAuth2 setup for the Icecast radio backend"
    )
    parser.add_argument(
        "command",
        choices=["generate", "finish"],
        default=None,
        nargs="?",
        help="generate a device code, or finish and retrieve the token",
    )
    args = parser.parse_args()

    if args.command == "generate":
        cmd_generate()
    elif args.command == "finish":
        cmd_finish()
    else:
        # Interactive default: generate, wait for Enter, then finish.
        cmd_generate()
        print("\nPress Enter after authorizing the device...")
        input()
        cmd_finish()


if __name__ == "__main__":
    main()
