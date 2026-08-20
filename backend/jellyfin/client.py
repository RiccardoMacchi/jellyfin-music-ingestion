"""
Integrazione opzionale con l'API Jellyfin: dopo un inserimento riuscito in
libreria, se JELLYFIN_ENABLED=true, chiede un refresh della libreria.

Un fallimento qui NON deve mai far fallire il download: il file e' gia'
correttamente presente in /music a prescindere da Jellyfin. Per questo ogni
funzione qui cattura le proprie eccezioni e si limita a loggare.
"""
from __future__ import annotations

import httpx

from backend.config import settings
from backend.utils.logging import get_logger

logger = get_logger(__name__)


async def trigger_library_refresh() -> bool:
    """Ritorna True se il refresh e' stato richiesto con successo, False
    altrimenti (compreso il caso JELLYFIN_ENABLED=false). Non solleva mai."""
    if not settings.jellyfin_enabled:
        return False
    if not settings.jellyfin_url or not settings.jellyfin_api_key:
        logger.warning("JELLYFIN_ENABLED=true ma URL/API key mancanti: refresh saltato")
        return False

    url = settings.jellyfin_url.rstrip("/") + "/Library/Refresh"
    headers = {"X-Emby-Token": settings.jellyfin_api_key}

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(url, headers=headers)
            response.raise_for_status()
        logger.info("Refresh libreria Jellyfin richiesto con successo")
        return True
    except Exception as exc:  # qualunque errore di rete/HTTP: non fatale
        logger.warning("Refresh libreria Jellyfin fallito (non bloccante): %s", exc)
        return False
