from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models import (
    Cargo, UF, Candidato, Snapshot, SnapshotTotais, SnapshotCandidato,
    SnapshotMunicipio, Evento, Comparacao, PushSubscription,
)
from app.ws import broadcaster

router = APIRouter(prefix="/api")


def _url_foto(sq_candidato: str, uf: str | None) -> str:
    """URL da foto do candidato no site do TSE.

    Formato (2026): /divulga/rest/arquivo/img/{cod_eleicao}/{sq}/{uf}
    Carregada pelo navegador do usuário (IP residencial BR) — passa
    pelo Akamai. Candidatos do seed antigo caem na silhueta.
    """
    if any(sq_candidato.startswith(p) for p in ("PR2026_", "GO2026_", "SE2026_", "DF2026_", "DE2026_")):
        return "/static/silhueta.svg"
    uf_seg = uf or "BR"
    from app.config import get_settings
    cod = get_settings().eleicao_cod_divulga
    return (
        f"https://divulgacandcontas.tse.jus.br/divulga/rest/arquivo/img/"
        f"{cod}/{sq_candidato}/{uf_seg}"
    )


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
            "foto": _url_foto(c.sq_candidato, c.uf),
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
        "foto": _url_foto(c.sq_candidato, c.uf),
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
    """Retorna líder de cada município da UF, extraído do breakdown por
    município embutido no snapshot da UF (campo `abr` ou `mu` do TSE).

    Se o TSE não incluir esse breakdown no JSON, retorna {} e o mapa
    municipal fica cinza — mas ainda navegável.
    """
    from sqlalchemy import func
    # Último snapshot dessa (cargo, uf) e busca líder por município
    subq = (
        select(func.max(Snapshot.id).label("last_id"))
        .where(
            Snapshot.cod_cargo == cargo,
            Snapshot.abrangencia == uf,
            Snapshot.suspeito.is_(False),
        )
        .scalar_subquery()
    )
    q = (
        select(
            SnapshotMunicipio.cod_ibge,
            SnapshotMunicipio.sq_candidato,
            SnapshotMunicipio.votos,
            Candidato.nome_urna,
        )
        .join(Candidato, Candidato.sq_candidato == SnapshotMunicipio.sq_candidato)
        .where(
            SnapshotMunicipio.snapshot_id == subq,
            SnapshotMunicipio.posicao == 1,
        )
    )
    r = await sess.execute(q)
    municipios: dict[str, dict[str, Any]] = {}
    sq_para_idx: dict[str, int] = {}
    for row in r.all():
        if row.sq_candidato not in sq_para_idx:
            sq_para_idx[row.sq_candidato] = len(sq_para_idx)
        municipios[row.cod_ibge] = {
            "sq_candidato": row.sq_candidato,
            "nome_lider": row.nome_urna,
            "votos": row.votos,
            "cor_idx": sq_para_idx[row.sq_candidato],
        }
    return {"municipios": municipios}


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


