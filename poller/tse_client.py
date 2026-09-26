"""Cliente HTTP para os JSONs públicos do TSE.

URL típica: {base}/{turno}/{abrangencia}/{cod_eleicao}-c000{cod_cargo}-e000{cod_eleicao}-{abr}.json
Mantemos o formato configurável — o TSE muda o esquema entre eleições.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
from typing import Any

import httpx

log = logging.getLogger(__name__)


def resultado_url(base: str, cod_eleicao: int, cod_cargo: int, abrangencia: str) -> str:
    abr = abrangencia.lower()
    return (
        f"{base.rstrip('/')}/{cod_eleicao}/dados/{abr}/"
        f"{cod_eleicao}-c{cod_cargo:04d}-e{cod_eleicao:06d}-{abr}.json"
    )


async def buscar_json(
    client: httpx.AsyncClient,
    url: str,
    *,
    max_retries: int = 4,
) -> tuple[dict[str, Any], str] | None:
    """Baixa JSON com backoff exponencial. Retorna (payload, sha256) ou None."""
    delay = 1.0
    for tentativa in range(1, max_retries + 1):
        try:
            r = await client.get(url, timeout=15.0)
            if r.status_code == 404:
                log.warning("json não encontrado (404): %s", url)
                return None
            r.raise_for_status()
            content = r.content
            payload = r.json()
            sha = hashlib.sha256(content).hexdigest()
            return payload, sha
        except (httpx.HTTPError, ValueError) as exc:
            log.warning(
                "falha ao baixar %s (tentativa %d/%d): %s",
                url, tentativa, max_retries, exc,
            )
            if tentativa == max_retries:
                return None
            await asyncio.sleep(delay)
            delay *= 2
    return None
