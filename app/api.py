from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models import (
    Cargo, UF, Candidato, Snapshot, SnapshotTotais, SnapshotCandidato,
    Evento, Comparacao, PushSubscription,
)
from app.ws import broadcaster

router = APIRouter(prefix="/api")


@router.get("/cargos")
async def listar_cargos(sess: AsyncSession = Depends(get_session)) -> list[dict[str, Any]]:
    r = await sess.execute(select(Cargo))
    return [{"cod_cargo": c.cod_cargo, "nome": c.nome, "abrangencia": c.abrangencia} for c in r.scalars()]


@router.get("/ufs")
async def listar_ufs(sess: AsyncSession = Depends(get_session)) -> list[dict[str, Any]]:
    r = await sess.execute(select(UF).order_by(UF.sigla))
    return [{"sigla": u.sigla, "nome": u.nome} for u in r.scalars()]


@router.get("/candidatos")
async def listar_candidatos(
    cargo: int = Query(...),
    uf: str | None = None,
    sess: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    stmt = select(Candidato).where(Candidato.cod_cargo == cargo)
    if uf:
        stmt = stmt.where(Candidato.uf == uf)
    r = await sess.execute(stmt.order_by(Candidato.numero))
    return [
        {
            "sq_candidato": c.sq_candidato,
            "nome": c.nome,
            "nome_urna": c.nome_urna,
            "numero": c.numero,
            "partido": c.partido_numero,
            "uf": c.uf,
            "foto": f"/static/candidatos/{c.sq_candidato}.jpg",
        }
        for c in r.scalars()
    ]


@router.get("/candidato/{sq}")
async def ficha(sq: str, sess: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    r = await sess.execute(select(Candidato).where(Candidato.sq_candidato == sq))
    c = r.scalar_one_or_none()
    if not c:
        raise HTTPException(404, "candidato não encontrado")
    return {
        "sq_candidato": c.sq_candidato,
        "nome": c.nome,
        "nome_urna": c.nome_urna,
        "numero": c.numero,
        "partido": c.partido_numero,
        "uf": c.uf,
        "coligacao": c.coligacao,
        "foto": f"/static/candidatos/{c.sq_candidato}.jpg",
    }


async def _ultimo_snapshot(sess: AsyncSession, cargo: int, abr: str) -> Snapshot | None:
    q = (
        select(Snapshot)
        .where(and_(Snapshot.cod_cargo == cargo, Snapshot.abrangencia == abr, Snapshot.suspeito.is_(False)))
        .order_by(Snapshot.coletado_em.desc())
        .limit(1)
    )
    r = await sess.execute(q)
    return r.scalar_one_or_none()


@router.get("/apuracao/atual")
async def apuracao_atual(
    cargo: int = Query(...),
    abrangencia: str = Query("BR"),
    sess: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    snap = await _ultimo_snapshot(sess, cargo, abrangencia)
    if not snap:
        return {"disponivel": False}
    tot = (await sess.execute(select(SnapshotTotais).where(SnapshotTotais.snapshot_id == snap.id))).scalar_one()
    cands = (await sess.execute(
        select(SnapshotCandidato).where(SnapshotCandidato.snapshot_id == snap.id)
        .order_by(SnapshotCandidato.posicao)
    )).scalars().all()
    return {
        "disponivel": True,
        "coletado_em": snap.coletado_em.isoformat(),
        "gerado_em_tse": snap.gerado_em_tse.isoformat() if snap.gerado_em_tse else None,
        "totais": {
            "secoes_total": tot.qt_secoes_total,
            "secoes_totalizadas": tot.qt_secoes_totalizadas,
            "pct_apurado": (tot.qt_secoes_totalizadas / tot.qt_secoes_total * 100) if tot.qt_secoes_total else 0,
            "eleitorado_apto": tot.qt_eleitorado_apto,
            "comparecimento": tot.qt_comparecimento,
            "abstencoes": tot.qt_abstencoes,
            "votos_validos": tot.qt_votos_validos,
            "votos_brancos": tot.qt_votos_brancos,
            "votos_nulos": tot.qt_votos_nulos,
        },
        "candidatos": [
            {
                "sq_candidato": c.sq_candidato,
                "votos": c.votos,
                "pct_validos": float(c.pct_validos),
                "posicao": c.posicao,
            }
            for c in cands
        ],
    }


@router.get("/apuracao/historico")
async def historico(
    cargo: int = Query(...),
    abrangencia: str = Query("BR"),
    candidatos: str = Query(..., description="lista sq_candidato separada por vírgula"),
    desde: datetime | None = None,
    sess: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    sqs = [s for s in candidatos.split(",") if s]
    stmt = (
        select(Snapshot.id, Snapshot.coletado_em, SnapshotCandidato.sq_candidato,
               SnapshotCandidato.votos, SnapshotCandidato.pct_validos,
               SnapshotTotais.qt_votos_validos, SnapshotTotais.qt_eleitorado_apto,
               SnapshotTotais.qt_eleitorado_apto_totalizadas)
        .join(SnapshotCandidato, SnapshotCandidato.snapshot_id == Snapshot.id)
        .join(SnapshotTotais, SnapshotTotais.snapshot_id == Snapshot.id)
        .where(and_(
            Snapshot.cod_cargo == cargo,
            Snapshot.abrangencia == abrangencia,
            Snapshot.suspeito.is_(False),
            SnapshotCandidato.sq_candidato.in_(sqs),
        ))
        .order_by(Snapshot.coletado_em)
    )
    if desde:
        stmt = stmt.where(Snapshot.coletado_em >= desde)
    r = await sess.execute(stmt)
    series: dict[str, list[dict[str, Any]]] = {sq: [] for sq in sqs}
    for row in r.all():
        series[row.sq_candidato].append({
            "t": row.coletado_em.isoformat(),
            "votos": row.votos,
            "pct": float(row.pct_validos),
            "validos_totais": row.qt_votos_validos,
            "restantes_max": max(0, row.qt_eleitorado_apto - row.qt_eleitorado_apto_totalizadas),
        })
    return {"series": series}


@router.get("/eventos")
async def eventos(
    cargo: int = Query(...),
    abrangencia: str = Query("BR"),
    sess: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    r = await sess.execute(
        select(Evento).where(Evento.cod_cargo == cargo, Evento.abrangencia == abrangencia)
        .order_by(Evento.ocorrido_em)
    )
    return [
        {
            "id": e.id,
            "ocorrido_em": e.ocorrido_em.isoformat(),
            "tipo": e.tipo,
            "sq_candidato_a": e.sq_candidato_a,
            "sq_candidato_b": e.sq_candidato_b,
            "snapshot_id": e.snapshot_id,
            "detalhes": e.detalhes,
        }
        for e in r.scalars()
    ]


@router.post("/comparacao")
async def salvar_comparacao(
    payload: dict[str, Any],
    sess: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    comp = Comparacao(
        criado_em=datetime.now(timezone.utc),
        session_id=payload.get("session_id", "anon"),
        cod_cargo=int(payload["cod_cargo"]),
        abrangencia=payload.get("abrangencia", "BR"),
        sq_candidato_a=payload["sq_candidato_a"],
        sq_candidato_b=payload["sq_candidato_b"],
    )
    sess.add(comp)
    await sess.commit()
    return {"id": comp.id}


@router.post("/push/subscribe")
async def push_subscribe(
    payload: dict[str, Any],
    sess: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    keys = payload.get("keys", {})
    sub = PushSubscription(
        criado_em=datetime.now(timezone.utc),
        endpoint=payload["endpoint"],
        p256dh=keys.get("p256dh", ""),
        auth=keys.get("auth", ""),
    )
    sess.add(sub)
    try:
        await sess.commit()
    except Exception:
        await sess.rollback()
    return {"ok": True}


ws_router = APIRouter()


@ws_router.websocket("/ws/apuracao")
async def ws_apuracao(ws: WebSocket, cargo: int, abrangencia: str = "BR") -> None:
    await ws.accept()
    await broadcaster.register(cargo, abrangencia, ws)
    try:
        while True:
            # mantém conexão viva; cliente não precisa mandar nada
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await broadcaster.unregister(cargo, abrangencia, ws)
