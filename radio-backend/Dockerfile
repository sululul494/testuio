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
    openssl \
    icecast2 \
    supervisor \
    nginx \
    nodejs \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --upgrade pip && \
    pip install -r requirements.txt

COPY . .

RUN mkdir -p /app/logs /var/log/nginx /run/nginx && \
    # Create icecast2 system user/group explicitly — DEBIAN_FRONTEND=noninteractive
    # skips postinst scripts on python:3.12-slim so the package doesn't create them.
    getent group icecast2 || groupadd --system icecast2 && \
    getent passwd icecast2 || useradd --system --no-create-home --gid icecast2 icecast2 && \
    mkdir -p /var/log/icecast2 /var/run/icecast2 && \
    chown -R icecast2:icecast2 /var/log/icecast2 /var/run/icecast2 && \
    chmod +x /app/start.sh

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:${PORT:-8080}/health || exit 1

CMD ["/app/start.sh"]
