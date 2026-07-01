#!/usr/bin/env bash
set -euo pipefail

# Always run from the app directory so Python can resolve 'main' and 'app.*'
cd /app

echo "========================================"
echo "  Icecast Radio Backend — Starting Up"
echo "========================================"

mkdir -p "${LOG_DIR:-/app/logs}"

echo "[start.sh] Python: $(python --version)"
echo "[start.sh] FFmpeg: $(ffmpeg -version 2>&1 | head -1)"
echo "[start.sh] yt-dlp: $(python -m yt_dlp --version 2>&1 | head -1)"
echo "[start.sh] Working directory: $(pwd)"
echo "[start.sh] Files in /app: $(ls /app)"

# Diagnostic: try importing main.py and print the real error if it fails.
# This exposes the actual exception that uvicorn would otherwise swallow.
echo "[start.sh] Running import diagnostic..."
python - <<'PYEOF'
import sys, traceback
try:
    import main
    app = getattr(main, 'app', None)
    if app is None:
        print("DIAGNOSTIC: main.py imported but 'app' attribute is missing!", file=sys.stderr)
        sys.exit(1)
    print(f"DIAGNOSTIC: main.py imported OK, app={app}")
except Exception as exc:
    print(f"DIAGNOSTIC IMPORT ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
    traceback.print_exc(file=sys.stderr)
    sys.exit(1)
PYEOF

PORT="${PORT:-8000}"
echo "[start.sh] Starting Uvicorn on port ${PORT}"

exec python -m uvicorn main:app \
    --host "0.0.0.0" \
    --port "${PORT}" \
    --workers 1 \
    --log-level "$(echo "${LOG_LEVEL:-info}" | tr '[:upper:]' '[:lower:]')" \
    --access-log \
    --no-server-header
