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
# Fail fast — never fall back to insecure defaults in production.
if [[ -z "${ICECAST_PASSWORD:-}" ]]; then
  echo "[start.sh] ERROR: ICECAST_PASSWORD is not set. Set it in Railway environment variables." >&2
  exit 1
fi

ICECAST_SOURCE_PASS="${ICECAST_PASSWORD}"
ICECAST_ADMIN_PASS="${ICECAST_ADMIN_PASSWORD:-${ICECAST_PASSWORD}}"

# ── Configure Icecast ─────────────────────────────────────────────────────────
# Escape sed replacement metacharacters (&, \, |) so passwords with special
# characters cannot corrupt the XML or break the sed expression.
escape_sed() {
  # Escape backslash first, then &, then the sed delimiter (|)
  printf '%s' "$1" | sed 's/\\/\\\\/g; s/&/\\\&/g; s/|/\\|/g'
}

SAFE_SOURCE=$(escape_sed "${ICECAST_SOURCE_PASS}")
SAFE_ADMIN=$(escape_sed "${ICECAST_ADMIN_PASS}")

echo "[start.sh] Configuring Icecast..."
sed -i "s|<source-password>[^<]*</source-password>|<source-password>${SAFE_SOURCE}</source-password>|g" \
    /etc/icecast2/icecast.xml
sed -i "s|<relay-password>[^<]*</relay-password>|<relay-password>${SAFE_SOURCE}</relay-password>|g" \
    /etc/icecast2/icecast.xml
sed -i "s|<admin-password>[^<]*</admin-password>|<admin-password>${SAFE_ADMIN}</admin-password>|g" \
    /etc/icecast2/icecast.xml
# Ensure Icecast listens on port 8000 (internal only — nginx proxies externally)
sed -i "s|<port>[^<]*</port>|<port>8000</port>|g" /etc/icecast2/icecast.xml

# ── Configure nginx ───────────────────────────────────────────────────────────
PORT="${PORT:-8080}"
echo "[start.sh] Configuring nginx on port ${PORT}..."
sed "s/__PORT__/${PORT}/g" /app/nginx.conf.template > /etc/nginx/sites-enabled/default

# Test nginx config before launching
nginx -t

echo "[start.sh] All services configured. Launching via supervisord..."
exec supervisord -n -c /app/supervisord.conf
