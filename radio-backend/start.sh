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

# ── Internal Icecast password ─────────────────────────────────────────────────
# Generate a clean random hex password so there are no special characters that
# could corrupt the XML or break FFmpeg's icecast:// URL parser.
# The user-supplied ICECAST_SOURCE_PASSWORD / ICECAST_PASSWORD is only used
# for external source clients (e.g. broadcasting from Mixxx). Internally the
# FastAPI backend always uses this generated value.
ICECAST_INTERNAL_PASS="$(openssl rand -hex 20)"
ICECAST_ADMIN_PASS="$(openssl rand -hex 20)"

# Force the backend to use the Icecast instance running inside this container.
# Railway may still have old env vars pointing to the separate Icecast service;
# override them so FFmpeg, the API, and Icecast all agree on localhost:8000/stream.
export ICECAST_HOST="localhost"
export ICECAST_PORT="8000"
export ICECAST_USER="source"
export ICECAST_MOUNT="/stream"
export ICECAST_PASSWORD="${ICECAST_INTERNAL_PASS}"
export ICECAST_NAME="Itachi Hits Radio"
export ICECAST_DESCRIPTION="Live internet radio stream"
export ICECAST_PUBLIC="0"

echo "[start.sh] Configuring Icecast (internal credentials generated)..."

# Use Python for XML patching — avoids all sed special-character issues.
python3 - <<PYEOF
import re, sys

path = "/etc/icecast2/icecast.xml"
src  = open(path).read()
sp   = "${ICECAST_INTERNAL_PASS}"
ap   = "${ICECAST_ADMIN_PASS}"

src = re.sub(r"<source-password>[^<]*</source-password>",
             f"<source-password>{sp}</source-password>", src)
src = re.sub(r"<relay-password>[^<]*</relay-password>",
             f"<relay-password>{sp}</relay-password>", src)
src = re.sub(r"<admin-password>[^<]*</admin-password>",
             f"<admin-password>{ap}</admin-password>", src)

# Ensure the public /stream mount is explicitly defined so listeners can hit it
# even if the source hasn't connected yet, and so source clients know the mount.
if "<mount-name>/stream" not in src:
    mount_block = """
    <mount>
        <mount-name>/stream</mount-name>
        <password>___MOUNT_SOURCE_PASS___</password>
        <max-listeners>1000</max-listeners>
        <burst-size>65536</burst-size>
    </mount>
"""
    mount_block = mount_block.replace("___MOUNT_SOURCE_PASS___", sp)
    src = src.replace("</icecast>", f"{mount_block}</icecast>")

open(path, "w").write(src)
print("[start.sh] Icecast XML patched OK")

# Verify
assert sp in open(path).read(), "source-password not found after patch!"
print("[start.sh] Icecast XML verification passed")
PYEOF

# ── Configure nginx ───────────────────────────────────────────────────────────
PORT="${PORT:-8080}"
echo "[start.sh] Configuring nginx on port ${PORT}..."
sed "s/__PORT__/${PORT}/g" /app/nginx.conf.template > /etc/nginx/sites-enabled/default

nginx -t

echo "[start.sh] All services configured. Launching via supervisord..."
exec supervisord -n -c /app/supervisord.conf
