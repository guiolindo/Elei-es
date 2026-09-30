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


async def descobrir_cods_eleicao() -> dict[str, int]:
    """Descobre os 4 códigos de eleição do TSE 2026.

    TSE 2026 tem DUAS eleições distintas (confirmado 30/09/2026):
      - Presidencial (cargo 1)              → cod_1t / cod_2t
      - Estadual (cargos 3, 5, 6, 7)         → cod_1t_estadual / cod_2t_estadual

    Cada uma tem sua entrada em `comum/config/ele-c.json` com nome
    tipo "Eleição Geral - Presidente - 2026 - 1º Turno" ou similar.

    Retorna dict com as chaves encontradas (podem faltar algumas se
    TSE ainda não publicou). Ex.:
      {"eleicao_cod_1t": 6257, "eleicao_cod_1t_estadual": 6259}
    """
    settings = get_settings()
    base = settings.tse_cdn_base.rstrip("/")
    if base.endswith("/ele2026"):
        base = base.rsplit("/", 1)[0]
    url = f"{base}/comum/config/ele-c.json"
    achados: dict[str, int] = {}
    try:
        async with await cliente_tse() as c:
            r = await c.get(url, headers=BROWSER_HEADERS, timeout=10)
        if r.status_code != 200:
            return achados
        j = r.json()
        for pl in j.get("pl", []):
            dt = pl.get("dt", "")
            if not dt.endswith("/2026"):
                continue
            for e in pl.get("e", []):
                nm = (e.get("nm") or "").lower()
                turno = str(e.get("t") or "")
                if not re.search(r"2026", nm):
                    continue
                cd = e.get("cd")
                cdt2 = e.get("cdt2")
                if not cd:
                    continue
                cd = int(cd)
                cd2 = int(cdt2) if cdt2 else cd + 1
                # Presidente aparece em pleitos com "president" no nome
                # ou pertence à eleição federal.
                if "president" in nm or "federal" in nm:
                    if turno == "1":
                        achados["eleicao_cod_1t"] = cd
                        achados["eleicao_cod_2t"] = cd2
                elif "estadual" in nm or "governador" in nm or "senador" in nm:
                    if turno == "1":
                        achados["eleicao_cod_1t_estadual"] = cd
                        achados["eleicao_cod_2t_estadual"] = cd2
                elif "geral" in nm and turno == "1":
                    # Fallback: pleito geral sem descriminar — assume federal
                    achados.setdefault("eleicao_cod_1t", cd)
                    achados.setdefault("eleicao_cod_2t", cd2)
        if achados:
            log.info("descoberta: %s", achados)
        else:
            log.info("descoberta: 2026 ainda não publicado (ciclo=%s)", j.get("c"))
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as ex:
        log.warning("descoberta: falhou %s", ex)
    return achados


async def descobrir_cod_eleicao_atual() -> tuple[int, int] | None:
    """Wrapper legado — retorna só o par (cd_1t, cd_2t) da presidencial.
    Mantido pra compat com _descobrir_cod_loop antigo."""
    d = await descobrir_cods_eleicao()
    if "eleicao_cod_1t" in d:
        return d["eleicao_cod_1t"], d.get("eleicao_cod_2t", d["eleicao_cod_1t"] + 1)
    return None
