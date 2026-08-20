"""
Piccolo event bus in-process per il progress SSE.

Non e' una coda di messaggi persistente: serve solo a svegliare rapidamente
gli endpoint SSE quando un job cambia stato, cosi' l'endpoint puo' evitare
un polling troppo aggressivo del DB. Il DB resta comunque la fonte di
verita' (un client che si connette in ritardo legge comunque lo stato
corrente da li').
"""
from __future__ import annotations

import asyncio


class JobEventBus:
    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue] = set()

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=100)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subscribers.discard(q)

    def publish(self, download_id: int) -> None:
        for q in list(self._subscribers):
            try:
                q.put_nowait(download_id)
            except asyncio.QueueFull:
                pass


event_bus = JobEventBus()
