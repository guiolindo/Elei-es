"""Descoberta automática do código da eleição atual no TSE.

O TSE publica em `resultados.tse.jus.br/oficial/comum/config/ele-c.json`
a lista de pleitos ativos. Estrutura confirmada em 28/09/2026:

  { "c": "ele2024",     # ciclo atual
    "pl": [
      { "cd": "452",    # código do pleito
        "dt": "06/10/2024",
        "e": [
          { "cd": "619",       # código da eleição (1T)
            "cdt2": "620",     # código do 2T
            "nm": "Eleição Ordinária Municipal - 2024 - 06/10/2024 1º Turno",
            "t": "1",          # turno
            "cp": [ ... ]      # cargos
          }
        ]
      }
    ]
  }

Assim que TSE incluir "Eleição Geral 2026" nesta lista, extraímos e
cd correto automaticamente e atualizamos o config em memória.
"""
from __future__ import annotations

import logging
import re

import httpx

from app.config import get_settings
from poller.tse_client import BROWSER_HEADERS, cliente_tse

log = logging.getLogger(__name__)


async def descobrir_cod_eleicao_atual() -> tuple[int, int] | None:
    """Consulta o TSE e devolve (cd_1t, cd_2t) da Eleição Geral 2026 quando disponível.

    Retorna None se ainda não estiver publicada.
    """
    settings = get_settings()
    base = settings.tse_cdn_base.rstrip("/")
    # sobe uma pasta pra achar comum/config
    if base.endswith("/ele2026"):
        base = base.rsplit("/", 1)[0]
    url = f"{base}/comum/config/ele-c.json"
    try:
        async with await cliente_tse() as c:
            r = await c.get(url, headers=BROWSER_HEADERS, timeout=10)
        if r.status_code != 200:
            return None
        j = r.json()
        for pl in j.get("pl", []):
            dt = pl.get("dt", "")   # DD/MM/AAAA
            if not dt.endswith("/2026"):
                continue
            for e in pl.get("e", []):
                nm = (e.get("nm") or "").lower()
                turno = e.get("t")
                # Procura pleito geral do 1T de 2026 (ignora suplementares)
                if turno == "1" and re.search(r"geral.*2026|2026.*geral", nm):
                    cd_1t = int(e.get("cd"))
                    cd_2t = int(e.get("cdt2") or (cd_1t + 1))
                    log.info("descoberta: 2026 geral cd_1t=%d cd_2t=%d", cd_1t, cd_2t)
                    return cd_1t, cd_2t
        log.info("descoberta: TSE em ciclo %s — 2026 ainda não publicado",
                 j.get("c"))
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as e:
        log.warning("descoberta: falhou %s", e)
    return None
