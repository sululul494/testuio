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

# ── Validate required secrets ─────────────────────────────────────────────────
# Accept ICECAST_PASSWORD or ICECAST_SOURCE_PASSWORD (Railway uses the latter).
ICECAST_PASSWORD="${ICECAST_PASSWORD:-${ICECAST_SOURCE_PASSWORD:-}}"
if [[ -z "${ICECAST_PASSWORD}" ]]; then
  echo "[start.sh] ERROR: Set ICECAST_PASSWORD (or ICECAST_SOURCE_PASSWORD) in Railway env vars." >&2
  exit 1
fi
export ICECAST_PASSWORD

ICECAST_ADMIN_PASS="${ICECAST_ADMIN_PASSWORD:-${ICECAST_PASSWORD}}"

# ── Configure Icecast ─────────────────────────────────────────────────────────
# Escape sed replacement metacharacters so passwords with & or \ don't corrupt XML.
escape_sed() {
  printf '%s' "$1" | sed 's/\\/\\\\/g; s/&/\\\&/g; s/|/\\|/g'
}

SAFE_SOURCE=$(escape_sed "${ICECAST_PASSWORD}")
SAFE_ADMIN=$(escape_sed "${ICECAST_ADMIN_PASS}")

echo "[start.sh] Configuring Icecast..."
sed -i "s|<source-password>[^<]*</source-password>|<source-password>${SAFE_SOURCE}</source-password>|g" \
    /etc/icecast2/icecast.xml
sed -i "s|<relay-password>[^<]*</relay-password>|<relay-password>${SAFE_SOURCE}</relay-password>|g" \
    /etc/icecast2/icecast.xml
sed -i "s|<admin-password>[^<]*</admin-password>|<admin-password>${SAFE_ADMIN}</admin-password>|g" \
    /etc/icecast2/icecast.xml
# Icecast listens on 8000 internally — nginx proxies it externally
sed -i "s|<port>[^<]*</port>|<port>8000</port>|g" /etc/icecast2/icecast.xml

# ── Configure nginx ───────────────────────────────────────────────────────────
PORT="${PORT:-8080}"
echo "[start.sh] Configuring nginx on port ${PORT}..."
sed "s/__PORT__/${PORT}/g" /app/nginx.conf.template > /etc/nginx/sites-enabled/default

nginx -t

echo "[start.sh] All services configured. Launching via supervisord..."
exec supervisord -n -c /app/supervisord.conf
