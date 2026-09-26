from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any

from fastapi import WebSocket


class Broadcaster:
    """Broadcaster simples in-memory por (cargo, abrangencia)."""

    def __init__(self) -> None:
        self._clients: dict[tuple[int, str], set[WebSocket]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def register(self, cod_cargo: int, abrangencia: str, ws: WebSocket) -> None:
        async with self._lock:
            self._clients[(cod_cargo, abrangencia)].add(ws)

    async def unregister(self, cod_cargo: int, abrangencia: str, ws: WebSocket) -> None:
        async with self._lock:
            self._clients[(cod_cargo, abrangencia)].discard(ws)

    async def broadcast(self, cod_cargo: int, abrangencia: str, payload: dict[str, Any]) -> None:
        async with self._lock:
            targets = list(self._clients.get((cod_cargo, abrangencia), ()))
        for ws in targets:
            try:
                await ws.send_json(payload)
            except Exception:
                await self.unregister(cod_cargo, abrangencia, ws)


broadcaster = Broadcaster()
