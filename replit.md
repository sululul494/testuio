# Icecast Radio Backend

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

## Gotchas

- Icecast XML and the FastAPI backend both expect the same `ICECAST_PASSWORD`. If you change one, change the other and restart the workflow.
- The iOS-friendly stream mount was added to `icecast-replit.xml` with a larger `burst-size` and `client-timeout` to reduce rebuffering on mobile networks.
- YouTube cookies can be supplied via the `YOUTUBE_COOKIES_B64` env var if extractions fail on cloud IPs.

## Pointers

- See `radio-backend/README.md` (original) for full API documentation and troubleshooting.
