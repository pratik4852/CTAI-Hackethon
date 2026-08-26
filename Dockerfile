# syntax=docker/dockerfile:1
#
# Single-container build: the API serves the built React bundle from the same
# origin and port. This is the simplest thing to deploy — one image, one port,
# no reverse proxy and no CORS configuration — which is what most PaaS hosts
# (Render, Railway, Fly, Cloud Run, App Runner) want.
#
#   docker build -t mepiq .
#   docker run -p 8000:8000 -v mepiq-data:/data mepiq
#
# Use docker-compose.yml instead if you want the API and web tiers separated.

FROM node:20-alpine AS web

WORKDIR /web
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install --no-audit --no-fund
COPY frontend/ ./
ENV VITE_API_BASE=""
RUN npm run build


FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    MEPIQ_DATA_DIR=/data \
    MEPIQ_STATIC_DIR=/app/static \
    PORT=8000

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/mepiq_core ./mepiq_core
COPY backend/app ./app
COPY backend/evaluate_dataset.py ./
COPY --from=web /web/dist ./static

RUN mkdir -p /data && useradd -m -u 10001 mepiq && chown -R mepiq /data /app
USER mepiq

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=25s --retries=3 \
    CMD curl -fsS "http://127.0.0.1:${PORT}/api/health" || exit 1

# $PORT is honoured so the same image runs unchanged on Render, Railway,
# Cloud Run and Fly.
CMD ["sh", "-c", "python -m uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
