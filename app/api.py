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


@router.get("/poller-status")
async def api_poller_status() -> dict[str, Any]:
    """Observabilidade do loop do poller. Público — sem dados sensíveis.

    Chame repetidamente pra ver o `ciclo_atual` subir e o
    `segundos_desde_ultimo_ciclo` oscilar entre 0 e `intervalo_s`.
    Se `segundos_desde_ultimo_ciclo` passar muito do intervalo, algo
    travou (ex.: TSE devolvendo 503 em massa).
    """
    from poller.service import poller_status
    return poller_status()


@router.get("/cargos")
async def listar_cargos(sess: AsyncSession = Depends(get_session)) -> list[dict[str, Any]]:
    r = await sess.execute(select(Cargo))
    return [{"cod_cargo": c.cod_cargo, "nome": c.nome, "abrangencia": c.abrangencia} for c in r.scalars()]


@router.get("/ufs")
async def listar_ufs(sess: AsyncSession = Depends(get_session)) -> list[dict[str, Any]]:
    r = await sess.execute(select(UF).order_by(UF.sigla))
    return [{"sigla": u.sigla, "nome": u.nome} for u in r.scalars()]


@router.get("/segundo-turno/ufs-governador")
async def ufs_governador_segundo_turno(
    sess: AsyncSession = Depends(get_session),
) -> list[str]:
    """UFs que terão 2º turno de Governador (CF art. 77 §2º: só com <50%+1
    dos válidos no 1T). O frontend usa pra esconder do dropdown de UF, no
    modo 2T + cargo Governador, as UFs que já foram decididas no 1T."""
    r = await sess.execute(
        select(Evento.abrangencia).where(
            and_(Evento.cod_cargo == 3, Evento.tipo == "SEGUNDO_TURNO_DEFINIDO")
        ).distinct()
    )
    return sorted({row for row in r.scalars() if row})


