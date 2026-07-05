---
name: YouTube cookies on Replit cloud
description: yt-dlp from Replit cloud IPs usually hits YouTube bot checks; base64 cookies in YOUTUBE_COOKIES_B64 are needed for playback.
---

# YouTube cookies on Replit cloud

## Rule
When a Replit project uses yt-dlp to extract YouTube audio, expect "Sign in to confirm you're not a bot" errors from cloud IPs. The fix is to provide a logged-in browser's cookies via the `YOUTUBE_COOKIES_B64` environment variable (or secret), not to change the app code.

**Why:** YouTube aggressively blocks datacenter/cloud IP ranges. The app already has `youtube_cookies_b64` support; it just needs the value.

**How to apply:**
1. Export cookies from a logged-in browser in Netscape format.
2. Base64-encode them.
3. Store the result as `YOUTUBE_COOKIES_B64` in Replit Secrets or env vars.
4. Verify with a real track extraction from the `/play` endpoint.
