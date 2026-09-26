"""Serviço de polling: baixa, persiste e dispara eventos matemáticos.

Executa em loop assíncrono; cada iteração baixa os JSONs configurados,
salva snapshots novos (dedup por hash SHA-256) e roda o motor matemático
sobre o snapshot mais recente por (cargo, abrangência).
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from dataclasses import dataclass

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import SessionLocal
from app.models import (
    Snapshot, SnapshotTotais, SnapshotCandidato, Evento,
)
from math_engine import CandidatoResumo, TotaisResumo, avaliar_apuracao
from poller.parser import parse_snapshot
from poller.tse_client import buscar_json, resultado_url

log = logging.getLogger("poller")


@dataclass(frozen=True)
class AlvoColeta:
    turno: int
    cod_cargo: int
    abrangencia: str  # 'BR' ou UF de 2 letras

    @property
    def cod_eleicao_key(self) -> str:
        return "eleicao_cod_1t" if self.turno == 1 else "eleicao_cod_2t"


_UFS = [
    "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT",
    "MS", "MG", "PA", "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO",
    "RR", "SC", "SP", "SE", "TO",
]

ALVOS_PADRAO: list[AlvoColeta] = (
    [AlvoColeta(1, 1, "BR")]                       # Presidente nacional
    + [AlvoColeta(1, 1, uf) for uf in _UFS]        # Presidente por UF (mapa)
    + [AlvoColeta(1, 3, uf) for uf in _UFS]        # Governador de cada UF
    + [AlvoColeta(1, 5, uf) for uf in _UFS]        # Senador de cada UF
)


async def _snapshot_ja_existe(sess: AsyncSession, sha: str) -> bool:
    r = await sess.execute(select(Snapshot.id).where(Snapshot.hash_conteudo == sha))
    return r.first() is not None


async def _ultimo_totalizadas(
    sess: AsyncSession, cod_cargo: int, abrangencia: str
) -> int | None:
    q = (
        select(SnapshotTotais.qt_secoes_totalizadas)
        .join(Snapshot, Snapshot.id == SnapshotTotais.snapshot_id)
        .where(Snapshot.cod_cargo == cod_cargo, Snapshot.abrangencia == abrangencia)
        .order_by(Snapshot.coletado_em.desc())
        .limit(1)
    )
    r = await sess.execute(q)
    v = r.scalar_one_or_none()
    return v


async def _eventos_existentes(
    sess: AsyncSession, cod_cargo: int, abrangencia: str
) -> set[tuple[str, str]]:
    """Retorna (tipo, sq_candidato_a) já registrados p/ evitar duplicatas."""
    q = select(Evento.tipo, Evento.sq_candidato_a).where(
        Evento.cod_cargo == cod_cargo, Evento.abrangencia == abrangencia
    )
    r = await sess.execute(q)
    return {(t, a) for t, a in r.all()}


async def processar_alvo(
    client: httpx.AsyncClient, alvo: AlvoColeta, broadcaster=None
) -> None:
    settings = get_settings()
    cod_eleicao = getattr(settings, alvo.cod_eleicao_key)
    url = resultado_url(settings.tse_cdn_base, cod_eleicao, alvo.cod_cargo, alvo.abrangencia)
    res = await buscar_json(client, url)
    if res is None:
        return
    payload, sha = res
    parsed = parse_snapshot(payload)

    async with SessionLocal() as sess:
        if await _snapshot_ja_existe(sess, sha):
            return

        suspeito = False
        ultimo = await _ultimo_totalizadas(sess, alvo.cod_cargo, alvo.abrangencia)
        if ultimo is not None and parsed.totais.qt_secoes_totalizadas < ultimo:
            log.warning(
                "snapshot suspeito %s: totalizadas retrocedeu %d -> %d",
                url, ultimo, parsed.totais.qt_secoes_totalizadas,
            )
            suspeito = True

        snap = Snapshot(
            coletado_em=datetime.now(timezone.utc),
            gerado_em_tse=parsed.totais.gerado_em,
            turno=alvo.turno,
            abrangencia=alvo.abrangencia,
            cod_cargo=alvo.cod_cargo,
            hash_conteudo=sha,
            raw=payload,
            suspeito=suspeito,
        )
        sess.add(snap)
        await sess.flush()

        sess.add(SnapshotTotais(
            snapshot_id=snap.id,
            qt_secoes_total=parsed.totais.qt_secoes_total,
            qt_secoes_totalizadas=parsed.totais.qt_secoes_totalizadas,
            qt_eleitorado_apto=parsed.totais.qt_eleitorado_apto,
            qt_eleitorado_apto_totalizadas=parsed.totais.qt_eleitorado_apto_totalizadas,
            qt_comparecimento=parsed.totais.qt_comparecimento,
            qt_abstencoes=parsed.totais.qt_abstencoes,
            qt_votos_validos=parsed.totais.qt_votos_validos,
            qt_votos_brancos=parsed.totais.qt_votos_brancos,
            qt_votos_nulos=parsed.totais.qt_votos_nulos,
        ))

        ordenados = sorted(parsed.candidatos, key=lambda c: c.votos, reverse=True)
        for pos, c in enumerate(ordenados, start=1):
            sess.add(SnapshotCandidato(
                snapshot_id=snap.id,
                sq_candidato=c.sq_candidato,
                votos=c.votos,
                pct_validos=c.pct_validos,
                posicao=pos,
            ))

        eventos_novos: list[dict] = []
        if not suspeito:
            resumos = [CandidatoResumo(c.sq_candidato, c.votos) for c in ordenados]
            tot = TotaisResumo(
                qt_secoes_total=parsed.totais.qt_secoes_total,
                qt_secoes_totalizadas=parsed.totais.qt_secoes_totalizadas,
                qt_eleitorado_apto=parsed.totais.qt_eleitorado_apto,
                qt_eleitorado_apto_totalizadas=parsed.totais.qt_eleitorado_apto_totalizadas,
                qt_votos_validos=parsed.totais.qt_votos_validos,
            )
            eventos = avaliar_apuracao(resumos, tot, cod_cargo=alvo.cod_cargo)
            ja = await _eventos_existentes(sess, alvo.cod_cargo, alvo.abrangencia)
            for ev in eventos:
                chave = (ev["tipo"], ev["sq_candidato_a"])
                if chave in ja:
                    continue
                sess.add(Evento(
                    ocorrido_em=datetime.now(timezone.utc),
                    snapshot_id=snap.id,
                    tipo=ev["tipo"],
                    cod_cargo=alvo.cod_cargo,
                    abrangencia=alvo.abrangencia,
                    sq_candidato_a=ev["sq_candidato_a"],
                    sq_candidato_b=ev.get("sq_candidato_b"),
                    detalhes=ev.get("detalhes", {}),
                ))
                eventos_novos.append(ev)

        await sess.commit()

        log.info(json.dumps({
            "alvo": f"{alvo.turno}/{alvo.cod_cargo}/{alvo.abrangencia}",
            "snapshot_id": snap.id,
            "suspeito": suspeito,
            "eventos": [e["tipo"] for e in eventos_novos],
        }))

        if broadcaster and not suspeito:
            await broadcaster.broadcast(alvo.cod_cargo, alvo.abrangencia, {
                "type": "snapshot",
                "snapshot_id": snap.id,
                "eventos": eventos_novos,
            })


async def loop(broadcaster=None, alvos: list[AlvoColeta] | None = None) -> None:
    """Loop principal. Processa alvos em paralelo (limitado por semáforo)
    para não explodir o TSE — o Brasil todo cabe em uma iteração curta.
    """
    settings = get_settings()
    alvos = alvos or ALVOS_PADRAO
    sem = asyncio.Semaphore(6)  # até 6 requisições concorrentes

    async def _um(client, alvo):
        async with sem:
            try:
                await processar_alvo(client, alvo, broadcaster)
            except Exception:
                log.exception("erro processando %s", alvo)

    async with httpx.AsyncClient() as client:
        while True:
            await asyncio.gather(*[_um(client, a) for a in alvos])
            await asyncio.sleep(settings.poll_interval_seconds)
