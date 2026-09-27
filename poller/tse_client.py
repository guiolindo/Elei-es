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


def cliente_tse() -> httpx.AsyncClient:
    """AsyncClient já configurado com headers de browser e proxy TSE (se houver).

    Todos os módulos que falam com o TSE devem usar este helper para
    herdar o proxy configurado em TSE_PROXY.
    """
    from app.config import get_settings
    s = get_settings()
    kwargs: dict = {"headers": BROWSER_HEADERS, "timeout": 20.0}
    if s.tse_proxy:
        kwargs["proxy"] = s.tse_proxy
    return httpx.AsyncClient(**kwargs)


# Headers de navegador. O TSE bloqueia (403) requisições sem User-Agent
# de browser real. Aplicado em todos os fetches para o TSE.
BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
    "Referer": "https://resultados.tse.jus.br/",
}


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
            r = await client.get(url, timeout=15.0, headers=BROWSER_HEADERS)
            if r.status_code == 404:
                log.debug("json ainda não publicado (404): %s", url)
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
