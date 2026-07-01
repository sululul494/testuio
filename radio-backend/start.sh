#!/usr/bin/env bash
set -euo pipefail

echo "========================================"
echo "  Icecast Radio Backend — Starting Up"
echo "========================================"

mkdir -p "${LOG_DIR:-/app/logs}"

echo "[start.sh] Python: $(python --version)"
echo "[start.sh] FFmpeg: $(ffmpeg -version 2>&1 | head -1)"
echo "[start.sh] yt-dlp: $(python -m yt_dlp --version 2>&1 | head -1)"

PORT="${PORT:-8000}"

echo "[start.sh] Starting Uvicorn on port ${PORT}"

exec python -m uvicorn main:app \
    --host "0.0.0.0" \
    --port "${PORT}" \
    --workers 1 \
    --log-level "${LOG_LEVEL:-info}" \
    --access-log \
    --no-server-header
