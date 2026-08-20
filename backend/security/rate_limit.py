"""
Rate limiting minimale in-memory (per singolo processo/istanza container:
adeguato a un servizio self-hosted a bassa concorrenza, non pensato per
scalare orizzontalmente su piu' istanze).
"""
from __future__ import annotations

import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request

from backend.config import settings

_hits: dict[str, deque] = defaultdict(deque)


def _client_key(request: Request) -> str:
    return request.client.host if request.client else "unknown"


async def rate_limiter(request: Request) -> None:
    key = _client_key(request)
    window_seconds = 60.0
    now = time.monotonic()
    hits = _hits[key]

    while hits and now - hits[0] > window_seconds:
        hits.popleft()

    if len(hits) >= settings.rate_limit_per_minute:
        raise HTTPException(status_code=429, detail="Troppe richieste, riprova tra poco")

    hits.append(now)
