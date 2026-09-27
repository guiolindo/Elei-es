"""Baixa e persiste a lista de candidatos do TSE.

O TSE publica a lista definitiva de candidatos (nome, urna, número,
partido, foto, coligação) semanas antes da eleição, via divulgacandcontas.
Este módulo:
  1. Consulta o endpoint por (ano, UF, cod_eleicao, cargo).
  2. Faz upsert em `candidatos` e `partidos` (idempotente — pode rodar
     todo dia até o dia D sem duplicar).
  3. Baixa a foto pra static/candidatos/{sq_candidato}.jpg (só quando
     ainda não existe).

Aceita variações de schema (o TSE muda campos entre eleições) — parser
tolerante a chaves faltantes.
"""
from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from typing import Any, Iterable

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import SessionLocal
from app.models import Candidato, Partido
from poller.tse_client import cliente_tse

log = logging.getLogger(__name__)


@dataclass
class CandidatoTSE:
    sq_candidato: str
    nome: str
    nome_urna: str
    numero: int
    partido_numero: int
    partido_sigla: str
    partido_nome: str
    uf: str | None
    cod_cargo: int
    coligacao: str | None
    vice_nome: str | None
    vice_partido: str | None
    foto_url: str | None


def _pick(d: dict, *keys, default=None):
    for k in keys:
        v = d.get(k)
        if v not in (None, "", "#NULO#"):
            return v
    return default


def _to_int(v, default=0):
    if v is None or v == "":
        return default
    try:
        return int(str(v).replace(".", "").replace(",", ""))
    except (ValueError, TypeError):
        return default


def parse_candidato(payload: dict, cod_cargo: int, uf: str | None) -> CandidatoTSE | None:
    """Aceita tanto o schema divulgacandcontas quanto os JSONs de config."""
    sq = _pick(payload, "id", "sqCandidato", "sq_candidato", "idCandidato", "sqCand")
    if not sq:
        return None
    partido = payload.get("partido") or {}
    if not partido and payload.get("sgPartido"):
        partido = {
            "numero": payload.get("numero_partido") or payload.get("nrPartido"),
            "sigla": payload.get("sgPartido"),
            "nome": payload.get("nomePartido") or "",
        }
    coligacao = _pick(payload, "nomeColigacao", "nm_coligacao", "coligacao")
    vice = payload.get("vice") or payload.get("candidatoVice") or {}
    foto_url = _pick(payload, "fotoUrl", "foto_url", "urlFoto")
    return CandidatoTSE(
        sq_candidato=str(sq),
        nome=_pick(payload, "nomeCompleto", "nomeCandidato", "nm_candidato", "nome", default=""),
        nome_urna=_pick(payload, "nomeUrna", "nomeUrnaCandidato", "nm_urna_candidato", default=""),
        numero=_to_int(_pick(payload, "numero", "numeroCandidato", "nr_candidato")),
        partido_numero=_to_int(_pick(partido, "numero", "numeroPartido", "nr_partido")),
        partido_sigla=_pick(partido, "sigla", "sg_partido", default=""),
        partido_nome=_pick(partido, "nome", "nm_partido", default=""),
        uf=uf,
        cod_cargo=cod_cargo,
        coligacao=coligacao,
        vice_nome=_pick(vice, "nomeUrna", "nome") if isinstance(vice, dict) else None,
        vice_partido=_pick(vice.get("partido", {}) if isinstance(vice, dict) else {}, "sigla"),
        foto_url=foto_url,
    )


def parse_lista(payload: dict, cod_cargo: int, uf: str | None) -> list[CandidatoTSE]:
    lista = payload.get("candidatos") or payload.get("cand") or payload.get("data") or []
    if isinstance(lista, dict):
        lista = list(lista.values())
    out = []
    for item in lista:
        if not isinstance(item, dict):
            continue
        c = parse_candidato(item, cod_cargo, uf)
        if c and c.numero:
            out.append(c)
    return out


# Headers de navegador real. O TSE bloqueia (403) requisições sem
# User-Agent de browser — é uma proteção anti-scraping padrão.
_TSE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
    "Referer": "https://divulgacandcontas.tse.jus.br/divulga/",
    "Origin": "https://divulgacandcontas.tse.jus.br",
}


async def _fetch_lista(
    client: httpx.AsyncClient, ano: int, uf: str, cod_eleicao: int, cargo: int
) -> list[dict]:
    settings = get_settings()
    url = f"{settings.tse_divulga_base}/{ano}/{uf}/{cod_eleicao}/{cargo}/candidatos"
    try:
        r = await client.get(url, timeout=20.0, headers=_TSE_HEADERS)
        if r.status_code == 404:
            return []
        r.raise_for_status()
        j = r.json()
        return parse_lista(j, cargo, None if uf == "BR" else uf)
    except (httpx.HTTPError, ValueError) as e:
        log.warning("candidatos %s cargo=%s uf=%s falhou: %s", ano, cargo, uf, e)
        return []