@router.get("/candidatos")
async def listar_candidatos(
    cargo: int = Query(...),
    uf: str | None = None,
    turno: int | None = Query(None, ge=1, le=2, description=
        "Se 2, retorna apenas os candidatos que foram ao 2º turno "
        "(pros cargos 1 Pres e 3 Gov). Derivado dos eventos "
        "SEGUNDO_TURNO_DEFINIDO (sq_a e sq_b). Senador/Deputado nunca "
        "têm 2T, então turno=2 retorna []. Omitido = todos."),
    sess: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    stmt = select(Candidato).where(Candidato.cod_cargo == cargo)
    # Presidente é nacional: candidatos têm uf=NULL. Ignora o filtro de UF.
    if uf and cargo != 1:
        stmt = stmt.where(Candidato.uf == uf)
    # Filtro por turno: pros cargos 1/3 que têm 2T, pega sq_candidatos
    # dos eventos SEGUNDO_TURNO_DEFINIDO. Senador(5), Dep Fed(6), Dep Est(7)
    # nunca têm 2T → turno=2 retorna lista vazia.
    if turno == 2:
        if cargo not in (1, 3):
            return []
        abr = "BR" if cargo == 1 else (uf.upper() if uf else None)
        if abr:
            where_ev = [Evento.cod_cargo == cargo,
                        Evento.abrangencia == abr,
                        Evento.tipo == "SEGUNDO_TURNO_DEFINIDO"]
            r_ev = (await sess.execute(select(Evento).where(and_(*where_ev)))).scalars().all()
            sqs_2t: set[str] = set()
            for e in r_ev:
                if e.sq_candidato_a: sqs_2t.add(e.sq_candidato_a)
                if e.sq_candidato_b: sqs_2t.add(e.sq_candidato_b)
            if not sqs_2t:
                return []
            stmt = stmt.where(Candidato.sq_candidato.in_(sqs_2t))
    r = await sess.execute(stmt.order_by(Candidato.numero))
    todos = list(r.scalars())
    # Dedup HONESTO por (uf, numero). O TSE às vezes mantém dois registros
    # pro mesmo número. Quatro casos:
    #
    #   a) 1 ativo + N inativos  → mostra só o ativo. Substituição com
    #                               baixa do antigo.
    #   b) 0 ativos               → mostra TODOS. Ex.: PRTB-28 em 2026 teve
    #                               Avalanche (renunciou) e Marçal
    #                               (indeferido) — pessoas distintas, não
    #                               cabe esconder nenhum.
    #   c) 2+ ativos COM MESMO nome_urna → MESMA pessoa reregistrada sem
    #                               TSE dar baixa no antigo (Guto Schiavetto
    #                               SP-144, Josiel Machado MS-29029 em 2026).
    #                               Dedup — mantém o sq_candidato maior
    #                               (reregistro mais recente, provavelmente
    #                               o canônico pro TSE).
    #   d) 2+ ativos COM nomes DIFERENTES → pessoas diferentes concorrendo
    #                               ao mesmo número (Laira×Noely DF-3535,
    #                               Amanda×Gringo RS-4567 em 2026). Mostra
    #                               TODOS — só o TSE sabe qual é oficial;
    #                               votos no dia D revelam.
    #
    # Candidatos sem numero (ex.: 0, lixo) nunca são deduped.
    from collections import defaultdict
    import unicodedata
    def _norm_nome(s: str | None) -> str:
        """Normaliza nome pra comparação: minúsculo, sem acento, trim."""
        if not s: return ""
        s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
        return s.strip().lower()

    grupos: dict[tuple, list[Candidato]] = defaultdict(list)
    extras: list[Candidato] = []
    for c in todos:
        if not c.numero:
            extras.append(c)
            continue
        chave = (c.uf or "BR", c.numero)
        grupos[chave].append(c)
    final: list[Candidato] = []
    for cands_do_grupo in grupos.values():
        ativos = [c for c in cands_do_grupo if c.situacao == "ativo"]
        if len(ativos) == 1 and len(cands_do_grupo) > 1:
            final.append(ativos[0])  # caso (a): dedup limpo
            continue
        if len(ativos) >= 2:
            # Caso (c) vs (d): mesmo nome ou nomes diferentes?
            nomes = {_norm_nome(c.nome_urna) for c in ativos}
            if len(nomes) == 1:
                # (c) MESMA pessoa — mantém o sq_candidato maior (mais recente).
                # Inativos homônimos ficam de fora também (não interessam).
                canonico = max(ativos, key=lambda c: str(c.sq_candidato))
                final.append(canonico)
                continue
            # (d) nomes diferentes → mostra todos (fluxo abaixo)
        else:
            final.extend(cands_do_grupo)  # casos (b) e (c): mostra todos
    final.extend(extras)
    final.sort(key=lambda x: (x.numero or 0, str(x.sq_candidato)))
    return [
        {
            "sq_candidato": c.sq_candidato,
            "nome": c.nome,
            "nome_urna": c.nome_urna,
            "numero": c.numero,
            "partido": c.partido_numero,
            "uf": c.uf,
            "foto": _url_foto(c.sq_candidato, c.uf),
            "situacao": c.situacao,
        }
        for c in final
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
        "situacao": c.situacao,
        "foto": _url_foto(c.sq_candidato, c.uf),
        "situacao_tse": _p("descricaoSituacao"),
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


async def _ultimo_snapshot(
    sess: AsyncSession, cargo: int, abr: str, turno: int | None = None,
) -> Snapshot | None:
    """Último snapshot não-suspeito pra (cargo, abrangencia).
    turno=None → qualquer turno (último de todos).
    turno=1 → só 1T (fica fixo em páginas de arquivo do 1º turno).
    turno=2 → só 2T (novo default do site após 05/10/2026)."""
    where = [Snapshot.cod_cargo == cargo, Snapshot.abrangencia == abr,
             Snapshot.suspeito.is_(False)]
    if turno is not None:
        where.append(Snapshot.turno == turno)
    q = (
        select(Snapshot)
        .where(and_(*where))
        .order_by(Snapshot.coletado_em.desc())
        .limit(1)
    )
    r = await sess.execute(q)
    return r.scalar_one_or_none()


async def _calcular_projecao_tendencia(
    sess: AsyncSession, cargo: int, abrangencia: str,
    snap_atual, tot_atual, cands_atual: list,
) -> dict[str, int]:
    """Projeção por tendência da JANELA MÓVEL das últimas N snapshots.

    Problema que resolve: projeção linear simples assume que as urnas
    faltantes vão votar como as já apuradas. No Brasil isso é falso —
    historicamente, Sul/Sudeste apuram primeiro e tendem a direita,
    Nordeste depois e tende a esquerda. Projeção linear enganaria no
    começo da apuração.

    Solução pragmática (sem modelagem regional pseudocientífica): usa a
    taxa de votos ganhos POR % APURADO nas últimas N snapshots. Se o
    candidato está acelerando nas últimas urnas (ganhando mais por %),
    a projeção reflete. Se desacelerou, idem.

    Fórmula:
        taxa_recente = (votos_atual - votos_N_atras) / (pct_atual - pct_N_atras)
        projecao     = votos_atual + taxa_recente * (100 - pct_atual)

    Guardas (silêncio é melhor que ruído):
    - Só roda após >= 30% apurado (abaixo disso a extrapolação é absurda).
    - Precisa de pelo menos 10 snapshots na janela.
    - Delta de % apurado tem que ser >= 1% (evita divisão por quase-zero).
    - Projeção clipada entre `votos_atual` e `2 * projecao_linear`
      pra evitar valores negativos ou absurdos.
    """
    JANELA = 15        # últimas N snapshots consideradas
    MIN_SNAPS = 10     # mínimo pra estimativa confiável
    MIN_PCT_APUR = 30.0
    MIN_DELTA_PCT = 1.0

    if not tot_atual.qt_secoes_total:
        return {}
    pct_apurado_atual = (tot_atual.qt_secoes_totalizadas or 0) * 100.0 / tot_atual.qt_secoes_total
    if pct_apurado_atual < MIN_PCT_APUR or pct_apurado_atual >= 100.0:
        return {}

    # Pega as JANELA últimas snapshots da mesma (cargo, abr) INCLUSIVE a atual
    snaps_rows = (await sess.execute(
        select(Snapshot.id, SnapshotTotais.qt_secoes_totalizadas,
                SnapshotTotais.qt_secoes_total,
                SnapshotTotais.qt_votos_validos)
        .join(SnapshotTotais, SnapshotTotais.snapshot_id == Snapshot.id)
        .where(and_(
            Snapshot.cod_cargo == cargo,
            Snapshot.abrangencia == abrangencia,
            Snapshot.suspeito.is_(False),
            Snapshot.id <= snap_atual.id,
        ))
        .order_by(Snapshot.coletado_em.desc())
        .limit(JANELA)
    )).all()
    if len(snaps_rows) < MIN_SNAPS:
        return {}

    # Snapshot mais antigo da janela — base pro cálculo de delta
    snap_base_id, apur_base, total_base, validos_base = snaps_rows[-1]
    if not total_base or total_base <= 0:
        return {}
    pct_apurado_base = (apur_base or 0) * 100.0 / total_base
    delta_pct = pct_apurado_atual - pct_apurado_base
    if delta_pct < MIN_DELTA_PCT:
        return {}

    # Votos de cada candidato no snapshot base
    votos_base_rows = (await sess.execute(
        select(SnapshotCandidato.sq_candidato, SnapshotCandidato.votos)
        .where(SnapshotCandidato.snapshot_id == snap_base_id)
    )).all()
    votos_cand_base = {sq: v for sq, v in votos_base_rows}

    pct_faltante = 100.0 - pct_apurado_atual
    # Projeção dos VÁLIDOS TOTAIS pela mesma lógica da janela móvel —
    # usada só pra calcular % projetado (nos majoritários onde faz sentido).
    validos_atual = tot_atual.qt_votos_validos or 0
    taxa_validos = (validos_atual - (validos_base or 0)) / delta_pct
    proj_validos = max(validos_atual,
                        int(validos_atual + taxa_validos * pct_faltante))

    out: dict[str, dict] = {}
    for c in cands_atual:
        v_base = votos_cand_base.get(c.sq_candidato, 0)
        delta_votos = c.votos - v_base
        if delta_votos < 0:
            continue  # inconsistência (TSE reprocessou) — pula
        taxa = delta_votos / delta_pct  # votos ganhos por % apurado
        proj_votos = int(c.votos + taxa * pct_faltante)
        # Clipa entre votos atuais e 2x da projeção linear pra evitar
        # extrapolações absurdas (ex.: candidato que acabou de "disparar").
        # Guard de UX, não base estatística.
        if tot_atual.qt_secoes_totalizadas and tot_atual.qt_secoes_total:
            proj_linear = int(c.votos * tot_atual.qt_secoes_total /
                               tot_atual.qt_secoes_totalizadas)
            proj_votos = max(c.votos, min(proj_votos, 2 * proj_linear))
        proj_pct = (proj_votos / proj_validos * 100.0) if proj_validos > 0 else None
        out[c.sq_candidato] = {"votos": proj_votos, "pct": proj_pct}
    return out


@router.get("/apuracao/atual")
async def apuracao_atual(
    cargo: int = Query(...),
    abrangencia: str = Query("BR"),
    turno: int | None = Query(None, ge=1, le=2, description=
        "Filtra pelo turno (1 ou 2). Omitido = último snapshot de qualquer "
        "turno (compatibilidade). Páginas de 2T devem passar turno=2 "
        "explicitamente; páginas de arquivo do 1T devem passar turno=1."),
    inflate: bool = Query(False, description=
        "Se true, inclui nome_urna/numero/partido/situacao de cada "
        "candidato inline no snapshot. Facilita auditoria via curl/"
        "verificacao sem precisar cruzar com /api/candidatos. Default "
        "false pra manter o payload leve (hot path do WS)."),
    sess: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    snap = await _ultimo_snapshot(sess, cargo, abrangencia, turno=turno)
    if not snap:
        return {"disponivel": False}
    tot = (await sess.execute(select(SnapshotTotais).where(SnapshotTotais.snapshot_id == snap.id))).scalar_one()
    cands = (await sess.execute(
        select(SnapshotCandidato).where(SnapshotCandidato.snapshot_id == snap.id)
        .order_by(SnapshotCandidato.posicao)
    )).scalars().all()

    # Pre-fetch metadata dos candidatos (nome/numero/partido/situacao) —
    # usado quer pra inflate=true, quer pra detectar sq_candidato
    # órfãos (apareceu no snapshot mas não está em Candidato).
    sqs_snap = [c.sq_candidato for c in cands]
    ficha_rows = (await sess.execute(
        select(Candidato.sq_candidato, Candidato.nome_urna, Candidato.numero,
               Candidato.partido_numero, Candidato.situacao, Candidato.uf)
        .where(Candidato.sq_candidato.in_(sqs_snap))
    )).all() if sqs_snap else []
    ficha_map = {r.sq_candidato: r for r in ficha_rows}

    # Projeção por tendência: pega as últimas N snapshots pra calcular a
    # taxa recente de voto por % apurado de cada candidato. Mais responsiva
    # que projeção linear estática quando o perfil regional das urnas que
    # faltam é diferente das já apuradas (ex.: SE/SU apura antes do NE).
    # Guardas: só calcula após 30% apurado e com pelo menos 10 snapshots.
    proj_tendencia_map = await _calcular_projecao_tendencia(
        sess, cargo, abrangencia, snap, tot, cands
    )
    # Órfãos: sq_candidato no snapshot sem metadado — bug grave,
    # frontend vai mostrar "sq 2800..." em vez de nome. Expor na
    # resposta pra facilitar diagnóstico via /verificacao.
    orfaos = [sq for sq in sqs_snap if sq not in ficha_map]
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
            _candidato_payload(c, tot, ficha_map.get(c.sq_candidato), inflate,
                                proj_tendencia_map.get(c.sq_candidato),
                                cod_cargo=cargo)
            for c in cands
        ],
        # Órfãos (sq_candidato sem metadado em `candidatos` table).
        # Em prod normal essa lista é vazia. Se aparecer algo, significa
        # que o TSE devolveu sq que a nossa sincronização não tem —
        # frontend precisa refetchar /api/candidatos.
        "orfaos": orfaos,
    }


def _candidato_payload(sc, tot, ficha, inflate: bool,
                        projecao_tendencia: dict | None = None,
                        cod_cargo: int | None = None) -> dict:
    """Monta a linha de candidato. Com inflate=True, inclui
    nome/numero/partido/situacao pra o payload ser auditável sozinho
    (sem precisar cruzar com /api/candidatos). Default enxuto.

    `projecao_tendencia` é dict `{"votos": int, "pct": float|None}` ou None.
    `projecao_pct_tendencia` só é exposto pra cargos MAJORITÁRIOS (1=Pres,
    3=Gov, 5=Sen). Em proporcional (6,7) % individual não é o KPI que
    define eleição — o cálculo proporcional (QE/QP/sobras) é que decide.
    """
    MAJORITARIOS = {1, 3, 5}
    tv = (projecao_tendencia or {}).get("votos")
    tp = (projecao_tendencia or {}).get("pct")
    base = {
        "sq_candidato": sc.sq_candidato,
        "votos": sc.votos,
        "pct_validos": float(sc.pct_validos),
        "posicao": sc.posicao,
        "projecao_linear": int(sc.votos / (tot.qt_secoes_totalizadas / tot.qt_secoes_total))
            if tot.qt_secoes_total and tot.qt_secoes_totalizadas else sc.votos,
        # Projeção por tendência das últimas N snapshots. None antes de
        # 30% apurado (sem dados suficientes) ou se não houver histórico.
        "projecao_tendencia": tv,
    }
    # Projeção de % só em majoritários (ver docstring acima).
    if cod_cargo in MAJORITARIOS:
        base["projecao_pct_tendencia"] = tp
    return _finalizar_payload_candidato(base, ficha, inflate)


def _finalizar_payload_candidato(base: dict, ficha, inflate: bool) -> dict:
    """Separado pra manter a assinatura original de _candidato_payload."""
    if inflate and ficha:
        base["nome_urna"] = ficha.nome_urna
        base["numero"] = ficha.numero
        base["partido"] = ficha.partido_numero
        base["situacao"] = ficha.situacao
        base["uf"] = ficha.uf
    elif inflate and not ficha:
        # Órfão — sinaliza explicitamente em vez de omitir
        base["nome_urna"] = None
        base["orfao"] = True
    return base


@router.get("/apuracao/historico")
async def historico(
    cargo: int = Query(...),
    abrangencia: str = Query("BR"),
    candidatos: str = Query(..., description="lista sq_candidato separada por vírgula"),
    turno: int | None = Query(None, ge=1, le=2),
    desde: datetime | None = None,
    sess: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    sqs = [s for s in candidatos.split(",") if s]
    where_clauses = [
        Snapshot.cod_cargo == cargo,
        Snapshot.abrangencia == abrangencia,
        Snapshot.suspeito.is_(False),
    ]
    if turno is not None:
        where_clauses.append(Snapshot.turno == turno)
    stmt = (
        select(Snapshot.id, Snapshot.coletado_em, SnapshotCandidato.sq_candidato,
               SnapshotCandidato.votos, SnapshotCandidato.pct_validos,
               SnapshotTotais.qt_votos_validos, SnapshotTotais.qt_eleitorado_apto,
               SnapshotTotais.qt_eleitorado_apto_totalizadas)
        .join(SnapshotCandidato, SnapshotCandidato.snapshot_id == Snapshot.id)
        .join(SnapshotTotais, SnapshotTotais.snapshot_id == Snapshot.id)
        .where(and_(
            *where_clauses,
            # Só inclui snapshots que já são apuração — critério é
            # qt_secoes_totalizadas > 0 (não qt_votos_validos). Diferença
            # importante no dia D: uma seção pode ter sido totalizada com
            # TODOS os votos brancos/nulos, dando qt_votos_validos=0 mas
            # qt_secoes_totalizadas=1 — isso é apuração real, deve
            # aparecer no gráfico (improvável mas possível).
            SnapshotTotais.qt_secoes_totalizadas > 0,
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
    # Gate correto é "nenhuma seção totalizada ainda", não "nenhum voto
    # válido" — se já há seção apurada mas só com brancos/nulos, o
    # motor pode rodar (QE=0 trivialmente, mas status fica correto).
    if not tot or (tot.qt_secoes_totalizadas or 0) == 0:
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
    def _idade_de(cnd) -> int | None:
        """Extrai idade em anos completos a partir do dataDeNascimento no
        raw_divulga. Usado só pra desempate interno do partido (art. 110 CE)."""
        from datetime import date
        raw = cnd.raw_divulga or {}
        dn = raw.get("dataDeNascimento")
        if not dn:
            return None
        try:
            if "/" in dn:
                d, m, y = dn.split("/")
            else:
                y, m, d = dn.split("-")
            nasc = date(int(y), int(m), int(d))
            hoje = date.today()
            return hoje.year - nasc.year - ((hoje.month, hoje.day) < (nasc.month, nasc.day))
        except (ValueError, AttributeError, TypeError):
            return None

    cands_prop = [
        CandidatoProporcional(
            sq_candidato=sc.sq_candidato,
            nome_urna=cnd.nome_urna,
            numero=cnd.numero,
            partido_numero=cnd.partido_numero,
            votos=sc.votos,
            situacao=cnd.situacao,  # motor filtra != 'ativo' (votos nulos)
            idade_anos=_idade_de(cnd),  # desempate art. 110 CE
        )
        for sc, cnd in cands_db
    ]
    r = calcular_eleitos_proporcional(cands_prop, vagas=vagas)

    # Status PROJETADO: roda o motor de novo com votos projetados pela
    # janela móvel. Mostra pro usuário "quem seria eleito se o ritmo
    # recente continuar" — útil pra proporcional onde votos individuais
    # altos não garantem vaga (QE/QP/sobras é que decide).
    proj_tendencia = await _calcular_projecao_tendencia(
        sess, cargo, uf.upper(), snap, tot,
        [sc for sc, _ in cands_db],
    )
    status_projetado: dict[str, str] = {}
    if proj_tendencia:
        cands_prop_proj = [
            CandidatoProporcional(
                sq_candidato=sc.sq_candidato,
                nome_urna=cnd.nome_urna,
                numero=cnd.numero,
                partido_numero=cnd.partido_numero,
                votos=(proj_tendencia.get(sc.sq_candidato) or {}).get("votos", sc.votos),
                situacao=cnd.situacao,
                idade_anos=_idade_de(cnd),
            )
            for sc, cnd in cands_db
        ]
        r_proj = calcular_eleitos_proporcional(cands_prop_proj, vagas=vagas)
        status_projetado = {c.sq_candidato: c.status for c in r_proj.candidatos}

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
                "status_projetado": status_projetado.get(c.sq_candidato),  # mesmo cálculo com votos projetados
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
    turno: int | None = Query(None, ge=1, le=2),
    sess: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Retorna líder de cada município da UF, extraído do breakdown por
    município embutido no snapshot da UF (campo `abr` ou `mu` do TSE).

    Se o TSE não incluir esse breakdown no JSON, retorna {} e o mapa
    municipal fica cinza — mas ainda navegável.
    """
    from sqlalchemy import func
    # Último snapshot dessa (cargo, uf) e busca líder por município
    base_where = [
        Snapshot.cod_cargo == cargo,
        Snapshot.abrangencia == uf,
        Snapshot.suspeito.is_(False),
    ]
    if turno is not None:
        base_where.append(Snapshot.turno == turno)
    subq = (
        select(func.max(Snapshot.id).label("last_id"))
        .where(and_(*base_where))
        .scalar_subquery()
    )
    # Top-5 por município pra conseguir pular retirados/cassados —
    # mesma lógica do lideres-por-uf, votos deles são nulos por lei.
    q = (
        select(
            SnapshotMunicipio.cod_ibge,
            SnapshotMunicipio.sq_candidato,
            SnapshotMunicipio.votos,
            SnapshotMunicipio.posicao,
            Candidato.nome_urna, Candidato.situacao,
        )
        .join(Candidato, Candidato.sq_candidato == SnapshotMunicipio.sq_candidato)
        .where(
            SnapshotMunicipio.snapshot_id == subq,
            SnapshotMunicipio.posicao <= 5,
        )
        .order_by(SnapshotMunicipio.cod_ibge, SnapshotMunicipio.posicao)
    )
    r = await sess.execute(q)
    por_mun: dict[str, list[Any]] = {}
    for row in r.all():
        por_mun.setdefault(row.cod_ibge, []).append(row)
    municipios: dict[str, dict[str, Any]] = {}
    sq_para_idx: dict[str, int] = {}
    for cod_ibge, linhas in por_mun.items():
        # Primeiro ATIVO com voto > 0. Pré-apuração todos têm 0 votos
        # e a 'posicao' vem arbitrária do TSE — sem voto não há líder,
        # senão o mapa pinta todos os municípios da mesma cor fantasma.
        lider = next(
            (l for l in linhas if l.situacao == "ativo" and l.votos > 0),
            None,
        )
        if not lider:
            continue
        if lider.sq_candidato not in sq_para_idx:
            sq_para_idx[lider.sq_candidato] = len(sq_para_idx)
        municipios[cod_ibge] = {
            "sq_candidato": lider.sq_candidato,
            "nome_lider": lider.nome_urna,
            "votos": lider.votos,
            "cor_idx": sq_para_idx[lider.sq_candidato],
        }
    return {"municipios": municipios}


@router.get("/apuracao/lideres-por-uf")
async def lideres_por_uf(
    cargo: int = Query(...),
    turno: int | None = Query(None, ge=1, le=2),
    sess: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Retorna, para cada UF onde há snapshot desse cargo, quem está em 1º.

    Usado pelo mapa do frontend: colore cada UF pelo candidato líder.
    Para Presidente (nacional), o cargo pode não ter recorte por UF —
    nesse caso volta {} e o mapa fica todo cinza.
    """
    # Último snapshot por UF/cargo — subquery com max(coletado_em) por UF
    from sqlalchemy import func
    base_where = [Snapshot.cod_cargo == cargo, Snapshot.suspeito.is_(False),
                  Snapshot.abrangencia != "BR"]
    if turno is not None:
        base_where.append(Snapshot.turno == turno)
    subq = (
        select(
            Snapshot.abrangencia.label("abr"),
            func.max(Snapshot.coletado_em).label("ts"),
        )
        .where(and_(*base_where))
        .group_by(Snapshot.abrangencia)
        .subquery()
    )
    # Pega top-5 candidatos de cada UF (não só posicao=1) pra conseguir
    # pular os retirados/cassados — votos deles são nulos por lei
    # (9.504 §3º) e não devem pintar o mapa.
    q = (
        select(
            Snapshot.abrangencia, SnapshotCandidato.sq_candidato,
            SnapshotCandidato.votos, SnapshotCandidato.posicao,
            Candidato.nome_urna, Candidato.situacao,
        )
        .join(SnapshotCandidato, SnapshotCandidato.snapshot_id == Snapshot.id)
        .join(Candidato, Candidato.sq_candidato == SnapshotCandidato.sq_candidato)
        .join(subq, and_(subq.c.abr == Snapshot.abrangencia,
                         subq.c.ts == Snapshot.coletado_em))
        .where(Snapshot.cod_cargo == cargo, SnapshotCandidato.posicao <= 5)
        .order_by(Snapshot.abrangencia, SnapshotCandidato.posicao)
    )
    r = await sess.execute(q)
    # Agrupa por UF; dentro de cada UF pega o primeiro ATIVO
    por_uf: dict[str, list[Any]] = {}
    for row in r.all():
        por_uf.setdefault(row.abrangencia, []).append(row)
    ufs: dict[str, dict[str, Any]] = {}
    sq_para_idx: dict[str, int] = {}
    for abr, linhas in por_uf.items():
        # Mesma lógica do por-municipio: só é líder quem tem voto > 0.
        # Pré-apuração a posicao é arbitrária e pintaria todo mapa com a
        # mesma cor fantasma (bug reportado 03/10 — Flávio Bolsonaro
        # aparecia em TODAS as 27 UFs com 0 votos).
        lider = next(
            (l for l in linhas if l.situacao == "ativo" and l.votos > 0),
            None,
        )
        if not lider:
            continue  # Sem voto → UF fica cinza no mapa
        if lider.sq_candidato not in sq_para_idx:
            sq_para_idx[lider.sq_candidato] = len(sq_para_idx)
        ufs[abr] = {
            "sq_candidato": lider.sq_candidato,
            "nome_lider": lider.nome_urna,
            "votos": lider.votos,
            "cor_idx": sq_para_idx[lider.sq_candidato],
        }
    return {"ufs": ufs}


@router.get("/eventos")
async def eventos(
    cargo: int = Query(...),
    abrangencia: str = Query("BR"),
    turno: int | None = Query(None, ge=1, le=2, description=
        "Filtra eventos pelo turno (1 ou 2). Omitido = todos os turnos. "
        "Páginas 2T devem passar turno=2 pra não mostrar MATEMATICAMENTE_"
        "ELIMINADO/VIRADA do 1T no feed do 2T."),
    sess: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    where = [Evento.cod_cargo == cargo, Evento.abrangencia == abrangencia]
    if turno is not None:
        # Snapshot do evento tem o turno; join leve
        where.append(Evento.snapshot_id.in_(
            select(Snapshot.id).where(Snapshot.turno == turno)
        ))
    r = await sess.execute(
        select(Evento).where(and_(*where)).order_by(Evento.ocorrido_em)
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
    from poller.candidatos_tse import parse_lista, _upsert, _marcar_removidos_pelo_tse
    cargo = int(payload["cargo"])
    uf_arg = payload.get("uf")
    uf = None if uf_arg in ("BR", "", None) else uf_arg
    tse_json = payload["json"]
    cands = parse_lista(tse_json, cargo, uf)
    if not cands:
        return {"atualizados": 0, "aviso": "JSON não tinha candidatos ou schema desconhecido"}
    n = await _upsert(sess, cands)
    sq_vistos = {c.sq_candidato for c in cands}
    removidos = await _marcar_removidos_pelo_tse(sess, uf_arg or "BR", cargo, sq_vistos)
    return {"atualizados": n, "removidos": removidos, "cargo": cargo, "uf": uf_arg or "BR"}


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
        .where(SnapshotTotais.qt_secoes_totalizadas == 0)
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


@router.get("/admin/duplicatas", dependencies=[Depends(_exigir_admin)])
async def admin_duplicatas(sess: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    """Lista candidatos com (cod_cargo, uf, numero) duplicados — sinal de
    substituição/reregistro TSE em que o sq antigo ficou no DB.
    """
    rows = (await sess.execute(select(Candidato))).scalars().all()
    buckets: dict[tuple, list[Candidato]] = {}
    for c in rows:
        if not c.numero:
            continue
        chave = (c.cod_cargo, c.uf or "BR", c.numero)
        buckets.setdefault(chave, []).append(c)
    dups = []
    for (cargo, uf, numero), lista in buckets.items():
        if len(lista) < 2:
            continue
        dups.append({
            "cargo": cargo, "uf": uf, "numero": numero,
            "candidatos": [
                {"sq": c.sq_candidato, "nome_urna": c.nome_urna,
                 "situacao": c.situacao}
                for c in lista
            ],
        })
    return {"ok": True, "total": len(dups), "duplicatas": dups}


@router.post("/admin/reavaliar-situacao", dependencies=[Depends(_exigir_admin)])
async def admin_reavaliar_situacao(sess: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    """Reavalia a situacao de todos os candidatos a partir do raw_divulga.

    Útil quando o TSE atualizou um status (ex.: 'Inapto' depois de ter
    sido 'Pendente de julgamento') e queremos refletir isso sem esperar
    o próximo ciclo de sync completo.
    """
    from poller.candidatos_tse import reavaliar_situacao_pelo_raw
    n = await reavaliar_situacao_pelo_raw(sess)
    return {"ok": True, "mudados": n}


@router.get("/admin/diagnostico-mismatches", dependencies=[Depends(_exigir_admin)])
async def diagnostico_mismatches(sess: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    """Lista TODOS os sq_candidato que aparecem em snapshots mas não
    existem em `candidatos` (órfãos). Esses viram 'nome: null' na UI
    porque o join falha.

    Causa típica: TSE devolveu um candidato que o sync via Termux ainda
    não importou. Fix: rodar scripts/importar_termux.py novamente.
    """
    # Todos os sq_candidato distintos vistos em snapshots
    q_snap = select(SnapshotCandidato.sq_candidato).distinct()
    sqs_snap = {r[0] for r in (await sess.execute(q_snap)).all()}
    if not sqs_snap:
        return {"ok": True, "orfaos": [], "total_snapshots": 0}
    # Quais estão em Candidato
    q_cand = select(Candidato.sq_candidato).where(
        Candidato.sq_candidato.in_(sqs_snap)
    )
    sqs_cand = {r[0] for r in (await sess.execute(q_cand)).all()}
    orfaos = sorted(sqs_snap - sqs_cand)
    return {
        "ok": True,
        "total_em_snapshots": len(sqs_snap),
        "total_em_candidatos": len(sqs_cand),
        "orfaos": orfaos,
        "diagnostico": (
            "Lista de sq_candidato que o TSE devolveu mas nosso sync "
            "não tem metadado. Rode scripts/importar_termux.py ou "
            "POST /api/admin/importar-candidatos para resolver."
        ) if orfaos else "tudo em dia",
    }


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
    base = settings.tse_cdn_base.rstrip("/")  # inclui /ele2026
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


@router.get("/apuracao/zona", deprecated=True)
async def apuracao_zona(
    uf: str = Query(..., min_length=2, max_length=2),
    municipio: str = Query(..., min_length=1, max_length=6),
    zona: str = Query(..., min_length=1, max_length=5),
    cargo: int = Query(...),
    turno: int = Query(1, ge=1, le=2),
) -> dict[str, Any]:
    """DEPRECATED (03/10/2026). TSE não publica agregado por zona no S3
    público — apenas BU por seção. Testamos padrões 2024/2026 e todos
    retornam 404.

    Pra drill-down por zona, o caminho correto é agregar BUs das seções
    da zona client-side via /api/apuracao/bu — mas isso custa centenas
    de requests por zona e não escala.

    Endpoint mantido com 410 Gone pra documentar a limitação. Qualquer
    tentativa de uso retorna `disponivel: false` com motivo claro.
    """
    return {
        "disponivel": False,
        "motivo": (
            "TSE não publica agregado por zona eleitoral no S3 público. "
            "Use /api/apuracao/municipio-tse (agregado por município) ou "
            "/api/apuracao/bu (seção individual)."
        ),
        "deprecated": True,
    }


# Mantido pra referência: o código original do zona ficava aqui, com
# cache e URL /{cod}/dados/{uf}/{uf}{mun}z{zn}-c{cargo:04d}-e{cod:06d}-u.json
# que SEMPRE retorna 404 em testes contra TSE 2022, 2024 e 2026 pré-apuração.
async def _apuracao_zona_removida(
    uf: str = Query(..., min_length=2, max_length=2),
    municipio: str = Query(..., min_length=1, max_length=6),
    zona: str = Query(..., min_length=1, max_length=5),
    cargo: int = Query(...),
    turno: int = Query(1, ge=1, le=2),
) -> dict[str, Any]:
    """Código original mantido pra referência histórica — removido do
    endpoint real em 03/10/2026 após validação contra TSE.
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
    base = settings.tse_cdn_base.rstrip("/")
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


# ============ Lista de municípios por UF (TSE) ============
# Mapeia nome do município → código TSE. Usado pela página /urna pra
# evitar que o usuário tenha que decorar o código numérico (ninguém
# sabe que São Paulo = 71099, ex.).
_CACHE_MUN_LIST: dict[str, tuple[float, list]] = {}
_CACHE_MUN_LIST_TTL = 24 * 3600  # 24h — a lista raramente muda


@router.get("/municipios")
async def listar_municipios(uf: str = Query(..., min_length=2, max_length=2)) -> dict[str, Any]:
    """Lista oficial de municípios da UF com código TSE + nome.

    Fonte: config/arquivo-urna do pleito 3220 (eleição federal 2026).
    URL: /arquivo-urna/3220/config/{uf}/{uf}-p003220-cs.json
    Esse arquivo também traz todas as zonas de cada município e seções
    de cada zona — base pro dropdown em cascata da /urna.

    Cacheado 24h. Retorna lista enxuta (só codigo + nome); use
    /api/municipios/zonas pra zonas de um município específico.
    """
    from app.config import get_settings
    from time import monotonic
    uf = uf.lower()
    agora = monotonic()
    hit = _CACHE_MUN_LIST.get(uf)
    if hit and (agora - hit[0]) < _CACHE_MUN_LIST_TTL:
        return {"cache_hit": True, "municipios": hit[1]}

    settings = get_settings()
    base = settings.tse_cdn_base.rstrip("/")
    # Pleito 3220 = eleição federal 2026 (04/10). Hardcoded pq é o
    # pleito da eleição em curso. Se mudar, trocar aqui.
    cd_pleito = "3220"
    url = f"{base}/arquivo-urna/{cd_pleito}/config/{uf}/{uf}-p00{cd_pleito}-cs.json"
    j = await _fetch_tse_json(url)
    if not j:
        return {
            "municipios": [],
            "erro": f"TSE não publicou configuração pra {uf.upper()} (url: {url})",
        }

    # Formato: {"abr": [{"cd": "sp", "mu": [{"cd": "71072", "nm": "SÃO PAULO",
    #   "zon": [{"cd": "0001", "sec": [{"ns": "0001"}, ...]}]}, ...]}]}
    municipios: list[dict] = []
    for abr in j.get("abr", []):
        if not isinstance(abr, dict):
            continue
        for m in abr.get("mu", []):
            if not isinstance(m, dict):
                continue
            cd = m.get("cd")
            nm = m.get("nm")
            if cd and nm:
                municipios.append({
                    "codigo": str(cd),
                    "nome": str(nm).title(),
                    "qtd_zonas": len(m.get("zon", [])),
                })
    municipios.sort(key=lambda m: m["nome"])
    _CACHE_MUN_LIST[uf] = (agora, municipios)
    return {"municipios": municipios, "total": len(municipios)}


@router.get("/municipios/{municipio}/zonas")
async def listar_zonas_municipio(
    municipio: str,
    uf: str = Query(..., min_length=2, max_length=2),
) -> dict[str, Any]:
    """Zonas e seções de um município específico. Fonte: mesmo arquivo
    config/arquivo-urna que /api/municipios usa.

    Retorna estrutura: {"zonas": [{"codigo": "0001", "secoes": [...]}]}
    """
    from app.config import get_settings
    from time import monotonic
    uf = uf.lower()
    agora = monotonic()
    # Reusa cache do arquivo bruto (chave diferente)
    chave_raw = f"raw:{uf}"
    hit = _CACHE_MUN_LIST.get(chave_raw)
    if hit and (agora - hit[0]) < _CACHE_MUN_LIST_TTL:
        raw = hit[1]
    else:
        settings = get_settings()
        base = settings.tse_cdn_base.rstrip("/")
        url = f"{base}/arquivo-urna/3220/config/{uf}/{uf}-p003220-cs.json"
        j = await _fetch_tse_json(url)
        if not j:
            return {"zonas": [], "erro": "config não disponível"}
        raw = j
        _CACHE_MUN_LIST[chave_raw] = (agora, raw)

    for abr in raw.get("abr", []):
        for m in abr.get("mu", []):
            if str(m.get("cd")) == str(int(municipio)):
                return {
                    "municipio": {"codigo": m["cd"], "nome": m.get("nm", "")},
                    "zonas": [
                        {
                            "codigo": z.get("cd"),
                            "secoes": [s.get("ns") for s in z.get("sec", []) if s.get("ns")],
                        }
                        for z in m.get("zon", [])
                    ],
                }
    return {"zonas": [], "erro": f"município {municipio} não achado em {uf.upper()}"}


# ============ Boletim de Urna (BU) — verificação por seção ============
# TSE publica BU por seção eleitoral individual. Formato:
#   https://resultados.tse.jus.br/oficial/{cod}/dados/{uf}/{uf}{mun}/{zona}/{secao}/o{cod_padded}-{mun}{zona}{secao}.json
# Cache 5min pq BU muda só na hora da totalização de cada seção.
_CACHE_BU: dict[str, tuple[float, dict]] = {}
_CACHE_BU_TTL = 300.0


@router.get("/apuracao/bu")
async def apuracao_bu(
    uf: str = Query(..., min_length=2, max_length=2),
    municipio: str = Query(..., min_length=1, max_length=6),
    zona: str = Query(..., min_length=1, max_length=5),
    secao: str = Query(..., min_length=1, max_length=5),
    cargo: int = Query(1, ge=1, le=7),
    turno: int = Query(1, ge=1, le=2),
) -> dict[str, Any]:
    """Boletim de Urna de uma seção específica — baixa direto do TSE,
    sem persistir. Útil pra verificação: 'confere com a minha seção?'.

    Retorna totais nominais da seção, candidatos com votos, URL da
    imagem assinada do BU (JPEG original do TSE) pra download/verificação.
    """
    from app.config import get_settings
    from time import monotonic
    uf = uf.lower()
    mu = str(int(municipio)).zfill(5)
    zn = str(int(zona)).zfill(4)
    se = str(int(secao)).zfill(4)
    settings = get_settings()
    if cargo == 1:
        cod = settings.eleicao_cod_1t if turno == 1 else settings.eleicao_cod_2t
    else:
        cod = settings.eleicao_cod_1t_estadual if turno == 1 else settings.eleicao_cod_2t_estadual
    cod_pad = str(cod).zfill(5)
    chave = f"bu:{uf}:{mu}:{zn}:{se}:{cargo}:{cod}"
    agora = monotonic()
    hit = _CACHE_BU.get(chave)
    if hit and (agora - hit[0]) < _CACHE_BU_TTL:
        return {"cache_hit": True, **hit[1]}

    base = settings.tse_cdn_base.rstrip("/")
    # JSON do BU: /dados/{uf}/{uf}{mun}/{zona}/{secao}/o{cod}-{mun}{zona}{secao}.json
    url_json = f"{base}/{cod}/dados/{uf}/{uf}{mu}/{zn}/{se}/o{cod_pad}-{mu}{zn}{se}.json"
    # Imagem assinada do BU: /dados_bu_imgbu/{uf}/{mun}/{zona}/{secao}/o{cod}-{mun}{zona}{secao}-bu.jpeg
    url_bu_img = f"{base}/{cod}/dados_bu_imgbu/{uf}/{uf}{mu}/{zn}/{se}/o{cod_pad}-{mu}{zn}{se}-bu.jpeg"

    j = await _fetch_tse_json(url_json)
    if not j:
        return {
            "disponivel": False,
            "motivo": (
                "BU não encontrado. Causas comuns: (1) a seção ainda não "
                "foi totalizada (BUs só saem a partir das 17h de domingo "
                "do dia D); (2) o código do município/zona/seção está "
                "incorreto — confira em tse.jus.br/eleitor/onde-votar."
            ),
            "url_tentada": url_json,
            "url_imagem_bu": url_bu_img,
        }

    # TSE devolve estrutura específica pro BU com cargos agrupados.
    # Minimamente útil: totais da seção + candidatos com votos pro cargo pedido.
    try:
        from poller.parser import parse_snapshot
        parsed = parse_snapshot(j)
    except Exception:
        return {"disponivel": False, "erro": "parse_bu", "url_imagem_bu": url_bu_img}
    tot = parsed.totais if parsed else None
    body = {
        "disponivel": True,
        "uf": uf.upper(),
        "municipio": mu.lstrip("0") or "0",
        "zona": zn.lstrip("0") or "0",
        "secao": se.lstrip("0") or "0",
        "cargo": cargo,
        "turno": turno,
        "url_imagem_bu": url_bu_img,
        "url_json_bu": url_json,
        "totais": {
            "eleitorado_apto": tot.qt_eleitorado_apto if tot else 0,
            "comparecimento": tot.qt_comparecimento if tot else 0,
            "abstencoes": tot.qt_abstencoes if tot else 0,
            "votos_validos": tot.qt_votos_validos if tot else 0,
            "votos_brancos": tot.qt_votos_brancos if tot else 0,
            "votos_nulos": tot.qt_votos_nulos if tot else 0,
        } if tot else None,
        "candidatos": [
            {"sq_candidato": c.sq_candidato, "votos": c.votos,
             "pct_validos": float(c.pct_validos)}
            for c in (parsed.candidatos if parsed else [])
        ],
    }
    _CACHE_BU[chave] = (agora, body)
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
