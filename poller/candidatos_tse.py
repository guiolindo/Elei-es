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
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import SessionLocal
from app.models import Candidato, Partido
from poller.tse_client import cliente_tse

log = logging.getLogger(__name__)


class _BloqueadoPorAkamai(Exception):
    """Sinalização interna: divulgacandcontas bloqueou o IP (403 ou 429).
    O sync aborta cedo em vez de queimar requests que vão todas falhar."""


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
    situacao: str = "ativo"
    raw: dict | None = None


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
    """Aceita o schema divulgacandcontas 2026 (id, nomeUrna, partido.sigla)
    e os variantes de 2022 (sqCandidato, camelCase)."""
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
    # Em 2026 o partido.numero às vezes vem 0 no JSON — derivamos do
    # número do candidato conforme padrão do TSE:
    #  - Presidente (1) e Governador (3): 2 dígitos = número do partido
    #    (ex.: 13 = PT, 22 = PL, 12 = PDT)
    #  - Senador (5): 3 dígitos, os 2 primeiros = partido, 3º = sequencial
    #    (ex.: 130 e 131 são PT, 220 e 221 são PL)
    #  - Deputado Federal (6): 4 dígitos, 2 primeiros = partido
    #  - Deputado Estadual (7): 5 dígitos, 2 primeiros = partido
    # Bug histórico: senador estava sendo tratado como presidente/gov
    # (partido_num = num_cand), então virava 130/131/etc — que não
    # existe como partido → candidatos ficavam sem logo.
    partido_num = _to_int(_pick(partido, "numero", "numeroPartido", "nr_partido"))
    num_cand = _to_int(_pick(payload, "numero", "numeroCandidato", "nr_candidato"))
    if cod_cargo in (5, 6, 7) and num_cand:
        # Pra senador/deputado SEMPRE deriva pelos 2 primeiros dígitos do
        # numero. O TSE 2026 às vezes manda partido.numero=130 (igual ao
        # numero do candidato) em vez de 13 — se confiarmos no payload,
        # a FK quebra ou o logo não aparece. Os 2 primeiros dígitos do
        # numero são padrão TSE e sempre corretos.
        s = str(num_cand)
        if len(s) >= 2:
            partido_num = int(s[:2])
    elif not partido_num and num_cand and cod_cargo in (1, 3):
        # Presidente/Governador: 2 dígitos exatos = número do partido
        partido_num = num_cand
    coligacao = _pick(payload, "nomeColigacao", "nm_coligacao", "coligacao")
    vice = payload.get("vice") or payload.get("candidatoVice") or {}
    foto_url = _pick(payload, "fotoUrl", "foto_url", "urlFoto")
    # Mapeia descricaoSituacao do TSE pra enum interno. Candidatos
    # retirados/cassados são MANTIDOS no banco (vão receber votos no
    # dia D) mas marcados pra motor excluí-los do cálculo de "eleito".
    # Lei 9.504/97 art. 175 §3º: votos considerados nulos na apuração
    # oficial final.
    sit_raw = (_pick(payload, "descricaoSituacao", "descricaoTotalizacao") or "").lower()
    if "indeferido" in sit_raw and "recurso" not in sit_raw:
        situacao = "indeferido_sem_recurso"
    elif "renunc" in sit_raw:
        situacao = "renunciou"
    elif "cancel" in sit_raw:
        situacao = "cancelado"
    elif "cass" in sit_raw:
        situacao = "cassado"
    else:
        situacao = "ativo"
    return CandidatoTSE(
        sq_candidato=str(sq),
        nome=_pick(payload, "nomeCompleto", "nomeCandidato", "nm_candidato", "nome", default=""),
        nome_urna=_pick(payload, "nomeUrna", "nomeUrnaCandidato", "nm_urna_candidato", default=""),
        numero=_to_int(_pick(payload, "numero", "numeroCandidato", "nr_candidato")),
        partido_numero=partido_num,
        partido_sigla=_pick(partido, "sigla", "sg_partido", default=""),
        partido_nome=_pick(partido, "nome", "nm_partido", default=""),
        uf=uf,
        cod_cargo=cod_cargo,
        coligacao=coligacao,
        vice_nome=_pick(vice, "nomeUrna", "nome") if isinstance(vice, dict) else None,
        vice_partido=_pick(vice.get("partido", {}) if isinstance(vice, dict) else {}, "sigla"),
        foto_url=foto_url,
        situacao=situacao,
        raw=payload,
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
        if r.status_code in (403, 429):
            # Esperado quando o Railway (fora do BR) bate direto no TSE.
            # 403 = Akamai bloqueou; 429 = rate limit do mesmo gateway.
            # Candidatos são importados via Termux
            # (scripts/importar_termux.py) ou /api/admin/importar-candidatos.
            # Debug em vez de warning pra não poluir o log.
            log.debug("candidatos %s cargo=%s uf=%s: %d Akamai (esperado)",
                      ano, cargo, uf, r.status_code)
            # Sinaliza para o loop externo abortar
            raise _BloqueadoPorAkamai()
        r.raise_for_status()
        j = r.json()
        cs = parse_lista(j, cargo, None if uf == "BR" else uf)
        if cs:
            log.info("candidatos %s cargo=%s uf=%s: %d encontrados", ano, cargo, uf, len(cs))
        return cs
    except _BloqueadoPorAkamai:
        raise
    except (httpx.HTTPError, ValueError) as e:
        log.warning("candidatos %s cargo=%s uf=%s falhou: %s", ano, cargo, uf, e)
        return []


async def _upsert(sess: AsyncSession, candidatos: Iterable[CandidatoTSE]) -> int:
    """Insere/atualiza partidos e candidatos. Idempotente."""
    partidos_vistos: dict[int, tuple[str, str]] = {}
    cands_dict = []
    for c in candidatos:
        # Sempre registra o partido (sigla vem do JSON mesmo com numero derivado)
        if c.partido_numero:
            partidos_vistos[c.partido_numero] = (c.partido_sigla, c.partido_nome)
        else:
            # partido_numero=0: use um partido dummy pra não quebrar FK
            partidos_vistos.setdefault(0, ("N/D", "Não informado"))
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
            "raw_divulga": c.raw,
            "situacao": c.situacao,
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


async def _marcar_removidos_pelo_tse(
    sess: AsyncSession, uf: str | None, cod_cargo: int, sq_vistos: set[str]
) -> int:
    """Marca como 'cancelado' candidatos ativos no DB que o TSE removeu.

    Caso real: candidato indeferido tardiamente (ex.: 'Avalanche' 2026) some
    da listagem oficial do divulgacandcontas, mas segue no nosso DB porque
    foi importado antes. Sem este sweep, apareceria na UI até a próxima
    reimportação manual.

    Só roda quando sq_vistos é NÃO-vazio — se o TSE devolveu zero
    candidatos pra (uf, cargo), provavelmente é erro de rede ou bloqueio
    Akamai, não remoção legítima. Idempotente: só mexe em situacao='ativo'.
    """
    if not sq_vistos:
        return 0
    stmt = select(Candidato.sq_candidato, Candidato.nome_urna).where(
        Candidato.cod_cargo == cod_cargo,
        Candidato.situacao == "ativo",
    )
    if uf and uf != "BR":
        stmt = stmt.where(Candidato.uf == uf)
    else:
        stmt = stmt.where(Candidato.uf.is_(None) | (Candidato.uf == "BR"))
    rows = (await sess.execute(stmt)).all()
    removidos = [(sq, nome) for sq, nome in rows if sq not in sq_vistos]
    if not removidos:
        return 0
    sqs = [sq for sq, _ in removidos]
    await sess.execute(
        update(Candidato)
        .where(Candidato.sq_candidato.in_(sqs))
        .values(situacao="cancelado")
    )
    await sess.commit()
    for sq, nome in removidos:
        log.warning(
            "candidato removido pelo TSE: sq=%s nome='%s' cargo=%s uf=%s → situacao=cancelado",
            sq, nome, cod_cargo, uf or "BR",
        )
    return len(removidos)


async def corrigir_partidos_orfaos(sess: AsyncSession | None = None) -> int:
    """Self-heal do partido_numero em candidatos de cargos 5/6/7.

    Roda no startup pra corrigir dados históricos importados antes do
    fix (Senador tem 3 dígitos: os 2 primeiros são o partido; deputados
    idem com 4-5 dígitos). Idempotente e barato — só toca em linhas
    cujo partido_numero atual não existe na tabela partidos.
    """
    from app.models import Partido as _P
    close_sess = False
    if sess is None:
        sess = SessionLocal()
        close_sess = True
    try:
        partidos_ok = {n for (n,) in (await sess.execute(select(_P.numero))).all()}
        if not partidos_ok:
            return 0
        r = await sess.execute(
            select(Candidato).where(Candidato.cod_cargo.in_([5, 6, 7]))
        )
        corrigidos = 0
        for c in r.scalars():
            num = str(c.numero or "")
            if len(num) < 2:
                continue
            esperado = int(num[:2])
            # Se já bate com os 2 primeiros dígitos, OK
            if c.partido_numero == esperado:
                continue
            # Sempre que o partido_numero atual NÃO bate com os 2 primeiros
            # dígitos do numero (padrão TSE pra cargos 5/6/7), tenta corrigir.
            # Isso cobre:
            #   - 130 (TSE mandou errado) → 13
            #   - 0 (stub FK dummy) → derivado
            #   - partido real mas desatualizado (ex.: 25 era União → virou PRD,
            #     mas o numero segue com [:2]=25, então 25 continua certo
            #     — a sigla/nome é que mudou, e isso é job do seed/upsert)
            if esperado in partidos_ok:
                c.partido_numero = esperado
                corrigidos += 1
        if corrigidos:
            await sess.commit()
        return corrigidos
    finally:
        if close_sess:
            await sess.close()


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
    # Candidatos usam o cod_divulga (que é diferente do cod_resultados)
    cod_eleicao = settings.eleicao_cod_divulga

    total = 0
    bloqueado = False
    async with await cliente_tse() as client:
        for cargo in cargos:
            if bloqueado:
                break
            # Presidente é só uf=BR
            ufs_cargo = ["BR"] if cargo == 1 else [u for u in ufs if u != "BR"]
            for uf in ufs_cargo:
                try:
                    cands = await _fetch_lista(client, ano, uf, cod_eleicao, cargo)
                except _BloqueadoPorAkamai:
                    log.info(
                        "sync_candidatos: divulgacandcontas bloqueou (Akamai). "
                        "Abortando ciclo. Use scripts/importar_termux.py do celular "
                        "ou POST /api/admin/importar-candidatos."
                    )
                    bloqueado = True
                    break
                if not cands:
                    continue
                async with SessionLocal() as sess:
                    n = await _upsert(sess, cands)
                    sq_vistos = {c.sq_candidato for c in cands}
                    removidos = await _marcar_removidos_pelo_tse(sess, uf, cargo, sq_vistos)
                total += n
                log.info(
                    "sincronizados %d candidatos cargo=%s uf=%s (removidos=%d)",
                    n, cargo, uf, removidos,
                )
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