async def _upsert(sess: AsyncSession, candidatos: Iterable[CandidatoTSE]) -> int:
    """Insere/atualiza partidos e candidatos. Idempotente."""
    partidos_vistos: dict[int, tuple[str, str]] = {}
    cands_dict = []
    for c in candidatos:
        if c.partido_numero:
            partidos_vistos[c.partido_numero] = (c.partido_sigla, c.partido_nome)
        cands_dict.append({
            "sq_candidato": c.sq_candidato,
            "nome": c.nome or c.nome_urna,
            "nome_urna": c.nome_urna or c.nome,
            "numero": c.numero,
            "cod_cargo": c.cod_cargo,
            "uf": c.uf,
            "partido_numero": c.partido_numero or 0,
            "coligacao": c.coligacao,
            "foto_url": c.foto_url,
            "vice_nome": c.vice_nome,
            "vice_partido": c.vice_partido,
        })

    # Partidos: upsert idempotente
    for numero, (sigla, nome) in partidos_vistos.items():
        stmt = pg_insert(Partido).values(numero=numero, sigla=sigla or f"P{numero}", nome=nome or sigla or "")
        stmt = stmt.on_conflict_do_update(
            index_elements=["numero"],
            set_={"sigla": stmt.excluded.sigla, "nome": stmt.excluded.nome},
        )
        await sess.execute(stmt)

    # Candidatos: upsert
    n = 0
    for row in cands_dict:
        stmt = pg_insert(Candidato).values(**row)
        stmt = stmt.on_conflict_do_update(
            index_elements=["sq_candidato"],
            set_={k: stmt.excluded[k] for k in row if k != "sq_candidato"},
        )
        await sess.execute(stmt)
        n += 1
    await sess.commit()
    return n


async def _baixar_fotos(
    client: httpx.AsyncClient, candidatos: Iterable[CandidatoTSE], destino: str
) -> None:
    os.makedirs(destino, exist_ok=True)
    settings = get_settings()
    for c in candidatos:
        path = f"{destino}/{c.sq_candidato}.jpg"
        if os.path.exists(path):
            continue
        # Duas URLs possíveis: a que veio no JSON, ou o pattern padrão do TSE
        candidatos_urls = []
        if c.foto_url:
            candidatos_urls.append(c.foto_url)
        candidatos_urls.append(f"{settings.tse_fotos_base}/{settings.eleicao_ano}/{c.sq_candidato}")
        for url in candidatos_urls:
            try:
                r = await client.get(url, timeout=15.0, headers=_TSE_HEADERS)
                if r.status_code == 200 and r.content:
                    with open(path, "wb") as f:
                        f.write(r.content)
                    break
            except httpx.HTTPError:
                continue


async def sincronizar_candidatos(
    ufs: list[str] | None = None,
    cargos: list[int] | None = None,
    baixar_fotos: bool = True,
) -> int:
    """Sincroniza a lista oficial de candidatos com o banco.

    Chame no cron (uma vez por dia até o dia D) ou manualmente:
      python -m poller.candidatos_tse
    """
    settings = get_settings()
    ufs = ufs or ["BR", "AC", "AL", "AM", "AP", "BA", "CE", "DF", "ES", "GO",
                  "MA", "MG", "MS", "MT", "PA", "PB", "PE", "PI", "PR", "RJ",
                  "RN", "RO", "RR", "RS", "SC", "SE", "SP", "TO"]
    cargos = cargos or [1, 3, 5, 6, 7]
    ano = settings.eleicao_ano
    cod_eleicao = settings.eleicao_cod_1t

    total = 0
    async with await cliente_tse() as client:
        for cargo in cargos:
            # Presidente é só uf=BR
            ufs_cargo = ["BR"] if cargo == 1 else [u for u in ufs if u != "BR"]
            for uf in ufs_cargo:
                cands = await _fetch_lista(client, ano, uf, cod_eleicao, cargo)
                if not cands:
                    continue
                async with SessionLocal() as sess:
                    n = await _upsert(sess, cands)
                total += n
                log.info("sincronizados %d candidatos cargo=%s uf=%s", n, cargo, uf)
                if baixar_fotos:
                    await _baixar_fotos(client, cands, "static/candidatos")
    return total


def main():
    import argparse
    logging.basicConfig(level=logging.INFO)
    p = argparse.ArgumentParser()
    p.add_argument("--sem-fotos", action="store_true")
    p.add_argument("--uf", action="append", help="restringe a esta UF (pode repetir)")
    p.add_argument("--cargo", type=int, action="append", help="restringe a este cargo")
    args = p.parse_args()
    total = asyncio.run(sincronizar_candidatos(
        ufs=args.uf, cargos=args.cargo, baixar_fotos=not args.sem_fotos,
    ))
    print(f"total: {total} candidatos sincronizados")


if __name__ == "__main__":
    main()
