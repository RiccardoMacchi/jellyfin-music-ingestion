"""
Streaming di progresso (Server-Sent Events).

Scelta rispetto a WebSocket: SSE e' unidirezionale (perfetto qui, la UI non
deve mandare comandi su questo canale), si integra nativamente con
EventSource nel browser senza librerie aggiuntive, e attraversa proxy/reverse
proxy (incluso quello davanti a Coolify) senza configurazioni particolari.

L'endpoint fa polling leggero del DB (il DB e' comunque la fonte di verita'
per via della coda persistente) mentre e' "sveglio" dall'event bus quando un
job pubblica un aggiornamento, cosi' la latenza percepita resta bassa senza
dover gestire la complessita' di un bridge thread->event loop per ogni
progress-hook di yt-dlp.
"""
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, Request
from sse_starlette.sse import EventSourceResponse

from backend.api.dependencies import get_download_repo
from backend.database.repository import DownloadRepository
from backend.queue.events import event_bus

router = APIRouter(prefix="/api", tags=["events"])

_ACTIVE = {"PENDING", "DOWNLOADING", "PROCESSING"}
_HEARTBEAT_SECONDS = 15
_FALLBACK_POLL_SECONDS = 1.0


@router.get("/events")
async def stream_events(request: Request, repo: DownloadRepository = Depends(get_download_repo)):
    queue = event_bus.subscribe()

    async def event_generator():
        last_payload = None
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    await asyncio.wait_for(queue.get(), timeout=_FALLBACK_POLL_SECONDS)
                except asyncio.TimeoutError:
                    pass

                records = await asyncio.to_thread(repo.list, None, 100)
                snapshot = [
                    {
                        "id": r.id,
                        "status": r.status,
                        "progress": r.progress,
                        "speed": r.speed,
                        "eta": r.eta,
                        "title": r.title,
                        "artist": r.artist,
                        "error": r.error,
                    }
                    for r in records
                    if r.status in _ACTIVE
                ]
                payload = json.dumps({"downloads": snapshot})
                if payload != last_payload:
                    last_payload = payload
                    yield {"event": "update", "data": payload}
        finally:
            event_bus.unsubscribe(queue)

    return EventSourceResponse(event_generator())
