FROM python:3.12-slim

LABEL maintainer="Icecast Radio Backend"
LABEL description="All-in-one internet radio: FastAPI + Icecast + nginx in a single container"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONFAULTHANDLER=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DEBIAN_FRONTEND=noninteractive \
    LOG_DIR=/app/logs

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    curl \
    ca-certificates \
    icecast2 \
    supervisor \
    nginx \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --upgrade pip && \
    pip install -r requirements.txt

COPY . .

RUN mkdir -p /app/logs /var/log/nginx /run/nginx && \
    # icecast2 Debian package needs these dirs owned by its system user
    mkdir -p /var/log/icecast2 /var/run/icecast2 && \
    chown -R icecast2:icecast2 /var/log/icecast2 /var/run/icecast2 && \
    chmod +x /app/start.sh

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:${PORT:-8080}/health || exit 1

CMD ["/app/start.sh"]
