"""Descoberta automática do código da eleição atual no TSE.

O TSE publica em `resultados.tse.jus.br/oficial/comum/config/ele-c.json`
qual é o ciclo/código de eleição corrente. Enquanto for 2024, mantemos
o valor hardcoded do simulado (21270). Assim que virar 2026, atualizamos.
"""
from __future__ import annotations

import logging

import httpx

from app.config import get_settings
from poller.tse_client import BROWSER_HEADERS, cliente_tse

log = logging.getLogger(__name__)


async def descobrir_cod_eleicao_atual() -> int | None:
    """Consulta o TSE e devolve o código do ciclo/eleição atual, se for 2026."""
    settings = get_settings()
    base = settings.tse_cdn_base.rstrip("/")
    # Se a base termina em /ele2026, sobe uma pasta pra achar comum/config
    if base.endswith("/ele2026"):
        base = base.rsplit("/", 1)[0]
    url = f"{base}/comum/config/ele-c.json"
    try:
        async with await cliente_tse() as c:
            r = await c.get(url, headers=BROWSER_HEADERS, timeout=10)
        if r.status_code != 200:
            return None
        j = r.json()
        ciclo = j.get("c") or ""
        if not ciclo.endswith("2026"):
            log.info("descoberta: TSE ainda em ciclo %s — usando fallback", ciclo)
            return None
        # Estrutura: pl (pleitos) -> lista -> e (eleições) -> lista -> cd
        for pl in j.get("pl", []):
            for e in pl.get("e", []):
                cd = e.get("cd")
                if cd:
                    log.info("descoberta: código 2026 encontrado = %s", cd)
                    return int(cd)
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as e:
        log.warning("descoberta: falhou %s", e)
    return None
