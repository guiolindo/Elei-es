"""Serviço de polling: baixa, persiste e dispara eventos matemáticos.

Executa em loop assíncrono; cada iteração baixa os JSONs configurados,
salva snapshots novos (dedup por hash SHA-256) e roda o motor matemático
sobre o snapshot mais recente por (cargo, abrangência).
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from dataclasses import dataclass
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import SessionLocal
from app.models import (
    Snapshot, SnapshotTotais, SnapshotCandidato, SnapshotMunicipio, Evento, Candidato,
)
from math_engine import CandidatoResumo, TotaisResumo, avaliar_apuracao
from math_engine.engine import detectar_viradas
from poller.parser import parse_snapshot
from poller.tse_client import buscar_json, cliente_tse, resultado_url

log = logging.getLogger("poller")


@dataclass(frozen=True)
class AlvoColeta:
    turno: int
    cod_cargo: int
    abrangencia: str  # 'BR' ou UF de 2 letras

    @property
    def cod_eleicao_key(self) -> str:
        """Chave da setting que tem o cod_eleicao pra este alvo.

        TSE separa em 2 eleições distintas (2 códigos separados):
        - Presidente (cargo 1): eleição PRESIDENCIAL (ex.: 6257 em 2026)
        - Governador/Senador/Deputado (3, 5, 6, 7): eleição ESTADUAL
          (ex.: 6259 em 2026)

        Cada eleição tem seus próprios arquivos no S3 sob paths
        /oficial/ele2026/{cod}/dados/. Antes esse método presumia um
        cod único pra todos os cargos; corrigido agora.
        """
        if self.cod_cargo == 1:
            return "eleicao_cod_1t" if self.turno == 1 else "eleicao_cod_2t"
        # Estaduais (3, 5, 6, 7)
        return "eleicao_cod_1t_estadual" if self.turno == 1 else "eleicao_cod_2t_estadual"


_UFS = [
    "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT",
    "MS", "MG", "PA", "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO",
    "RR", "SC", "SP", "SE", "TO",
]

ALVOS_PADRAO: list[AlvoColeta] = (
    # ---- 1º turno ----
    [AlvoColeta(1, 1, "BR")]                       # Presidente nacional
    + [AlvoColeta(1, 1, "ZZ")]                     # Presidente — voto do exterior (LC 44/82)
    + [AlvoColeta(1, 1, uf) for uf in _UFS]        # Presidente por UF (mapa)
    + [AlvoColeta(1, 3, uf) for uf in _UFS]        # Governador de cada UF
    + [AlvoColeta(1, 5, uf) for uf in _UFS]        # Senador de cada UF
    + [AlvoColeta(1, 6, uf) for uf in _UFS]        # Deputado Federal
    + [AlvoColeta(1, 7, uf) for uf in _UFS]        # Deputado Estadual
    # ---- 2º turno ----
    # Enquanto o TSE não abrir o 2T, os requests retornam 404 e o poller
    # pula silenciosamente. Quando abrir, começa a coletar sozinho — sem
    # precisar de deploy nem mudança de config. Deputado não tem 2T.
    + [AlvoColeta(2, 1, "BR")]                     # Presidente 2T nacional
    + [AlvoColeta(2, 1, "ZZ")]                     # Presidente 2T exterior
    + [AlvoColeta(2, 1, uf) for uf in _UFS]        # Presidente 2T por UF
    + [AlvoColeta(2, 3, uf) for uf in _UFS]        # Governador 2T de cada UF
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


# Contadores do ciclo em curso — zerados no `loop()` antes de cada
# gather e logados no fim. Dict em escopo de módulo pra evitar ter
# que passar objeto por parâmetro em processar_alvo (chamado em paralelo).
_stats_ciclo: dict[str, int] = {"novos": 0, "dedup": 0, "falhas": 0,
                                 "retrocesso": 0, "nao_publicado": 0}
# Observabilidade: info exposta via /api/poller-status pro user confirmar
# que o loop está vivo e no intervalo esperado.
_poller_info: dict[str, Any] = {
    "ciclo_atual": 0,
    "iniciado_em": None,       # datetime UTC
    "ultimo_ciclo_em": None,   # datetime UTC do fim do último ciclo
    "ultimo_ciclo_duracao_s": None,
    "intervalo_s": None,
    "alvos_total": 0,
    "ultimo": {"novos": 0, "dedup": 0, "falhas": 0,
                "retrocesso": 0, "nao_publicado": 0},
}


def poller_status() -> dict:
    """Snapshot do estado do loop pra expor via API. Thread-safe o suficiente
    pra GET — leitura de dict em Python é atômica."""
    info = dict(_poller_info)
    agora = datetime.now(timezone.utc)
    info["agora_utc"] = agora.isoformat()
    if info["iniciado_em"]:
        info["uptime_s"] = (agora - info["iniciado_em"]).total_seconds()
        info["iniciado_em"] = info["iniciado_em"].isoformat()
    if info["ultimo_ciclo_em"]:
        info["segundos_desde_ultimo_ciclo"] = (agora - info["ultimo_ciclo_em"]).total_seconds()
        info["ultimo_ciclo_em"] = info["ultimo_ciclo_em"].isoformat()
    return info


async def processar_alvo(
    client: httpx.AsyncClient, alvo: AlvoColeta, broadcaster=None
) -> None:
    settings = get_settings()
    cod_eleicao = getattr(settings, alvo.cod_eleicao_key)
    url = resultado_url(settings.tse_cdn_base, cod_eleicao, alvo.cod_cargo, alvo.abrangencia)
    res = await buscar_json(client, url)
    if res is None:
        _stats_ciclo["falhas"] += 1
        return
    if isinstance(res, str):  # NAO_PUBLICADO (404 esperado)
        _stats_ciclo["nao_publicado"] += 1
        return
    payload, sha = res
    parsed = parse_snapshot(payload)

    async with SessionLocal() as sess:
        if await _snapshot_ja_existe(sess, sha):
            _stats_ciclo["dedup"] += 1
            return
        _stats_ciclo["novos"] += 1

        suspeito = False
        ultimo = await _ultimo_totalizadas(sess, alvo.cod_cargo, alvo.abrangencia)
        if ultimo is not None and parsed.totais.qt_secoes_totalizadas < ultimo:
            log.warning(
                "snapshot suspeito %s: totalizadas retrocedeu %d -> %d",
                url, ultimo, parsed.totais.qt_secoes_totalizadas,
            )
            suspeito = True
            _stats_ciclo["retrocesso"] += 1

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
        # Garante que todos os candidatos do snapshot existem na tabela
        # candidatos — evita quebrar FK caso o sq_candidato de resultados
        # não bata com o id vindo da divulga. Cria stubs quando falta.
        sqs_snapshot = {c.sq_candidato for c in ordenados}
        if sqs_snapshot:
            existentes = await sess.execute(
                select(Candidato.sq_candidato).where(
                    Candidato.sq_candidato.in_(sqs_snapshot)
                )
            )
            faltando = sqs_snapshot - {row[0] for row in existentes.all()}
            if faltando:
                # Deriva partido pelo número do candidato (fallback — melhor
                # que partido_numero=0 que quebra FK). Padrão TSE:
                #   cargo 1/3 (president/gov): 2 dígitos = partido
                #   cargo 5/6/7: 2 primeiros dígitos = partido
                def _derivar_partido(numero: int, cargo: int) -> int:
                    if not numero:
                        return 0
                    s = str(numero)
                    if cargo in (1, 3):
                        return int(s[:2]) if len(s) >= 2 else int(s)
                    return int(s[:2]) if len(s) >= 2 else 0

                # Garante que todos os partidos derivados existem (upsert
                # idempotente de "N/D" quando o número não bate com nenhum
                # partido real). Evita FK violation.
                from sqlalchemy.dialects.postgresql import insert as pg_insert
                from app.models import Partido as _P
                partidos_necessarios: set[int] = {0}
                for c in ordenados:
                    if c.sq_candidato in faltando:
                        partidos_necessarios.add(_derivar_partido(c.numero, alvo.cod_cargo))
                existentes_part = {
                    n for (n,) in (await sess.execute(
                        select(_P.numero).where(_P.numero.in_(partidos_necessarios))
                    )).all()
                }
                for n in partidos_necessarios - existentes_part:
                    stmt = pg_insert(_P).values(
                        numero=n, sigla=f"P{n}" if n else "N/D",
                        nome="Partido não identificado" if not n else f"P{n}",
                    )
                    stmt = stmt.on_conflict_do_nothing(index_elements=["numero"])
                    await sess.execute(stmt)
                for c in ordenados:
                    if c.sq_candidato not in faltando:
                        continue
                    sess.add(Candidato(
                        sq_candidato=c.sq_candidato,
                        nome=c.nome_urna or f"Cand {c.numero}",
                        nome_urna=c.nome_urna or f"Cand {c.numero}",
                        numero=c.numero,
                        cod_cargo=alvo.cod_cargo,
                        uf=None if alvo.abrangencia == "BR" else alvo.abrangencia,
                        partido_numero=_derivar_partido(c.numero, alvo.cod_cargo),
                    ))
                await sess.flush()
                log.info("stub criado para %d candidatos que faltavam", len(faltando))

        # Dedup por sq_candidato — se o TSE reenvia o mesmo candidato
        # duas vezes no JSON (raro mas já ocorreu por bug de agregação),
        # o insert falharia por PK (snapshot_id, sq_candidato). Mantém
        # o primeiro (que veio primeiro na ordenação por votos).
        sqs_vistos: set[str] = set()
        for pos, c in enumerate(ordenados, start=1):
            if c.sq_candidato in sqs_vistos:
                log.warning("candidato %s duplicado no snapshot %s, ignorando",
                            c.sq_candidato, snap.id)
                continue
            sqs_vistos.add(c.sq_candidato)
            sess.add(SnapshotCandidato(
                snapshot_id=snap.id,
                sq_candidato=c.sq_candidato,
                votos=c.votos,
                pct_validos=c.pct_validos,
                posicao=pos,
            ))

        # Se o JSON traz breakdown por município, persiste também
        # (sem coleta adicional — extraído do mesmo snapshot).
        for mun in parsed.municipios:
            ordenados_mun = sorted(mun.candidatos, key=lambda c: c.votos, reverse=True)
            # Garante que os candidatos existem (podem vir novos aqui)
            sqs_novos = {c.sq_candidato for c in ordenados_mun} - sqs_snapshot
            if sqs_novos:
                existentes_mun = await sess.execute(
                    select(Candidato.sq_candidato).where(
                        Candidato.sq_candidato.in_(sqs_novos)
                    )
                )
                faltando_mun = sqs_novos - {row[0] for row in existentes_mun.all()}
                for c in ordenados_mun:
                    if c.sq_candidato not in faltando_mun:
                        continue
                    sess.add(Candidato(
                        sq_candidato=c.sq_candidato,
                        nome=c.nome_urna or f"Cand {c.numero}",
                        nome_urna=c.nome_urna or f"Cand {c.numero}",
                        numero=c.numero,
                        cod_cargo=alvo.cod_cargo,
                        uf=None if alvo.abrangencia == "BR" else alvo.abrangencia,
                        partido_numero=0,
                    ))
                if faltando_mun:
                    await sess.flush()

            for pos, c in enumerate(ordenados_mun, start=1):
                sess.add(SnapshotMunicipio(
                    snapshot_id=snap.id,
                    cod_ibge=mun.cod_ibge,
                    sq_candidato=c.sq_candidato,
                    votos=c.votos,
                    pct_validos=c.pct_validos,
                    posicao=pos,
                ))

        eventos_novos: list[dict] = []
        if not suspeito:
            # Busca metadata dos candidatos deste snapshot:
            #  - idade (pra desempate 2º turno, art. 110 CE)
            #  - situação (ativo/renunciou/cancelado/cassado — Lei 9.504
            #    art. 175 §3º exclui não-ativos do cálculo de eleito)
            idades: dict[str, int] = {}
            situacoes: dict[str, str] = {}
            if ordenados:
                from datetime import date
                sqs = [c.sq_candidato for c in ordenados]
                r_cands = await sess.execute(
                    select(Candidato.sq_candidato, Candidato.raw_divulga,
                           Candidato.situacao)
                    .where(Candidato.sq_candidato.in_(sqs))
                )
                hoje = date.today()
                for sq, raw, situ in r_cands.all():
                    situacoes[sq] = situ or "ativo"
                    if alvo.turno != 2:
                        continue
                    dn = (raw or {}).get("dataDeNascimento")
                    if not dn:
                        continue
                    try:
                        if "/" in dn:
                            d, m, y = dn.split("/")
                        else:
                            y, m, d = dn.split("-")
                        nasc = date(int(y), int(m), int(d))
                        idade = hoje.year - nasc.year - (
                            (hoje.month, hoje.day) < (nasc.month, nasc.day))
                        idades[sq] = idade
                    except (ValueError, AttributeError):
                        continue
            resumos = [CandidatoResumo(c.sq_candidato, c.votos,
                                        idade_anos=idades.get(c.sq_candidato),
                                        situacao=situacoes.get(c.sq_candidato, "ativo"))
                       for c in ordenados]
            tot = TotaisResumo(
                qt_secoes_total=parsed.totais.qt_secoes_total,
                qt_secoes_totalizadas=parsed.totais.qt_secoes_totalizadas,
                qt_eleitorado_apto=parsed.totais.qt_eleitorado_apto,
                qt_eleitorado_apto_totalizadas=parsed.totais.qt_eleitorado_apto_totalizadas,
                qt_votos_validos=parsed.totais.qt_votos_validos,
            )
            eventos = avaliar_apuracao(resumos, tot, cod_cargo=alvo.cod_cargo, turno=alvo.turno)

            # Detecta viradas comparando com o snapshot anterior.
            # Bug antigo: `.limit(50)` no join pegava linhas de MÚLTIPLOS
            # snapshots misturados (50 rows / ~12 cands ≈ 4 snapshots
            # empilhados). Detector recebia timeline embaralhada.
            # Correto: pegar ID do último snapshot não-suspeito, DEPOIS
            # buscar TODOS os candidatos desse snapshot único.
            q_id_anterior = (
                select(Snapshot.id)
                .where(
                    Snapshot.cod_cargo == alvo.cod_cargo,
                    Snapshot.abrangencia == alvo.abrangencia,
                    Snapshot.suspeito.is_(False),
                    Snapshot.id != snap.id,
                )
                .order_by(Snapshot.coletado_em.desc())
                .limit(1)
            )
            id_anterior = (await sess.execute(q_id_anterior)).scalar_one_or_none()
            if id_anterior is not None:
                q_cands_ant = select(
                    SnapshotCandidato.sq_candidato, SnapshotCandidato.votos,
                ).where(SnapshotCandidato.snapshot_id == id_anterior)
                r_ant = await sess.execute(q_cands_ant)
                resumos_ant = [CandidatoResumo(sq, v) for sq, v in r_ant.all()]
                if resumos_ant:
                    eventos.extend(detectar_viradas(resumos, resumos_ant))

            ja = await _eventos_existentes(sess, alvo.cod_cargo, alvo.abrangencia)
            for ev in eventos:
                # Viradas podem repetir se candidato ping-pongar → dedupe por A+B
                chave = (ev["tipo"], ev["sq_candidato_a"])
                if ev["tipo"] == "VIRADA":
                    chave = (ev["tipo"], ev["sq_candidato_a"], ev.get("sq_candidato_b"))
                    if chave in ja:
                        continue
                elif chave in ja:
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

        # Alertas via Telegram (só quando o snapshot é confiável e existem
        # eventos novos). Importado tarde pra não travar setup se módulo faltar.
        if eventos_novos and not suspeito:
            try:
                from notif.telegram_bot import enviar_notificacoes
                await enviar_notificacoes(eventos_novos, alvo.cod_cargo, alvo.abrangencia)
            except Exception:
                log.exception("notificação telegram falhou")


async def loop(broadcaster=None, alvos: list[AlvoColeta] | None = None) -> None:
    """Loop principal. Processa alvos em paralelo (limitado por semáforo)
    para não explodir o TSE — o Brasil todo cabe em uma iteração curta.
    """
    settings = get_settings()
    alvos = alvos or ALVOS_PADRAO
    sem = asyncio.Semaphore(6)  # até 6 requisições concorrentes
    _poller_info["intervalo_s"] = settings.poll_interval_seconds
    _poller_info["alvos_total"] = len(alvos)
    _poller_info["iniciado_em"] = datetime.now(timezone.utc)

    async def _um(client, alvo):
        async with sem:
            try:
                await processar_alvo(client, alvo, broadcaster)
            except Exception:
                log.exception("erro processando %s", alvo)

    ciclo = 0
    # Heartbeat sintético a cada N ciclos (confirma vida mesmo quando
    # dedup silencia tudo). Com poll_interval_seconds=20s, N=60 = 20 min.
    HEARTBEAT_A_CADA = 60
    while True:
        # Zera contadores do ciclo
        _stats_ciclo["novos"] = 0
        _stats_ciclo["dedup"] = 0
        _stats_ciclo["falhas"] = 0
        _stats_ciclo["retrocesso"] = 0
        _stats_ciclo["nao_publicado"] = 0
        # Recria o cliente a cada ciclo pra permitir troca de proxy quando um cair
        t_ini = time.perf_counter()
        async with await cliente_tse() as client:
            await asyncio.gather(*[_um(client, a) for a in alvos])
        ciclo += 1
        _poller_info["ciclo_atual"] = ciclo
        _poller_info["ultimo_ciclo_em"] = datetime.now(timezone.utc)
        _poller_info["ultimo_ciclo_duracao_s"] = round(time.perf_counter() - t_ini, 3)
        _poller_info["ultimo"] = {
            "novos": _stats_ciclo["novos"],
            "dedup": _stats_ciclo["dedup"],
            "falhas": _stats_ciclo["falhas"],
            "retrocesso": _stats_ciclo["retrocesso"],
            "nao_publicado": _stats_ciclo["nao_publicado"],
        }
        # Log por ciclo com stats agregados — só INFO quando teve
        # mudança real (snapshot novo, falha, retrocesso). Caso contrário
        # DEBUG pra não poluir no caso comum (dedup 100%).
        novos = _stats_ciclo["novos"]
        dedup = _stats_ciclo["dedup"]
        falhas = _stats_ciclo["falhas"]
        retro = _stats_ciclo["retrocesso"]
        nao_pub = _stats_ciclo["nao_publicado"]
        msg = (f"ciclo {ciclo}: {novos} novos, {dedup} dedup, "
               f"{falhas} falhas, {nao_pub} nao-pub (2T), "
               f"{retro} retrocesso ({len(alvos)} alvos)")
        if novos or falhas or retro:
            log.info(msg)
        elif ciclo % HEARTBEAT_A_CADA == 0:
            log.info("poller vivo — %s", msg)
        else:
            log.debug(msg)
        await asyncio.sleep(settings.poll_interval_seconds)
