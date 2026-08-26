# syntax=docker/dockerfile:1
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    MEPIQ_DATA_DIR=/data

WORKDIR /app

# PyMuPDF ships manylinux wheels, so no build toolchain is needed. Keeping the
# image slim matters here: the API is CPU-bound on geometry, not on I/O, and a
# small image starts fast on scale-to-zero hosts.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY mepiq_core ./mepiq_core
COPY app ./app
COPY evaluate_dataset.py ./

RUN mkdir -p /data && useradd -m -u 10001 mepiq && chown -R mepiq /data /app
USER mepiq

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/api/health || exit 1

# Workers stay low by default: each analysis holds a whole sheet's geometry in
# memory, so concurrency is bounded by RAM rather than by CPU.
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
