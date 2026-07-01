#!/usr/bin/env bash
set -euo pipefail

cd /app

echo "========================================"
echo "  Icecast Radio Backend — Starting Up"
echo "========================================"

mkdir -p "${LOG_DIR:-/app/logs}"

echo "[start.sh] Python: $(python --version)"
echo "[start.sh] FFmpeg: $(ffmpeg -version 2>&1 | head -1)"
echo "[start.sh] yt-dlp: $(python -m yt_dlp --version 2>&1 | head -1)"

# ── Configure Icecast ─────────────────────────────────────────────────────────
# Icecast runs internally on port 8000. The API connects to it at localhost:8000.
# Listeners reach it externally via nginx at /stream.
ICECAST_SOURCE_PASS="${ICECAST_PASSWORD:-hackme}"
ICECAST_ADMIN_PASS="${ICECAST_ADMIN_PASSWORD:-${ICECAST_PASSWORD:-hackme}}"

echo "[start.sh] Configuring Icecast..."
sed -i "s|<source-password>[^<]*</source-password>|<source-password>${ICECAST_SOURCE_PASS}</source-password>|g" \
    /etc/icecast2/icecast.xml
sed -i "s|<relay-password>[^<]*</relay-password>|<relay-password>${ICECAST_SOURCE_PASS}</relay-password>|g" \
    /etc/icecast2/icecast.xml
sed -i "s|<admin-password>[^<]*</admin-password>|<admin-password>${ICECAST_ADMIN_PASS}</admin-password>|g" \
    /etc/icecast2/icecast.xml
# Ensure Icecast listens on port 8000
sed -i "s|<port>[^<]*</port>|<port>8000</port>|g" /etc/icecast2/icecast.xml

# ── Configure nginx ───────────────────────────────────────────────────────────
# nginx listens on Railway's $PORT and proxies to icecast (8000) and api (8099)
PORT="${PORT:-8080}"
echo "[start.sh] Configuring nginx on port ${PORT}..."
sed "s/__PORT__/${PORT}/g" /app/nginx.conf.template > /etc/nginx/sites-enabled/default

# Remove nginx default welcome page config if it exists separately
rm -f /etc/nginx/sites-enabled/default.bak

# Test nginx config
nginx -t

echo "[start.sh] All services configured. Launching via supervisord..."
exec supervisord -n -c /app/supervisord.conf
