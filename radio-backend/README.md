# Icecast Radio Backend

A production-grade internet radio backend that streams YouTube audio directly to Icecast via FFmpeg — no downloads, no temp files, everything in memory.

## Features

- **Zero-download streaming** — yt-dlp extracts audio URLs, FFmpeg streams them directly to Icecast
- **AutoDJ** — configurable YouTube playlists keep the radio playing forever
- **User queue** — REST API allows adding songs on demand; they play before AutoDJ resumes
- **Auto-recovery** — watchdog restarts crashed components; FFmpeg reconnects on Icecast drops
- **Never silent** — if a song fails, it's skipped and the next one plays immediately
- **Railway/Docker ready** — single Dockerfile, all config via environment variables

## Quick Start (Local)

### Prerequisites

- Docker & Docker Compose
- An Icecast server (included in docker-compose.yml)

### 1. Clone and configure

```bash
cp .env.example .env
# Edit .env with your Icecast credentials and AutoDJ playlists
```

### 2. Start with Docker Compose

```bash
docker compose up --build
```

The API will be available at `http://localhost:8000`.  
The Icecast server will be at `http://localhost:8080`.

### 3. Test the API

```bash
# Check health
curl http://localhost:8000/health

# Add a song
curl -X POST http://localhost:8000/play \
  -H "Content-Type: application/json" \
  -d '{"query": "lofi hip hop"}'

# Check now playing
curl http://localhost:8000/nowplaying
```

## Railway Deployment

### 1. Create a Railway project

```bash
npm install -g @railway/cli
railway login
railway init
```

### 2. Set environment variables in Railway dashboard

Copy all variables from `.env.example` and set them in the Railway project's **Variables** tab. At minimum:

| Variable | Description |
|---|---|
| `ICECAST_HOST` | Your Icecast server hostname |
| `ICECAST_PORT` | Icecast port (usually 8000) |
| `ICECAST_USER` | Icecast source user (usually `source`) |
| `ICECAST_PASSWORD` | Icecast source password |
| `ICECAST_MOUNT` | Mount point (e.g. `/stream`) |
| `AUTODJ_PLAYLISTS` | Comma-separated YouTube playlist URLs |

### 3. Deploy

```bash
railway up
```

Railway will use the `Dockerfile` automatically. The `railway.json` configures health checks and restart policy.

> **Note:** You need a separate Icecast server. Options:
> - Run Icecast on a VPS (cheap, full control)
> - Use another Railway service running the `moul/icecast` Docker image
> - Use a hosted Icecast provider

## Environment Variables

See `.env.example` for the full list with descriptions. Key variables:

| Variable | Default | Description |
|---|---|---|
| `ICECAST_HOST` | `localhost` | Icecast server hostname |
| `ICECAST_PORT` | `8000` | Icecast server port |
| `ICECAST_PASSWORD` | `hackme` | Source password |
| `ICECAST_MOUNT` | `/stream` | Mount point |
| `AUTODJ_PLAYLISTS` | _(empty)_ | Comma-separated YouTube playlist URLs |
| `AUTODJ_SHUFFLE` | `true` | Shuffle playlist order |
| `AUTODJ_REFRESH_INTERVAL` | `3600` | Playlist refresh interval (seconds) |
| `AUDIO_BITRATE` | `128` | MP3 bitrate (kbps) |
| `LOG_LEVEL` | `INFO` | Logging level |

## Project Structure

```
radio-backend/
├── main.py                     # FastAPI app + lifespan
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
├── railway.json
├── Procfile
├── start.sh
├── .env.example
├── API_DOCUMENTATION.md
└── app/
    ├── api/
    │   └── routes.py           # All REST endpoints
    ├── autodj/
    │   └── manager.py          # AutoDJ playlist manager
    ├── config/
    │   └── settings.py         # Pydantic settings (env vars)
    ├── ffmpeg/
    │   └── streamer.py         # FFmpeg subprocess lifecycle
    ├── icecast/
    │   └── connector.py        # Icecast status + metadata
    ├── logger/
    │   └── setup.py            # Rotating log file setup
    ├── models/
    │   └── schemas.py          # Pydantic request/response models
    ├── player/
    │   └── controller.py       # Main player loop (thread)
    ├── queue/
    │   └── manager.py          # Thread-safe FIFO queue
    ├── services/
    │   └── watchdog.py         # Component health monitoring
    ├── utils/
    │   └── startup.py          # Startup verification checks
    └── youtube/
        └── extractor.py        # yt-dlp URL extraction
```

## Streaming Pipeline

```
YouTube URL / Search Query
        │
        ▼
   yt-dlp (extract direct audio URL — no download)
        │
        ▼
   FFmpeg (transcode + stream via icecast:// protocol)
        │
        ▼
   Icecast Server
        │
        ▼
   Listeners (Winamp, VLC, browser, Discord bots, etc.)
```

## Playback Logic

1. **User queue** takes priority — any song added via `POST /play` plays before AutoDJ resumes
2. **AutoDJ** fills silence when the queue is empty — cycles through configured YouTube playlists
3. If a track fails for any reason (deleted, private, region-blocked, yt-dlp error, FFmpeg crash), it is skipped and the next track plays immediately
4. The radio **never stops**

## Logs

Log files are written to `LOG_DIR` (default: `/app/logs`):

| File | Contents |
|---|---|
| `player.log` | Track start/stop, skip, queue events |
| `api.log` | API request/response |
| `errors.log` | All errors with stack traces |
| `ffmpeg.log` | FFmpeg stderr output |
| `ytdlp.log` | yt-dlp extraction events |
| `startup.log` | Startup verification results |
| `autodj.log` | AutoDJ playlist loading and track selection |
| `watchdog.log` | Component health check results |

## Troubleshooting

**Radio is silent / not streaming:**
1. Check `GET /health` — look for `icecast: false`
2. Verify Icecast is reachable from the container (`ICECAST_HOST`, `ICECAST_PORT`)
3. Check `errors.log` for FFmpeg or yt-dlp errors

**AutoDJ not playing:**
1. Verify `AUTODJ_PLAYLISTS` contains valid public YouTube playlist URLs
2. Check `autodj.log` — playlists may have loaded 0 tracks
3. Ensure `AUTODJ_ENABLED=true`

**Songs being skipped:**
- Age-restricted, private, members-only, or region-blocked videos are automatically skipped
- Check `ytdlp.log` for skip reasons

**FFmpeg not found:**
- Ensure `ffmpeg` is installed: `which ffmpeg`
- Set `FFMPEG_PATH` to the full path if needed
