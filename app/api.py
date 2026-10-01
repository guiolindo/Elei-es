from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, WebSocket, WebSocketDisconnect
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models import (
    Cargo, UF, Candidato, Snapshot, SnapshotTotais, SnapshotCandidato,
    SnapshotMunicipio, Evento, Comparacao, PushSubscription,
)
from app.ws import broadcaster

router = APIRouter(prefix="/api")


def _exigir_admin(x_admin_token: str | None = Header(default=None)) -> None:
    """Protege endpoints /admin/*. Se ADMIN_TOKEN estiver setado, exige
    o header X-Admin-Token com valor idêntico. Se vazio (dev), libera."""
    from app.config import get_settings
    esperado = (get_settings().admin_token or "").strip()
    if not esperado:
        return  # sem token configurado → aberto (só em dev)
    if not x_admin_token or x_admin_token.strip() != esperado:
        raise HTTPException(status_code=401, detail="admin token inválido")


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


@router.get("/config-publica")
async def config_publica() -> dict[str, Any]:
    """Config pública (sem segredos). Expõe os códigos TSE que o
    sistema usa pra auditoria externa, o ano da eleição e, quando o
    bot do Telegram está habilitado, seu @username pra montar o link.

    NUNCA inclui token, URL de proxy com credenciais, VAPID private
    key, DB URL ou admin token.
    """
    from app.config import get_settings
    s = get_settings()
    return {
        "eleicao_ano": s.eleicao_ano,
        "codigos_tse": {
            "presidente_1t": s.eleicao_cod_1t,
            "presidente_2t": s.eleicao_cod_2t,
            "estadual_1t": s.eleicao_cod_1t_estadual,
            "estadual_2t": s.eleicao_cod_2t_estadual,
            "divulga": s.eleicao_cod_divulga,
        },
        "fontes": {
            "resultados": s.tse_cdn_base,
            "candidatos": "https://divulgacandcontas.tse.jus.br",
        },
        "telegram_bot": (s.telegram_bot_username if s.telegram_bot_token else None),
    }


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
    raw = c.raw_divulga or {}
    # Extrai campos comuns do payload divulga (tolerante — se faltar, vira None)
    def _p(*keys):
        for k in keys:
            v = raw.get(k)
            if v not in (None, "", "#NULO#"):
                return v
        return None
    partido_raw = raw.get("partido") or {}
    # O detalhe (candidatura/buscar) traz `vices` (lista); o listar traz `vice`.
    vices_raw = raw.get("vices")
    if isinstance(vices_raw, list) and vices_raw and isinstance(vices_raw[0], dict):
        vice_raw = vices_raw[0]
    else:
        vice_raw = raw.get("vice") or raw.get("candidatoVice") or {}
    vice_part = (vice_raw.get("partido") or {}) if isinstance(vice_raw, dict) else {}
    return {
        "sq_candidato": c.sq_candidato,
        "nome": c.nome,
        "nome_urna": c.nome_urna,
        "numero": c.numero,
        "partido": c.partido_numero,
        "uf": c.uf,
        "coligacao": c.coligacao,
        "foto": _url_foto(c.sq_candidato, c.uf),
        "situacao": _p("descricaoSituacao"),
        "situacao_candidatura": _p("descricaoSituacao"),
        "sexo": _p("descricaoSexo"),
        "cor_raca": _p("descricaoCorRaca"),
        "estado_civil": _p("descricaoEstadoCivil"),
        "data_nascimento": _p("dataDeNascimento"),
        "grau_instrucao": _p("grauInstrucao"),
        "ocupacao": _p("ocupacao"),
        "uf_nascimento": _p("sgUfNascimento"),
        "municipio_nascimento": _p("nomeMunicipioNascimento"),
        "gasto_campanha": raw.get("gastoCampanha"),
        "cnpj_campanha": _p("cnpjcampanha"),
        "vice_nome": (vice_raw.get("nomeUrna") or vice_raw.get("nomeCompleto")) if isinstance(vice_raw, dict) else None,
        "vice_partido_sigla": vice_part.get("sigla") if isinstance(vice_part, dict) else None,
        "partido_nome": partido_raw.get("nome") if isinstance(partido_raw, dict) else None,
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
        "snapshot_id": snap.id,
        # Hash SHA-256 do JSON bruto do TSE — permite ao usuário verificar
        # que o conteúdo mostrado bate com o publicado pelo TSE (não foi
        # alterado no meio do caminho). Exibido em /verificacao.
        "hash_conteudo": snap.hash_conteudo,
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
        # Projeção linear simples do total final por candidato: extrapola
        # os votos atuais pela % apurada. Não é preditivo (não pondera
        # perfil regional das seções faltantes) — é aritmético. Explícito
        # como "projecao_linear" pra deixar claro que é estimativa,
        # não predição do vencedor.
        "candidatos": [
            {
                "sq_candidato": c.sq_candidato,
                "votos": c.votos,
                "pct_validos": float(c.pct_validos),
                "posicao": c.posicao,
                "projecao_linear": int(c.votos / (tot.qt_secoes_totalizadas / tot.qt_secoes_total))
                    if tot.qt_secoes_total and tot.qt_secoes_totalizadas else c.votos,
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
            # Pré-apuração (0 votos) o gráfico desenha pontos "todos a 0%"
            # com data de ontem/anteontem e deixa um platô vazio até o
            # dia D. Exclui pra curva começar quando a apuração começa.
            SnapshotTotais.qt_votos_validos > 0,
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


@router.get("/apuracao/proporcional")
async def apuracao_proporcional(
    cargo: int = Query(..., description="6 = Deputado Federal, 7 = Deputado Estadual"),
    uf: str = Query(...),
    sess: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Aplica o cálculo proporcional (QE + cláusula de barreira + sobras
    D'Hondt + federações) sobre a apuração atual e retorna quem se elege.

    Só faz sentido pra cargo 6 (Dep Federal) ou 7 (Dep Estadual)."""
    from math_engine.proporcional import (
        CandidatoProporcional, calcular_eleitos_proporcional,
        VAGAS_DEP_FEDERAL, vagas_dep_estadual,
    )
    if cargo == 6:
        vagas = VAGAS_DEP_FEDERAL.get(uf.upper(), 0)
    elif cargo == 7:
        vagas = vagas_dep_estadual(uf)
    else:
        raise HTTPException(400, "cargo deve ser 6 (Dep Federal) ou 7 (Dep Estadual)")

    snap = await _ultimo_snapshot(sess, cargo, uf.upper())
    if not snap:
        return {"disponivel": False, "vagas": vagas, "motivo": "sem snapshot"}

    # Pré-apuração (0 votos) o motor marcaria todo mundo como "eleito" ou
    # "suplente" por ordem arbitrária — fariam PT eleger 45 candidatos
    # com 0 votos, PSD ter 65 "partido_sem_vaga", etc. O status seria
    # ficção. Só roda o cálculo quando há voto real.
    tot = (await sess.execute(
        select(SnapshotTotais).where(SnapshotTotais.snapshot_id == snap.id)
    )).scalar_one_or_none()
    if not tot or (tot.qt_votos_validos or 0) == 0:
        return {
            "disponivel": False,
            "vagas": vagas,
            "motivo": "apuracao nao iniciada",
            "coletado_em": snap.coletado_em.isoformat(),
        }

    cands_db = (await sess.execute(
        select(SnapshotCandidato, Candidato)
        .join(Candidato, Candidato.sq_candidato == SnapshotCandidato.sq_candidato)
        .where(SnapshotCandidato.snapshot_id == snap.id)
    )).all()
    cands_prop = [
        CandidatoProporcional(
            sq_candidato=sc.sq_candidato,
            nome_urna=cnd.nome_urna,
            numero=cnd.numero,
            partido_numero=cnd.partido_numero,
            votos=sc.votos,
        )
        for sc, cnd in cands_db
    ]
    r = calcular_eleitos_proporcional(cands_prop, vagas=vagas)
    return {
        "disponivel": True,
        "vagas": r.vagas,
        "quociente_eleitoral": r.qe,
        "barreira_10pct": r.barreira_absoluta,
        "votos_validos": r.votos_validos,
        "coletado_em": snap.coletado_em.isoformat(),
        "candidatos": [
            {
                "sq_candidato": c.sq_candidato,
                "nome_urna": c.nome_urna,
                "partido": c.partido,
                "federacao": c.federacao,
                "votos": c.votos,
                "status": c.status,      # "eleito" / "suplente" / "nao_atingiu_barreira" / "partido_sem_vaga"
                "posicao_partido": c.posicao_no_partido,
            }
            for c in r.candidatos
        ],
        "partidos": [
            {
                "partido": p.partido,
                "federacao": p.federacao,
                "votos_partido": p.votos_partido,
                "votos_unidade": p.votos_unidade,
                "vagas_qp": p.vagas_qp,
                "vagas_sobras": p.vagas_sobras,
                "total_vagas": p.total_vagas,
                "passou_qe": p.passou_qe,
                "passou_80_qe": p.passou_80_qe,
            }
            for p in r.partidos
        ],
    }


@router.get("/apuracao/municipio")
async def detalhe_municipio(
    cargo: int = Query(...),
    uf: str = Query(...),
    cod_ibge: str = Query(...),
    sess: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Retorna ranking completo dos candidatos daquele município."""
    from sqlalchemy import func
    subq = (
        select(func.max(Snapshot.id).label("last_id"))
        .where(
            Snapshot.cod_cargo == cargo,
            Snapshot.abrangencia == uf.upper(),
            Snapshot.suspeito.is_(False),
        )
        .scalar_subquery()
    )
    q = (
        select(
            SnapshotMunicipio.sq_candidato,
            SnapshotMunicipio.votos,
            SnapshotMunicipio.pct_validos,
            SnapshotMunicipio.posicao,
            Candidato.nome_urna,
            Candidato.numero,
            Candidato.partido_numero,
        )
        .join(Candidato, Candidato.sq_candidato == SnapshotMunicipio.sq_candidato)
        .where(
            SnapshotMunicipio.snapshot_id == subq,
            SnapshotMunicipio.cod_ibge == cod_ibge,
        )
        .order_by(SnapshotMunicipio.posicao)
    )
    r = await sess.execute(q)
    candidatos = [
        {
            "sq_candidato": row.sq_candidato,
            "nome_urna": row.nome_urna,
            "numero": row.numero,
            "partido": row.partido_numero,
            "votos": row.votos,
            "pct_validos": float(row.pct_validos),
            "posicao": row.posicao,
        }
        for row in r.all()
    ]
    return {"cod_ibge": cod_ibge, "candidatos": candidatos}


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


@router.get("/admin/status", dependencies=[Depends(_exigir_admin)])
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


@router.post("/admin/limpar-seed", dependencies=[Depends(_exigir_admin)])
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


@router.post("/admin/upload-foto", dependencies=[Depends(_exigir_admin)])
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


@router.post("/admin/importar-candidatos", dependencies=[Depends(_exigir_admin)])
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


@router.post("/admin/atualizar-detalhe", dependencies=[Depends(_exigir_admin)])
async def atualizar_detalhe(
    payload: dict[str, Any],
    sess: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Recebe o JSON de detalhe do candidato (endpoint candidatura/buscar do
    TSE) e mescla em `raw_divulga`. Também atualiza campos denormalizados
    (foto_url, coligacao, vice) quando o detalhe traz valores novos.

    Body: { "sq_candidato": "...", "detalhe": { ...payload da rest/v1/candidatura/buscar... } }
    """
    sq = str(payload.get("sq_candidato") or "")
    det = payload.get("detalhe") or {}
    if not sq or not isinstance(det, dict):
        return {"ok": False, "erro": "payload inválido"}
    row = await sess.get(Candidato, sq)
    if not row:
        return {"ok": False, "erro": "candidato não encontrado"}
    merged = dict(row.raw_divulga or {})
    merged.update(det)
    row.raw_divulga = merged
    # Denormaliza alguns campos úteis quando presentes
    if det.get("fotoUrl") and not row.foto_url:
        row.foto_url = det["fotoUrl"]
    if det.get("nomeColigacao") and not row.coligacao:
        row.coligacao = det["nomeColigacao"]
    vices = det.get("vices") or []
    if vices and isinstance(vices, list) and isinstance(vices[0], dict):
        v = vices[0]
        vn = v.get("nomeUrna") or v.get("nomeCompleto")
        if vn and not row.vice_nome:
            row.vice_nome = vn
        vp = (v.get("partido") or {}).get("sigla")
        if vp and not row.vice_partido:
            row.vice_partido = vp
    await sess.commit()
    return {"ok": True, "sq": sq}


@router.post("/admin/reparsear-snapshots", dependencies=[Depends(_exigir_admin)])
async def reparsear_snapshots(sess: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    """Re-parseia snapshots existentes usando o parser atual e atualiza
    snapshot_totais + snapshot_candidato.

    Necessário quando um bug do parser gravou totais/votos errados —
    o JSON bruto do TSE está salvo em `snapshots.raw`, então dá pra
    reconstruir sem re-baixar do TSE.

    Exemplo: parser antigo lia `s` como escalar (era dict) → todos os
    totais viravam 0. Fix rodou, mas os snapshots já persistidos
    continuavam com zeros. Este endpoint re-executa parse_snapshot
    sobre raw e atualiza os campos calculados.
    """
    from poller.parser import parse_snapshot
    r = await sess.execute(select(Snapshot))
    snaps = r.scalars().all()
    atualizados = 0
    for snap in snaps:
        try:
            parsed = parse_snapshot(snap.raw or {})
        except Exception:
            continue
        # Atualiza snapshot_totais
        tot = (await sess.execute(
            select(SnapshotTotais).where(SnapshotTotais.snapshot_id == snap.id)
        )).scalar_one_or_none()
        if tot:
            tot.qt_secoes_total = parsed.totais.qt_secoes_total
            tot.qt_secoes_totalizadas = parsed.totais.qt_secoes_totalizadas
            tot.qt_eleitorado_apto = parsed.totais.qt_eleitorado_apto
            tot.qt_eleitorado_apto_totalizadas = parsed.totais.qt_eleitorado_apto_totalizadas
            tot.qt_comparecimento = parsed.totais.qt_comparecimento
            tot.qt_abstencoes = parsed.totais.qt_abstencoes
            tot.qt_votos_validos = parsed.totais.qt_votos_validos
            tot.qt_votos_brancos = parsed.totais.qt_votos_brancos
            tot.qt_votos_nulos = parsed.totais.qt_votos_nulos
            atualizados += 1
    await sess.commit()
    return {"ok": True, "snapshots_reparsed": atualizados,
            "total_snapshots": len(snaps)}


@router.post("/admin/limpar-eventos-pre-apuracao", dependencies=[Depends(_exigir_admin)])
async def limpar_eventos_pre_apuracao(sess: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    """Apaga eventos (VIRADA, ELEITO, etc) emitidos em snapshots com 0
    votos válidos — fantasma do bug fixado em 01/10/2026. Idempotente."""
    from sqlalchemy import delete
    # Snapshots sem apuração: votos_validos=0
    snaps_zero = (await sess.execute(
        select(Snapshot.id)
        .join(SnapshotTotais, SnapshotTotais.snapshot_id == Snapshot.id)
        .where(SnapshotTotais.qt_votos_validos == 0)
    )).scalars().all()
    if not snaps_zero:
        return {"ok": True, "removidos": 0}
    r = await sess.execute(
        delete(Evento).where(Evento.snapshot_id.in_(snaps_zero))
    )
    await sess.commit()
    return {"ok": True, "removidos": r.rowcount or 0, "snapshots_afetados": len(snaps_zero)}


@router.post("/admin/corrigir-partidos", dependencies=[Depends(_exigir_admin)])
async def corrigir_partidos(sess: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    """Repara candidatos cujo partido_numero foi derivado errado (bug
    histórico: Senador tinha `partido_numero = numero_candidato`, mas
    o número do senador tem 3 dígitos e só os 2 primeiros são o partido).

    Aplica a regra correta pra cargos 5/6/7:
      partido_numero = int(str(numero_candidato)[:2])

    Idempotente — só toca em candidatos cujo `partido_numero` atual
    não existe na tabela `partidos`.
    """
    from sqlalchemy import update
    from app.models import Partido
    # Partidos registrados (números conhecidos)
    partidos_ok = {n for (n,) in (await sess.execute(select(Partido.numero))).all()}
    r = await sess.execute(
        select(Candidato).where(Candidato.cod_cargo.in_([5, 6, 7]))
    )
    corrigidos = 0
    for c in r.scalars():
        if c.partido_numero in partidos_ok and c.partido_numero != 0:
            continue  # já está OK
        num = str(c.numero or "")
        if len(num) < 2:
            continue
        novo = int(num[:2])
        if novo in partidos_ok and novo != c.partido_numero:
            c.partido_numero = novo
            corrigidos += 1
    await sess.commit()
    return {"ok": True, "corrigidos": corrigidos}


@router.get("/admin/diagnostico-ids", dependencies=[Depends(_exigir_admin)])
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


@router.get("/admin/testar-tse", dependencies=[Depends(_exigir_admin)])
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


@router.post("/admin/sync-candidatos", dependencies=[Depends(_exigir_admin)])
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


# ============ Municipal on-demand (mapa) ============
# Cache TTL curto em memória pra puxar município/zona só quando alguém
# abre o mapa. Não persiste no banco — some do cache em 45s.
# Se 200 pessoas olham SP ao mesmo tempo, só 1 request sai pro TSE.
_CACHE_MUN: dict[str, tuple[float, dict]] = {}
_CACHE_MUN_TTL = 45.0


async def _fetch_tse_json(url: str) -> dict | None:
    from poller.tse_client import cliente_tse, BROWSER_HEADERS
    try:
        async with await cliente_tse() as c:
            r = await c.get(url, headers=BROWSER_HEADERS, timeout=8.0)
        if r.status_code != 200:
            return None
        return r.json()
    except Exception:
        return None


@router.get("/apuracao/municipio-tse")
async def apuracao_municipio_tse(
    uf: str = Query(..., min_length=2, max_length=2),
    municipio: str = Query(..., min_length=1, max_length=6),
    cargo: int = Query(...),
    turno: int = Query(1, ge=1, le=2),
) -> dict[str, Any]:
    """Puxa apuração de um município específico direto do TSE, sem
    persistir no banco. Usado pelo mapa (drill-down "quem ganhou aqui").

    NOTA: existe `/apuracao/municipio` (sem -tse) que usa dados
    JÁ persistidos no DB (vindos dentro do snapshot UF). Este endpoint
    é complementar: busca ao vivo, útil quando o JSON agregado da UF
    não trouxe aquela cidade específica.

    Cache em memória de 45s: se muita gente clica no mesmo município,
    só 1 request sai pro TSE. Nada é gravado — some quando expira.
    """
    from app.config import get_settings
    from time import monotonic
    uf = uf.lower()
    mu = str(int(municipio))  # normaliza (strip zeros à esquerda)
    settings = get_settings()
    if cargo == 1:
        cod = settings.eleicao_cod_1t if turno == 1 else settings.eleicao_cod_2t
    else:
        cod = settings.eleicao_cod_1t_estadual if turno == 1 else settings.eleicao_cod_2t_estadual
    chave = f"{uf}:{mu}:{cargo}:{cod}"
    agora = monotonic()
    hit = _CACHE_MUN.get(chave)
    if hit and (agora - hit[0]) < _CACHE_MUN_TTL:
        return {"cache_hit": True, **hit[1]}
    base = settings.tse_cdn_base.rstrip("/").rsplit("/", 1)[0]  # sem /ele2026
    # Padrão do TSE: /{cod}/dados/{uf}/{uf}{municipio}-c{cargo:04d}-e{cod:06d}-u.json
    # onde municipio pode ter 5 dígitos (código IBGE truncado do TSE)
    mu_pad = mu.zfill(5)
    url = f"{base}/{cod}/dados/{uf}/{uf}{mu_pad}-c{cargo:04d}-e{cod:06d}-u.json"
    j = await _fetch_tse_json(url)
    if not j:
        return {"disponivel": False, "url_tentada": url}
    # Parse enxuto: só o mínimo pro mapa (líder + % apurado)
    from poller.parser import parse_snapshot
    try:
        parsed = parse_snapshot(j)
    except Exception:
        return {"disponivel": False, "erro": "parse"}
    if not parsed:
        return {"disponivel": False}
    tot = parsed.totais
    lider = parsed.candidatos[0] if parsed.candidatos else None
    body = {
        "disponivel": True,
        "uf": uf.upper(),
        "municipio": mu,
        "cargo": cargo,
        "pct_apurado": (tot.qt_secoes_totalizadas / tot.qt_secoes_total * 100)
                        if tot.qt_secoes_total else 0,
        "secoes_total": tot.qt_secoes_total,
        "secoes_totalizadas": tot.qt_secoes_totalizadas,
        "lider": {
            "sq_candidato": lider.sq_candidato,
            "votos": lider.votos,
            "pct_validos": float(lider.pct_validos),
        } if lider else None,
        "candidatos": [
            {"sq_candidato": c.sq_candidato, "votos": c.votos,
             "pct_validos": float(c.pct_validos)}
            for c in parsed.candidatos[:20]  # top 20 basta pro mapa
        ],
    }
    _CACHE_MUN[chave] = (agora, body)
    # Limpa entradas expiradas (barato: só faz se cresceu demais)
    if len(_CACHE_MUN) > 5000:
        cutoff = agora - _CACHE_MUN_TTL
        for k in [k for k, (t, _) in _CACHE_MUN.items() if t < cutoff]:
            _CACHE_MUN.pop(k, None)
    return body


@router.get("/apuracao/zona")
async def apuracao_zona(
    uf: str = Query(..., min_length=2, max_length=2),
    municipio: str = Query(..., min_length=1, max_length=6),
    zona: str = Query(..., min_length=1, max_length=5),
    cargo: int = Query(...),
    turno: int = Query(1, ge=1, le=2),
) -> dict[str, Any]:
    """Apuração de uma zona eleitoral específica. Mesmo padrão do
    endpoint de município: on-demand, cache 45s, sem persistência.

    Zona é a subdivisão dentro do município (ex.: SP tem ~500 zonas).
    Útil pra drill-down: usuário abre SP-SP no mapa → escolhe a zona
    do bairro dele → vê onde cada candidato ganhou lá.
    """
    from app.config import get_settings
    from time import monotonic
    uf = uf.lower()
    mu = str(int(municipio)).zfill(5)
    zn = str(int(zona)).zfill(4)
    settings = get_settings()
    if cargo == 1:
        cod = settings.eleicao_cod_1t if turno == 1 else settings.eleicao_cod_2t
    else:
        cod = settings.eleicao_cod_1t_estadual if turno == 1 else settings.eleicao_cod_2t_estadual
    chave = f"z:{uf}:{mu}:{zn}:{cargo}:{cod}"
    agora = monotonic()
    hit = _CACHE_MUN.get(chave)  # reusa o mesmo cache
    if hit and (agora - hit[0]) < _CACHE_MUN_TTL:
        return {"cache_hit": True, **hit[1]}
    base = settings.tse_cdn_base.rstrip("/").rsplit("/", 1)[0]
    # Padrão TSE zona: /{cod}/dados/{uf}/{uf}{mun}z{zn}-c{cargo:04d}-e{cod:06d}-u.json
    url = f"{base}/{cod}/dados/{uf}/{uf}{mu}z{zn}-c{cargo:04d}-e{cod:06d}-u.json"
    j = await _fetch_tse_json(url)
    if not j:
        return {"disponivel": False, "url_tentada": url}
    from poller.parser import parse_snapshot
    try:
        parsed = parse_snapshot(j)
    except Exception:
        return {"disponivel": False, "erro": "parse"}
    if not parsed:
        return {"disponivel": False}
    tot = parsed.totais
    lider = parsed.candidatos[0] if parsed.candidatos else None
    body = {
        "disponivel": True,
        "uf": uf.upper(),
        "municipio": mu.lstrip("0") or "0",
        "zona": zn.lstrip("0") or "0",
        "cargo": cargo,
        "pct_apurado": (tot.qt_secoes_totalizadas / tot.qt_secoes_total * 100)
                        if tot.qt_secoes_total else 0,
        "secoes_total": tot.qt_secoes_total,
        "secoes_totalizadas": tot.qt_secoes_totalizadas,
        "lider": {
            "sq_candidato": lider.sq_candidato,
            "votos": lider.votos,
            "pct_validos": float(lider.pct_validos),
        } if lider else None,
        "candidatos": [
            {"sq_candidato": c.sq_candidato, "votos": c.votos,
             "pct_validos": float(c.pct_validos)}
            for c in parsed.candidatos[:20]
        ],
    }
    _CACHE_MUN[chave] = (agora, body)
    return body


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
