"""A tiny async pub/sub so the browser can watch the agents think in real time.

The demo lives or dies on this: judges need to see reasoning happen, not a
spinner followed by a result.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any


class EventBus:
    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue] = set()
        self._history: list[dict] = []
        self._lock = asyncio.Lock()

    async def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=1000)
        async with self._lock:
            self._subscribers.add(q)
            # Replay history so a late-joining tab is not staring at nothing.
            # Tag the replay: some events are prompts for the human ("may I take
            # this class?") and replaying one that has already been answered would
            # put a dead modal back on screen. The browser decides what to re-show.
            for ev in self._history[-300:]:
                q.put_nowait({**ev, "replay": True})
        return q

    async def unsubscribe(self, q: asyncio.Queue) -> None:
        async with self._lock:
            self._subscribers.discard(q)

    async def publish(self, kind: str, payload: dict[str, Any]) -> None:
        event = {"kind": kind, **payload}
        self._history.append(event)
        if len(self._history) > 2000:
            del self._history[:500]
        async with self._lock:
            dead = []
            for q in self._subscribers:
                try:
                    q.put_nowait(event)
                except asyncio.QueueFull:
                    dead.append(q)
            for q in dead:
                self._subscribers.discard(q)

    def clear_history(self) -> None:
        self._history.clear()

    @staticmethod
    def sse(event: dict) -> str:
        return f"data: {json.dumps(event)}\n\n"


BUS = EventBus()
