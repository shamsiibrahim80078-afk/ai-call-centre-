# VERIDIQ Telegram long-poll worker (Fly.io / any Docker host).
# Outbound getUpdates only — no public HTTP port required.
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    LOG_LEVEL=INFO \
    VERIDIQ_TELEGRAM_MODE=longpoll

WORKDIR /app

COPY requirements-telegram.txt .
RUN pip install --upgrade pip && \
    pip install -r requirements-telegram.txt

# Worker import chain needs the package tree + SQLite activity helper.
COPY database.py .
COPY veridiq/ veridiq/
COPY scripts/run_telegram_worker.py scripts/run_telegram_worker.py

# Non-root process (Fly runs as configured user; keep image portable).
RUN useradd --create-home --uid 1000 appuser && chown -R appuser:appuser /app
USER appuser

# Exec form so Fly SIGTERM reaches the Python process (graceful stop).
CMD ["python", "scripts/run_telegram_worker.py"]
