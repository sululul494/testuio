# Icecast Radio Backend — API Documentation

Base URL: `http://localhost:8000` (or your Railway/production URL)

All requests and responses use JSON. All endpoints return appropriate HTTP status codes.

---

## Endpoints

| Method | Path | Description |
|---|---|---|
| `POST` | `/play` | Add a song to the queue |
| `POST` | `/skip` | Skip the currently playing track |
| `POST` | `/remove` | Remove a track from the queue by position |
| `POST` | `/clear` | Clear the entire queue |
| `GET` | `/queue` | List all queued tracks |
| `GET` | `/nowplaying` | Get currently playing track info |
| `GET` | `/status` | Get overall system status |
| `GET` | `/health` | Health check (HTTP 200 = healthy, 503 = degraded) |
| `GET` | `/stats` | Playback statistics |

---

## POST /play

Add a track to the queue by YouTube URL or search query. yt-dlp resolves the track; if it is unavailable (private, deleted, age-restricted, etc.), a 422 is returned.

### Request body

Provide either `url` **or** `query` — not both.

```json
{
  "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
  "requested_by": "MyBot"
}
```

```json
{
  "query": "never gonna give you up",
  "requested_by": "MyBot"
}
```

| Field | Type | Required | Description |
|---|---|---|---|
| `url` | string | conditional | Full YouTube URL (video, short, music) |
| `query` | string | conditional | Search string — resolves to best match |
| `requested_by` | string | no | Label for who requested the track (default: `"API"`) |

### Response — 200 OK

```json
{
  "success": true,
  "message": "Track added to queue",
  "track": {
    "position": 1,
    "title": "Never Gonna Give You Up",
    "duration": "3:33",
    "url": "https://...",
    "thumbnail": "https://i.ytimg.com/vi/dQw4w9WgXcQ/maxresdefault.jpg",
    "requested_by": "MyBot"
  }
}
```

### Error responses

| Code | When |
|---|---|
| `400` | Neither `url` nor `query` provided |
| `422` | Track is unavailable (private, deleted, age-restricted, live stream, too long) |
| `502` | yt-dlp extraction failed (network error, rate limit, etc.) |
| `500` | Unexpected server error |

### Python example

```python
import requests

# By search query
r = requests.post(
    "http://localhost:8000/play",
    json={"query": "despacito", "requested_by": "MyDiscordBot"}
)
print(r.json())

# By URL
r = requests.post(
    "http://localhost:8000/play",
    json={"url": "https://www.youtube.com/watch?v=ktvTqknDobU"}
)
print(r.json())
```

---

## POST /skip

Skip the currently playing track. The player immediately moves to the next queued track or AutoDJ.

### Request body

None.

### Response — 200 OK

```json
{
  "success": true,
  "message": "Skip signal sent"
}
```

### Python example

```python
import requests

r = requests.post("http://localhost:8000/skip")
print(r.json())
```

---

## POST /remove

Remove a specific track from the queue by its 1-based position.

### Request body

```json
{
  "position": 2
}
```

| Field | Type | Required | Description |
|---|---|---|---|
| `position` | integer | yes | 1-based position in the queue |

### Response — 200 OK

```json
{
  "success": true,
  "message": "Removed: 'Bohemian Rhapsody'"
}
```

### Error responses

| Code | When |
|---|---|
| `400` | `position` is missing or < 1 |
| `404` | No track at the given position |

### Python example

```python
import requests

# Remove the second item in the queue
r = requests.post(
    "http://localhost:8000/remove",
    json={"position": 2}
)
print(r.json())
```

---

## POST /clear

Clear all tracks from the queue. The current track continues playing; AutoDJ resumes after it ends.

### Request body

None.

### Response — 200 OK

```json
{
  "success": true,
  "cleared": 5
}
```

### Python example

```python
import requests

r = requests.post("http://localhost:8000/clear")
print(r.json())
```

---

## GET /queue

List all tracks currently in the queue. Does not include the currently playing track.

### Response — 200 OK

```json
{
  "queue": [
    {
      "position": 1,
      "title": "Stairway to Heaven",
      "duration": "8:02",
      "url": "https://...",
      "thumbnail": "https://i.ytimg.com/vi/...",
      "requested_by": "Alice"
    },
    {
      "position": 2,
      "title": "Hotel California",
      "duration": "6:30",
      "url": "https://...",
      "thumbnail": "https://i.ytimg.com/vi/...",
      "requested_by": "Bob"
    }
  ],
  "total": 2
}
```

### Python example

```python
import requests

r = requests.get("http://localhost:8000/queue")
data = r.json()
print(f"Queue has {data['total']} tracks")
for track in data["queue"]:
    print(f"  {track['position']}. {track['title']} ({track['duration']})")
```

---

## GET /nowplaying

Get information about the currently playing track.

### Response — 200 OK (playing)

```json
{
  "title": "Bohemian Rhapsody",
  "channel": "",
  "duration": "5:55",
  "elapsed": "2:13",
  "remaining": "3:42",
  "thumbnail": "https://i.ytimg.com/vi/fJ9rUzIMcZQ/maxresdefault.jpg",
  "source_url": "https://...",
  "is_autodj": false,
  "queue_position": 1,
  "playing": true
}
```

### Response — 200 OK (idle)