@router.post("/admin/limpar-seed")
async def limpar_seed(sess: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    """Remove os candidatos fictícios do seed (prefixos PR2026_, GO2026_, etc).
    Chame depois que os reais entrarem para não misturar."""
    from sqlalchemy import delete, or_
    prefixos = ["PR2026_", "GO2026_", "SE2026_", "DF2026_", "DE2026_"]
    stmt = delete(Candidato).where(
        or_(*(Candidato.sq_candidato.like(f"{p}%") for p in prefixos))
    )
    r = await sess.execute(stmt)
    await sess.commit()
    return {"removidos": r.rowcount}


@router.post("/admin/upload-foto")
async def upload_foto(payload: dict[str, Any]) -> dict[str, Any]:
    """Recebe foto em base64 e salva em static/candidatos/{sq}.jpg.

    Body: {"sq_candidato": "250002541303", "b64": "/9j/4AAQ..."}
    Chamado pelo script Termux que baixa fotos com curl-cffi.
    """
    import base64
    import os
    sq = str(payload["sq_candidato"])
    b64 = payload["b64"]
    os.makedirs("static/candidatos", exist_ok=True)
    with open(f"static/candidatos/{sq}.jpg", "wb") as f:
        f.write(base64.b64decode(b64))
    return {"ok": True, "sq": sq}


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


@router.get("/admin/diagnostico-ids")
async def diagnostico_ids(sess: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    """Verifica se os IDs de candidatos batem entre divulga (importado) e
    resultados (snapshots). Chame depois que começar a apurar."""
    from sqlalchemy import func
    r = await sess.execute(
        select(SnapshotCandidato.sq_candidato,
               func.count(SnapshotCandidato.snapshot_id))
        .group_by(SnapshotCandidato.sq_candidato)
    )
    sqs_em_snapshots = {row[0]: row[1] for row in r.all()}
    if not sqs_em_snapshots:
        return {"status": "ainda sem snapshots"}

    r = await sess.execute(select(Candidato.sq_candidato))
    sqs_em_candidatos = {row[0] for row in r.all()}

    faltando_nome = [
        sq for sq in sqs_em_snapshots
        if sq not in sqs_em_candidatos
    ]
    return {
        "total_sqs_snapshots": len(sqs_em_snapshots),
        "total_sqs_candidatos": len(sqs_em_candidatos),
        "candidatos_sem_ficha_completa": len(faltando_nome),
        "amostra_faltando": faltando_nome[:10],
    }


@router.get("/admin/testar-tse")
async def admin_testar_tse() -> dict[str, Any]:
    """Diagnóstico: testa se o Railway consegue falar com todos os
    endpoints do TSE que a apuração usa. Cada teste diz se tá OK ou
    onde falha (Akamai 403, 404 pois eleição ainda não publicada, etc)."""
    from poller.tse_client import cliente_tse
    from app.config import get_settings
    s = get_settings()

    tests = [
        # (nome, url, o_que_esperar)
        (
            "1. Config comum (resultados.tse.jus.br)",
            f"{s.tse_cdn_base.rsplit('/', 1)[0]}/comum/config/ele-c.json",
            "Deve ser 200. Se der 403, resultados.tse.jus.br também tem Akamai (grave).",
        ),
        (
            "2. Config via Worker",
            f"{s.tse_cdn_base}/{s.eleicao_cod_1t}/config/br/br-e{s.eleicao_cod_1t:06d}-cs.json",
            "200 se 2026 publicado, 404 se ainda não.",
        ),
        (
            "3. Resultado Presidente BR",
            f"{s.tse_cdn_base}/{s.eleicao_cod_1t}/dados/br/br-c0001-e{s.eleicao_cod_1t:06d}-u.json",
            "200 se apuração começou, 404 antes de domingo 17h.",
        ),
        (
            "4. Resultado Governador SP",
            f"{s.tse_cdn_base}/{s.eleicao_cod_1t}/dados/sp/sp-c0003-e{s.eleicao_cod_1t:06d}-u.json",
            "200 se apuração começou, 404 antes.",
        ),
        (
            "5. Foto de candidato (divulga)",
            f"https://divulgacandcontas.tse.jus.br/divulga/rest/arquivo/img/{s.eleicao_cod_divulga}/250002541303/SP",
            "403 esperado (Akamai). Fotos são carregadas pelo browser do usuário, não pelo Railway.",
        ),
    ]

    resultado: dict[str, Any] = {
        "config_atual": {
            "tse_cdn_base": s.tse_cdn_base,
            "eleicao_cod_1t (resultados)": s.eleicao_cod_1t,
            "eleicao_cod_divulga (candidatos/fotos)": s.eleicao_cod_divulga,
        },
        "resumo": [],
        "detalhes": {},
    }
    async with await cliente_tse() as client:
        for nome, url, expl in tests:
            try:
                r = await client.get(url, timeout=10.0)
                status = r.status_code
                ok = status == 200
                emoji = "✅" if ok else ("🟡" if status == 404 else "❌")
                resultado["resumo"].append(f"{emoji} {nome}: {status}")
                resultado["detalhes"][nome] = {
                    "url": url,
                    "status": status,
                    "tamanho_bytes": len(r.content),
                    "explicacao": expl,
                    "preview": r.text[:200] if len(r.text) < 500 else "(muito longo)",
                }
            except Exception as e:
                resultado["resumo"].append(f"💥 {nome}: {e}")
                resultado["detalhes"][nome] = {"url": url, "erro": str(e), "explicacao": expl}
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
