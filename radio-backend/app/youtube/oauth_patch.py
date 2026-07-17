from __future__ import annotations

import datetime
import json
import time
import urllib.error
import urllib.request
from typing import Any, Dict

from yt_dlp.utils import ExtractorError
from yt_dlp.utils.traversal import traverse_obj


def _apply_youtube_oauth_patch() -> None:
    """Patch yt-dlp-youtube-oauth2 to handle the YouTube OAuth2 device-code flow.

    The plugin as shipped sends ``code`` to the token endpoint, but the YouTube
    device-code endpoint expects ``device_code``. It also treats the expected
    OAuth2 400 error responses as fatal, so the authorization loop crashes
    before the user has a chance to approve the device. This patch fixes both
    issues by using the correct parameter and polling the endpoint directly
    with urllib so the JSON error body can be parsed.
    """
    try:
        import yt_dlp_plugins.extractor.youtubeoauth as plugin
    except Exception:
        # Plugin not installed; nothing to patch.
        return

    if getattr(plugin.YouTubeOAuth2Handler, "_radio_oauth_patched", False):
        return

    _CLIENT_ID = plugin._CLIENT_ID
    _CLIENT_SECRET = plugin._CLIENT_SECRET
    _SCOPES = plugin._SCOPES

    def _poll_token_endpoint(
        device_code: str, interval: int
    ) -> Dict[str, Any]:
        """Poll the YouTube OAuth2 token endpoint until success or terminal error."""
        data = json.dumps(
            {
                "client_id": _CLIENT_ID,
                "client_secret": _CLIENT_SECRET,
                "device_code": device_code,
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            }
        ).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        poll_interval = max(1, interval)

        while True:
            request = urllib.request.Request(
                "https://www.youtube.com/o/oauth2/token",
                data=data,
                headers=headers,
                method="POST",
            )
            try:
                with urllib.request.urlopen(request, timeout=30) as response:
                    token_response = json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                body = exc.read().decode("utf-8", errors="replace")
                try:
                    token_response = json.loads(body)
                except Exception as parse_exc:
                    raise ExtractorError(
                        f"OAuth2 token endpoint returned HTTP {exc.code}: {body[:200]}"
                    ) from parse_exc

            error = traverse_obj(token_response, "error")
            if error:
                if error == "authorization_pending":
                    time.sleep(poll_interval)
                    continue
                elif error == "slow_down":
                    poll_interval += 5
                    time.sleep(poll_interval)
                    continue
                elif error == "expired_token":
                    raise ExtractorError(
                        "The device code has expired. Please restart the authorization flow."
                    )
                else:
                    raise ExtractorError(f"Unhandled OAuth2 error: {error}")

            return token_response

    def _authorize(self) -> Dict[str, Any]:
        code_response = self._download_json(
            "https://www.youtube.com/o/oauth2/device/code",
            video_id="oauth2",
            note="Initializing OAuth2 Authorization Flow",
            data=json.dumps(
                {
                    "client_id": _CLIENT_ID,
                    "scope": _SCOPES,
                    "device_id": plugin.uuid.uuid4().hex,
                    "device_model": "ytlr::",
                }
            ).encode("utf-8"),
            headers={"Content-Type": "application/json", "__youtube_oauth__": True},
        )

        verification_url = code_response["verification_url"]
        user_code = code_response["user_code"]
        self.to_screen(
            f"To give yt-dlp access to your account, go to  {verification_url}  and enter code  {user_code}"
        )

        token_response = _poll_token_endpoint(
            code_response["device_code"], code_response.get("interval", 5)
        )
        self.to_screen("Authorization successful")
        return {
            "access_token": token_response["access_token"],
            "expires": datetime.datetime.now(datetime.timezone.utc).timestamp()
            + token_response["expires_in"],
            "refresh_token": token_response["refresh_token"],
            "token_type": token_response["token_type"],
        }

    def _refresh_token(self, refresh_token: str) -> Dict[str, Any]:
        data = json.dumps(
            {
                "client_id": _CLIENT_ID,
                "client_secret": _CLIENT_SECRET,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            "https://www.youtube.com/o/oauth2/token",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                token_response = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            try:
                token_response = json.loads(body)
            except Exception as parse_exc:
                self.report_warning(
                    f"Failed to refresh access token (HTTP {exc.code}): {body[:200]}. Restarting authorization flow"
                )
                return self.authorize()

        error = traverse_obj(token_response, "error")
        if error:
            self.report_warning(
                f"Failed to refresh access token: {error}. Restarting authorization flow"
            )
            return self.authorize()

        return {
            "access_token": token_response["access_token"],
            "expires": datetime.datetime.now(datetime.timezone.utc).timestamp()
            + token_response["expires_in"],
            "token_type": token_response["token_type"],
            "refresh_token": token_response.get("refresh_token", refresh_token),
        }

    plugin.YouTubeOAuth2Handler.authorize = _authorize
    plugin.YouTubeOAuth2Handler.refresh_token = _refresh_token
    plugin.YouTubeOAuth2Handler._radio_oauth_patched = True
