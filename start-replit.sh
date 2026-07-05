#!/usr/bin/env bash
set -euo pipefail

cd /home/runner/workspace

echo "========================================"
echo "  Icecast Radio Backend — Replit"
echo "========================================"

# Create log dir
mkdir -p icecast-data/log

echo "[start] Python: $(python3 --version)"
echo "[start] FFmpeg: $(ffmpeg -version 2>&1 | head -1)"
echo "[start] yt-dlp: $(python3 -m yt_dlp --version 2>&1 | head -1)"

# ── Start Icecast ─────────────────────────────────────────────────────────────
echo "[start] Starting Icecast on port 8000..."
icecast -b -c /home/runner/workspace/icecast-replit.xml
sleep 2

# Verify Icecast started
if ! curl -sf http://localhost:8000/status-json.xsl > /dev/null 2>&1; then
  echo "[start] Warning: Icecast not responding yet, waiting..."
  sleep 3
fi
echo "[start] Icecast is up."

# ── Start FastAPI (on port 8099, nginx-like proxy via Replit's port 5000) ─────
echo "[start] Starting FastAPI on port 5000..."
exec python3 -m uvicorn main:app \
  --host 0.0.0.0 \
  --port 5000 \
  --workers 1 \
  --log-level info \
  --access-log \
  --no-server-header
