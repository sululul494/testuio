---
name: YouTube OAuth2 from cloud IPs
description: How to make yt-dlp work from Replit/Railway datacenter IPs where cookies alone are blocked.
---

YouTube treats most cloud datacenter IPs (Replit, Railway, etc.) as bots and returns "Sign in to confirm you're not a bot" even when valid cookies are supplied. The only reliable fix is OAuth2 device-code authentication via the `yt-dlp-youtube-oauth2` plugin.

**How it works:**

- The plugin dynamically subclasses every YouTube extractor and intercepts requests.
- It only activates when `YoutubeDL` is created with `username='oauth2'` and `password=''`.
- On first use it prints a device URL + code; after the user approves it, it stores a refreshable token in the yt-dlp cache.
- The cache file is `~/.cache/yt-dlp/youtube-oauth2/token_data.json` (wrapped as `{"yt-dlp_version": "...", "data": {...}}`).

**Server-side setup:**

1. Run the setup script once in an interactive shell:
   ```bash
   python3 setup_youtube_oauth.py
   ```
2. Copy the printed `YOUTUBE_OAUTH2_TOKEN_B64` value into a Replit Secret / Railway variable.
3. On startup the server decodes that value and writes it to the yt-dlp cache so the plugin can load the token without prompting.
4. When a token is present, the extractor uses `username='oauth2'`, `password=''` and switches to the authenticated `web` player client instead of `tv_embedded`.

**Why:** Cookies bypass age-restriction and some checks, but the "bot" decision is IP-based. OAuth2 tokens are tied to a real Google account and are trusted from any IP.
