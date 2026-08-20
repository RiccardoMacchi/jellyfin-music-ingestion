# syntax=docker/dockerfile:1

FROM python:3.12-slim AS base

# ffmpeg: conversione/validazione audio.
# curl:   usato dall'HEALTHCHECK per interrogare /api/health.
# gosu:   per droppare i privilegi da root all'utente applicativo dopo aver
#         allineato PUID/PGID (vedi docker-entrypoint.sh).
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg curl gosu \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Le dipendenze cambiano meno spesso del codice: layer separato per sfruttare
# la cache di build su rebuild successivi (importante su Coolify).
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend ./backend
COPY frontend ./frontend
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh

# Utente applicativo con UID/GID 1000 di default. A runtime l'entrypoint puo'
# riallinearlo ai valori PUID/PGID che passi (utile per far combaciare
# l'owner della tua libreria Jellyfin gia' esistente).
RUN groupadd -g 1000 appuser \
    && useradd -u 1000 -g appuser -m -s /usr/sbin/nologin appuser \
    && mkdir -p /music /data /downloads \
    && chown -R appuser:appuser /app /data /downloads \
    && chmod +x /usr/local/bin/docker-entrypoint.sh

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8000 \
    MUSIC_DIR=/music \
    DATA_DIR=/data \
    DOWNLOAD_DIR=/downloads \
    PUID=1000 \
    PGID=1000

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -fsS "http://127.0.0.1:${PORT}/api/health" || exit 1

# L'entrypoint parte come root SOLO per allineare l'utente e i permessi delle
# dir di stato, poi esegue l'app come utente non privilegiato tramite gosu.
# uvicorn inoltra SIGTERM al lifespan ASGI di FastAPI, che ferma la coda in
# modo pulito prima di uscire (vedi backend/main.py).
ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["sh", "-c", "uvicorn backend.main:app --host 0.0.0.0 --port ${PORT}"]
