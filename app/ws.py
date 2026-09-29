from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import Any

from fastapi import WebSocket

log = logging.getLogger(__name__)

# Timeout individual por envio (segundos). Se um cliente é lento, ele
# é dropado — o broadcast pros outros continua sem trava.
SEND_TIMEOUT = 3.0


class Broadcaster:
    """Broadcaster simples in-memory por (cargo, abrangencia).

    Envio em paralelo via asyncio.gather com timeout individual. Um
    cliente lento não segura os outros. Bug antigo: broadcast fazia
    `await send_json` em loop serial — em um cliente com 3G ruim, o
    broadcast pros milhares de outros travava até o timeout do TCP.
    """

    def __init__(self) -> None:
        self._clients: dict[tuple[int, str], set[WebSocket]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def register(self, cod_cargo: int, abrangencia: str, ws: WebSocket) -> None:
        async with self._lock:
            self._clients[(cod_cargo, abrangencia)].add(ws)

    async def unregister(self, cod_cargo: int, abrangencia: str, ws: WebSocket) -> None:
        async with self._lock:
            self._clients[(cod_cargo, abrangencia)].discard(ws)

    async def _send_um(self, ws: WebSocket, payload: dict) -> WebSocket | None:
        """Envia pra um cliente; retorna ws se falhou (pra dropar)."""
        try:
            await asyncio.wait_for(ws.send_json(payload), timeout=SEND_TIMEOUT)
            return None
        except (asyncio.TimeoutError, Exception):
            return ws

    async def broadcast(self, cod_cargo: int, abrangencia: str, payload: dict[str, Any]) -> None:
        async with self._lock:
            targets = list(self._clients.get((cod_cargo, abrangencia), ()))
        if not targets:
            return
        # Envio paralelo — o pior caso é SEND_TIMEOUT (não N × SEND_TIMEOUT)
        resultados = await asyncio.gather(
            *(self._send_um(ws, payload) for ws in targets),
            return_exceptions=True,
        )
        # Remove os que falharam
        falhados = [r for r in resultados if isinstance(r, WebSocket)]
        if falhados:
            async with self._lock:
                for ws in falhados:
                    self._clients[(cod_cargo, abrangencia)].discard(ws)
            log.debug("broadcast dropou %d clientes lentos", len(falhados))


broadcaster = Broadcaster()
