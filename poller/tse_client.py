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


async def cliente_tse() -> httpx.AsyncClient:
    """AsyncClient com headers de browser e proxy ativo do pool.

    Escolhe automaticamente um proxy vivo (da lista TSE_PROXY_LIST) que
    passe pelo Akamai do TSE. Se nenhum passar, tenta acesso direto.
    Sempre use como `async with await cliente_tse() as client:`.
    """
    from poller.proxy_pool import get_pool
    proxy = await get_pool().escolher()
    kwargs: dict = {"headers": BROWSER_HEADERS, "timeout": 20.0}
    if proxy:
        kwargs["proxy"] = proxy
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


def cargo_tse(cod_cargo: int, abrangencia: str) -> int:
    """Traduz nosso enum interno de cargo pro código usado pelo TSE na URL.

    Normalmente é 1-pra-1, exceto no DF: lá a Câmara Legislativa é formada
    por Deputados DISTRITAIS, não Estaduais, e o TSE publica sob c0008.
    Mantemos cod_cargo=7 no DB (motor e UI tratam Dep. Estadual/Distrital
    como mesmo enum), mas a URL do TSE precisa de c0008 pra DF.
    """
    if cod_cargo == 7 and abrangencia.upper() == "DF":
        return 8
    return cod_cargo


def resultado_url(base: str, cod_eleicao: int, cod_cargo: int, abrangencia: str) -> str:
    """URL do JSON de resultados no formato oficial TSE.

    Descoberto na documentação e simulado TSE 2026:
      {base}/{cod_eleicao}/dados/{uf}/{uf}-c{cargo:04d}-e{cod_eleicao:06d}-u.json

    Exemplos:
      Presidente BR:  ele2026/21270/dados/br/br-c0001-e021270-u.json
      Gov SP:         ele2026/21270/dados/sp/sp-c0003-e021270-u.json
      Dep Distrital DF: ele2026/.../dados/df/df-c0008-...  (ver cargo_tse)

    Note o sufixo `-u.json` (não -r ou -br) — u = "urna".
    """
    abr = abrangencia.lower()
    cargo_url = cargo_tse(cod_cargo, abrangencia)
    return (
        f"{base.rstrip('/')}/{cod_eleicao}/dados/{abr}/"
        f"{abr}-c{cargo_url:04d}-e{cod_eleicao:06d}-u.json"
    )


# Sentinel: retornado quando TSE devolve 404 (JSON ainda não publicado,
# ex.: 2º turno antes do 1º terminar). Distinto de None (erro real)
# pra que o poller não contabilize 404 como falha ruidosa.
NAO_PUBLICADO = "not_published"


async def buscar_json(
    client: httpx.AsyncClient,
    url: str,
    *,
    max_retries: int = 4,
) -> tuple[dict[str, Any], str] | str | None:
    """Baixa JSON com backoff exponencial.
    Retorna (payload, sha256) em sucesso, NAO_PUBLICADO em 404,
    None em erro real (timeout, 5xx após retries, JSON inválido).
    """
    delay = 1.0
    for tentativa in range(1, max_retries + 1):
        try:
            r = await client.get(url, timeout=15.0, headers=BROWSER_HEADERS)
            if r.status_code == 404:
                log.debug("json ainda não publicado (404): %s", url)
                return NAO_PUBLICADO
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