```json
{
  "title": "Nothing playing",
  "channel": "",
  "duration": "0:00",
  "elapsed": "0:00",
  "remaining": "0:00",
  "thumbnail": "",
  "source_url": "",
  "is_autodj": false,
  "queue_position": null,
  "playing": false
}
```

| Field | Type | Description |
|---|---|---|
| `title` | string | Track title |
| `duration` | string | Total duration (M:SS or H:MM:SS) |
| `elapsed` | string | Time elapsed since track started |
| `remaining` | string | Estimated time remaining |
| `is_autodj` | boolean | `true` if AutoDJ is playing (no user request) |
| `queue_position` | integer or null | Position in queue (null for AutoDJ tracks) |
| `playing` | boolean | Whether audio is currently streaming |

### Python example

```python
import requests

r = requests.get("http://localhost:8000/nowplaying")
np = r.json()
if np["playing"]:
    print(f"Now playing: {np['title']}")
    print(f"  {np['elapsed']} / {np['duration']} ({np['remaining']} remaining)")
    print(f"  Source: {'AutoDJ' if np['is_autodj'] else 'User Queue'}")
else:
    print("Nothing playing")
```

---

## GET /status

Overall system status snapshot.

### Response — 200 OK

```json
{
  "playing": true,
  "connected_to_icecast": true,
  "queue_length": 3,
  "listeners": 12,
  "uptime": "2:14:33",
  "cpu_usage": 4.2,
  "memory_usage": 38.7,
  "bitrate": 128,
  "autodj_enabled": true,
  "current_source": "AutoDJ"
}
```

| Field | Type | Description |
|---|---|---|
| `playing` | boolean | Whether audio is streaming |
| `connected_to_icecast` | boolean | Last Icecast health check result |
| `queue_length` | integer | Number of tracks in user queue |
| `listeners` | integer | Current Icecast listener count |
| `uptime` | string | Time since server started |
| `cpu_usage` | float | CPU usage % |
| `memory_usage` | float | RAM usage % |
| `bitrate` | integer | Stream bitrate in kbps |
| `autodj_enabled` | boolean | Whether AutoDJ is configured |
| `current_source` | string | `"AutoDJ"`, `"User Queue"`, or `"Idle"` |

### Python example

```python
import requests

r = requests.get("http://localhost:8000/status")
status = r.json()
print(f"Playing: {status['playing']}")
print(f"Listeners: {status['listeners']}")
print(f"Uptime: {status['uptime']}")
```

---

## GET /health

Health check endpoint. Returns 200 only when all components are healthy. Useful for uptime monitors, Railway health checks, and load balancers.

### Response — 200 OK (healthy)

```json
{
  "status": "ok",
  "icecast": true,
  "ffmpeg": true,
  "queue": true,
  "player": true,
  "api": true
}
```

### Response — 503 Service Unavailable (degraded)

```json
{
  "status": "degraded",
  "icecast": false,
  "ffmpeg": true,
  "queue": true,
  "player": true,
  "api": true
}
```

### Python example

```python
import requests

r = requests.get("http://localhost:8000/health")
if r.status_code == 200:
    print("Radio backend is healthy")
else:
    health = r.json()
    print(f"Degraded: {health}")
```

---

## GET /stats

Playback statistics since server start.

### Response — 200 OK

```json
{
  "total_tracks_played": 142,
  "total_skips": 7,
  "total_errors": 3,
  "uptime_seconds": 14523.4,
  "autodj_tracks_played": 130,
  "user_tracks_played": 12,
  "current_listeners": 8,
  "peak_listeners": 24
}
```

### Python example

```python
import requests

r = requests.get("http://localhost:8000/stats")
stats = r.json()
print(f"Tracks played: {stats['total_tracks_played']}")
print(f"  AutoDJ: {stats['autodj_tracks_played']}")
print(f"  User: {stats['user_tracks_played']}")
print(f"Peak listeners: {stats['peak_listeners']}")
```

---

## Error Format

All error responses follow this structure:

```json
{
  "detail": "Human-readable error message"
}
```

---

## Complete Bot Example

```python
import requests
from time import sleep

BASE_URL = "http://localhost:8000"

def add_song(query: str, requested_by: str = "Bot") -> dict:
    r = requests.post(f"{BASE_URL}/play", json={
        "query": query,
        "requested_by": requested_by
    })
    r.raise_for_status()
    return r.json()

def skip() -> dict:
    return requests.post(f"{BASE_URL}/skip").json()

def get_queue() -> list:
    return requests.get(f"{BASE_URL}/queue").json()["queue"]

def now_playing() -> dict:
    return requests.get(f"{BASE_URL}/nowplaying").json()

def clear_queue() -> dict:
    return requests.post(f"{BASE_URL}/clear").json()

def status() -> dict:
    return requests.get(f"{BASE_URL}/status").json()

if __name__ == "__main__":
    # Add some songs
    add_song("despacito", requested_by="Alice")
    add_song("https://www.youtube.com/watch?v=dQw4w9WgXcQ", requested_by="Bob")

    # Check queue
    queue = get_queue()
    print(f"Queue: {[t['title'] for t in queue]}")

    # Check now playing
    np = now_playing()
    print(f"Now playing: {np['title']} ({np['elapsed']} elapsed)")

    # System status
    s = status()
    print(f"Listeners: {s['listeners']}, Uptime: {s['uptime']}")

    # Skip current track
    skip()
    sleep(1)
    print(f"After skip: {now_playing()['title']}")
```
