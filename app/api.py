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
    # Presidente é nacional: candidatos têm uf=NULL. Ignora o filtro de UF.
    if uf and cargo != 1:
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


@router.get("/apuracao/lideres-por-municipio")
async def lideres_por_municipio(
    cargo: int = Query(...),
    uf: str = Query(...),
    sess: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Retorna líder por município da UF.

    Pré-requisito: o poller precisa coletar snapshots com abrangência
    a nível de município (ex.: 'SP:3550308' para São Paulo capital).
    Enquanto isso não estiver ativo, retorna {} — o mapa fica cinza mas
    ainda navegável.
    """
    # Placeholder: sem dados por município ainda. Estrutura preparada.
    return {"municipios": {}, "aviso": "coleta por município ainda não ativa"}


@router.get("/apuracao/lideres-por-uf")
async def lideres_por_uf(
    cargo: int = Query(...),
    sess: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Retorna, para cada UF onde há snapshot desse cargo, quem está em 1º.

    Usado pelo mapa do frontend: colore cada UF pelo candidato líder.
    Para Presidente (nacional), o cargo pode não ter recorte por UF —
    nesse caso volta {} e o mapa fica todo cinza.
    """
    # Último snapshot por UF/cargo — subquery com max(coletado_em) por UF
    from sqlalchemy import func
    subq = (
        select(
            Snapshot.abrangencia.label("abr"),
            func.max(Snapshot.coletado_em).label("ts"),
        )
        .where(Snapshot.cod_cargo == cargo, Snapshot.suspeito.is_(False),
               Snapshot.abrangencia != "BR")
        .group_by(Snapshot.abrangencia)
        .subquery()
    )
    q = (
        select(
            Snapshot.abrangencia, SnapshotCandidato.sq_candidato,
            SnapshotCandidato.votos, Candidato.nome_urna,
        )
        .join(SnapshotCandidato, SnapshotCandidato.snapshot_id == Snapshot.id)
        .join(Candidato, Candidato.sq_candidato == SnapshotCandidato.sq_candidato)
        .join(subq, and_(subq.c.abr == Snapshot.abrangencia,
                         subq.c.ts == Snapshot.coletado_em))
        .where(Snapshot.cod_cargo == cargo, SnapshotCandidato.posicao == 1)
    )
    r = await sess.execute(q)
    # Atribui uma cor a cada candidato distinto (cor_idx estável)
    ufs: dict[str, dict[str, Any]] = {}
    sq_para_idx: dict[str, int] = {}
    for row in r.all():
        if row.sq_candidato not in sq_para_idx:
            sq_para_idx[row.sq_candidato] = len(sq_para_idx)
        ufs[row.abrangencia] = {
            "sq_candidato": row.sq_candidato,
            "nome_lider": row.nome_urna,
            "votos": row.votos,
            "cor_idx": sq_para_idx[row.sq_candidato],
        }
    return {"ufs": ufs}


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


@router.get("/admin/status")
async def admin_status(sess: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    """Diagnóstico rápido: quantos candidatos há por cargo/UF e último snapshot."""
    from sqlalchemy import func
    r = await sess.execute(
        select(Candidato.cod_cargo, Candidato.uf, func.count().label("n"))
        .group_by(Candidato.cod_cargo, Candidato.uf)
        .order_by(Candidato.cod_cargo, Candidato.uf)
    )
    por_cargo_uf = [{"cargo": row.cod_cargo, "uf": row.uf, "candidatos": row.n} for row in r.all()]

    r = await sess.execute(select(func.count()).select_from(Snapshot))
    total_snaps = r.scalar_one()
    r = await sess.execute(
        select(Snapshot.coletado_em).order_by(Snapshot.coletado_em.desc()).limit(1)
    )
    ultimo = r.scalar_one_or_none()
    return {
        "candidatos_por_cargo_uf": por_cargo_uf,
        "total_snapshots": total_snaps,
        "ultimo_snapshot": ultimo.isoformat() if ultimo else None,
    }


@router.post("/admin/importar-candidatos")
async def importar_candidatos(
    payload: dict[str, Any],
    sess: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Recebe JSON do TSE (que o cliente baixou direto do celular) e faz upsert.

    Body esperado:
        { "cargo": 1, "uf": "SP", "json": { ... payload bruto do TSE ... } }

    Uso via Termux (ver scripts/importar_do_celular.sh) — o celular roda o
    fetch direto no TSE (funciona porque é IP residencial BR) e faz POST
    aqui pra alimentar o banco. Substitui o sync automático quando o
    Akamai bloqueia o backend.
    """
    from poller.candidatos_tse import parse_lista, _upsert
    cargo = int(payload["cargo"])
    uf_arg = payload.get("uf")
    uf = None if uf_arg in ("BR", "", None) else uf_arg
    tse_json = payload["json"]
    cands = parse_lista(tse_json, cargo, uf)
    if not cands:
        return {"atualizados": 0, "aviso": "JSON não tinha candidatos ou schema desconhecido"}
    n = await _upsert(sess, cands)
    return {"atualizados": n, "cargo": cargo, "uf": uf_arg or "BR"}


@router.get("/admin/testar-tse")
async def admin_testar_tse() -> dict[str, Any]:
    """Diagnostica conexão com o TSE. Testa 3 endpoints e retorna o
    status de cada um. Útil para validar se o proxy configurado está
    conseguindo passar pelo Akamai."""
    from poller.tse_client import cliente_tse
    from app.config import get_settings
    s = get_settings()
    urls = [
        ("candidatos", f"{s.tse_divulga_base}/{s.eleicao_ano}/SP/{s.eleicao_cod_1t}/1/candidatos"),
        ("resultado", f"{s.tse_cdn_base}/{s.eleicao_cod_1t}/dados/br/{s.eleicao_cod_1t}-c0001-e00{s.eleicao_cod_1t}-br.json"),
        ("home", "https://divulgacandcontas.tse.jus.br/divulga/"),
    ]
    from poller.proxy_pool import get_pool
    pool_info = get_pool().diagnostico()
    resultado = {"proxy_pool": pool_info}
    async with await cliente_tse() as client:
        for nome, url in urls:
            try:
                r = await client.get(url, timeout=10.0)
                resultado[nome] = {"status": r.status_code, "url": url,
                                    "tamanho": len(r.content)}
            except Exception as e:
                resultado[nome] = {"erro": str(e), "url": url}
    return resultado


@router.post("/admin/sync-candidatos")
async def admin_sync_candidatos(
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Dispara sincronização com o TSE agora. Retorna quantos candidatos
    foram atualizados. Use para forçar quando o TSE publicar a lista
    ou pra debug sem esperar as 6h do loop automático."""
    from poller.candidatos_tse import sincronizar_candidatos
    body = payload or {}
    n = await sincronizar_candidatos(
        ufs=body.get("ufs"),
        cargos=body.get("cargos"),
        baixar_fotos=body.get("baixar_fotos", True),
    )
    return {"atualizados": n}


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
