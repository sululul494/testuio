# Icecast Radio Backends

A production-grade internet radio backend that streams YouTube audio directly to a local Icecast server via FFmpeg — zero downloads, all in memory.

## Run & Operate

- `bash start-replit.sh` — start Icecast (port 8000) and the FastAPI backend (port 5000)
- The workflow `Start application` is configured to run the same command automatically
- API docs: `https://<your-replit-domain>/docs`
- Icecast admin/status: `http://localhost:8000/status.xsl`

## Stack

- Python 3.12 + FastAPI + Uvicorn
- Pydantic Settings for env-driven configuration
- FFmpeg (libmp3lame) → local Icecast mount `/stream`
- yt-dlp for in-memory URL extraction
- AutoDJ, user request queue, watchdog, metadata updates

## Where things live

- `main.py` — FastAPI app and lifespan startup
- `app/` — radio backend modules
- `icecast-replit.xml` — Icecast configuration tuned for Replit
- `start-replit.sh` — Replit run script
- `requirements.txt` — Python dependencies

## Configuration

Managed through Replit environment variables (shared). Required/sensitive:

- `ICECAST_PASSWORD` — source password (stored as a Replit Secret)

Other non-secret vars are set in Replit env, including `ICECAST_HOST`, `ICECAST_PORT`, `ICECAST_MOUNT`, `AUTODJ_PLAYLISTS`, `AUDIO_BITRATE`, etc. See `.env.example` in the source for the full list.

## User preferences

- None yet — populate here as the user gives explicit guidance.

## OAuth2 setup (required for YouTube playback from cloud IPs)

YouTube blocks Replit/Railway datacenter IPs with a "Sign in to confirm you're not a bot" screen. Cookies alone do not bypass this. The only reliable fix is OAuth2 device-code authentication:

1. Open the **Shell** tab and generate a device code:
   ```bash
   python3 setup_youtube_oauth.py generate
   ```
2. Visit the URL it prints and enter the device code.
3. Once approved, retrieve the token:
   ```bash
   python3 setup_youtube_oauth.py finish
   ```
4. Copy the printed `YOUTUBE_OAUTH2_TOKEN_B64` value.
5. Add it as a **Replit Secret** (and a Railway variable) named `YOUTUBE_OAUTH2_TOKEN_B64`.
6. Restart the `Start application` workflow.

The token is refreshable, so the one-time setup keeps working. `YOUTUBE_COOKIES_B64` is ignored when OAuth2 is configured.

## iOS / Safari stream

iOS AVFoundation cannot use the Icecast ICY protocol on port 8000. A `/stream` proxy endpoint is available on the FastAPI port (5000) that re-serves the MP3 bytes over plain HTTP with standard headers. Use that URL for mobile listeners.

## Gotchas

- Icecast XML and the FastAPI backend both expect the same `ICECAST_PASSWORD`. If you change one, change the other and restart the workflow.
- The iOS-friendly stream mount was added to `icecast-replit.xml` with a larger `burst-size` and `client-timeout` to reduce rebuffering on mobile networks.
- YouTube cookies can be supplied via the `YOUTUBE_COOKIES_B64` env var, but they are ignored when `YOUTUBE_OAUTH2_TOKEN_B64` is present because OAuth2 is the only reliable method from cloud IPs.

## Pointers

- See `radio-backend/README.md` (original) for full API documentation and troubleshooting.
