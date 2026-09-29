"""Bot do Telegram — comandos de consulta + assinaturas + config.

Arquitetura mínima: um único asyncio.Task com long-polling (getUpdates)
direto via httpx contra a Bot API. Sem aiogram/PTB — cabe em ~500 linhas.

Comandos (todos aparecem no menu do Telegram):

  /start                 menu principal (inline keyboard)
  /help                  lista de comandos

  Consulta rápida ao vivo:
  /pct [cargo] [uf]      % de seções apuradas
  /placar [cargo] [uf]   top 5 candidatos com barra
  /lider [cargo] [uf]    quem lidera agora + margem
  /candidato <num> [uf]  ficha completa por número na urna
  /vs <num1> <num2> [uf] compara dois candidatos lado a lado
  /mapa [cargo]          líder por UF (Presidente=todas)
  /proporcional <uf>     dep. federal por UF (QE + D'Hondt)
  /estadual <uf>         dep. estadual por UF
  /eventos [cargo] [uf]  últimos eventos matemáticos
  /status                totais + hash do snapshot atual (verificável)
  /tse                   link direto pra apuração oficial

  Assinaturas (recebe notificações):
  /assinar               assistente inline pra criar assinatura
  /minhas                lista + botões pra remover
  /pausar                pausa TODAS suas notificações (útil pra descanso)
  /retomar               retoma
  /silencio HH-HH        janela de silêncio diário (BRT). Ex.: /silencio 00-07
  /silencio off          desativa a janela
  /apagar_tudo           remove tudo

  Piada útil:
  /cola <num> [uf]       manda a foto do candidato (colinha pro dia da urna)

Quando o poller detecta um evento matemático novo, chama
`enviar_notificacoes(eventos, cargo, abr)` que consulta as assinaturas
casando por (cargo, abrangência, tipo) e envia a mensagem — respeitando
pausa e janela de silêncio.
"""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timezone, timedelta
from typing import Any, Iterable

import httpx
from sqlalchemy import select, delete, and_, desc, func
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.config import get_settings
from app.db import SessionLocal
from app.models import (
    TelegramSubscription, TelegramChatConfig, Candidato, Partido,
    Snapshot, SnapshotTotais, SnapshotCandidato, Evento,
)

log = logging.getLogger(__name__)

# Estado do assistente de assinatura por user_id (perde no restart, ok)
_ESTADOS: dict[int, dict] = {}
BRT = timezone(timedelta(hours=-3))

CARGOS = {1: "Presidente", 3: "Governador", 5: "Senador",
          6: "Dep. Federal", 7: "Dep. Estadual"}
UFS = ["AC","AL","AM","AP","BA","CE","DF","ES","GO","MA","MG","MS","MT",
       "PA","PB","PE","PI","PR","RJ","RN","RO","RR","RS","SC","SE","SP","TO"]
TIPOS = {
    "ELEITO_1T": "🎉 Eleito no 1º turno",
    "ELEITO_MAJORITARIO": "🏆 Eleito majoritário",
    "SEGUNDO_TURNO_DEFINIDO": "⚡ 2º turno definido",
    "VIRADA": "🔄 Virada",
    "MATEMATICAMENTE_ELIMINADO": "❌ Matematicamente eliminado",
}
EMOJI_TIPO = {"ELEITO_1T": "🎉", "ELEITO_MAJORITARIO": "🏆",
              "SEGUNDO_TURNO_DEFINIDO": "⚡", "VIRADA": "🔄",
              "MATEMATICAMENTE_ELIMINADO": "❌"}
SITE_URL = "https://elei-es-production.up.railway.app"

# ================== helpers HTTP ==================

def _api_base() -> str | None:
    tok = (get_settings().telegram_bot_token or "").strip()
    return f"https://api.telegram.org/bot{tok}" if tok else None


async def _api(client: httpx.AsyncClient, metodo: str, **payload) -> dict:
    base = _api_base()
    if not base:
        return {}
    try:
        r = await client.post(f"{base}/{metodo}", json=payload, timeout=20.0)
        j = r.json()
    except Exception:
        log.exception("telegram %s http falhou", metodo)
        return {}
    if not j.get("ok"):
        log.warning("telegram %s: %s", metodo, j.get("description"))
    return j


def _md_escape(s: str) -> str:
    """Escapa caracteres reservados do Markdown legacy do Telegram
    (`_`, `*`, `` ` ``, `[`) em strings que serão intercaladas em
    texto formatado. Nomes de candidatos com "_" (raro mas real)
    ou reticências apostrofadas quebravam a formatação e o
    Telegram devolvia erro 400 "can't parse entities".
    """
    if not s:
        return s
    return s.replace("\\", "\\\\").replace("_", "\\_").replace("*", "\\*") \
            .replace("`", "\\`").replace("[", "\\[")


async def _send(client, chat_id: int, texto: str, keyboard: dict | None = None,
                foto: str | None = None) -> None:
    # Telegram exige objeto válido em reply_markup — passar null dá 400.
    # Omitimos o campo quando não há teclado.
    extras: dict[str, Any] = {}
    if keyboard is not None:
        extras["reply_markup"] = keyboard
    if foto:
        await _api(client, "sendPhoto", chat_id=chat_id, photo=foto,
                   caption=texto[:1024], parse_mode="Markdown", **extras)
        return
    await _api(client, "sendMessage", chat_id=chat_id, text=texto,
               parse_mode="Markdown", disable_web_page_preview=True, **extras)


# ================== parsing de args ==================

def _parse_cargo_uf(args: list[str], default_cargo: int = 1) -> tuple[int, str]:
    """Tenta extrair (cargo, uf) de args do usuário — tolerante:
    /pct presidente / /pct 1 SP / /pct SP / /pct governador RJ"""
    cargo = default_cargo
    uf = "BR"
    mapa = {"presidente": 1, "pres": 1, "governador": 3, "gov": 3,
            "senador": 5, "sen": 5, "deputado": 6, "df": 6, "dep": 6,
            "estadual": 7, "de": 7}
    for a in args:
        s = a.strip().lower()
        if s.isdigit():
            n = int(s)
            if n in CARGOS:
                cargo = n
        elif s in mapa:
            cargo = mapa[s]
        elif len(s) == 2 and s.upper() in UFS:
            uf = s.upper()
        elif s in ("br", "brasil"):
            uf = "BR"
    if cargo != 1 and uf == "BR":
        uf = "SP"  # majoritário exige UF; default sensato
    return cargo, uf


def _parse_hora_intervalo(s: str) -> tuple[int, int] | None:
    m = re.match(r"^(\d{1,2})[-:h](\d{1,2})$", s.strip())
    if not m:
        return None
    a, b = int(m.group(1)), int(m.group(2))
    if 0 <= a <= 23 and 0 <= b <= 23:
        return a, b
    return None


# ================== keyboards ==================

def _kb_principal() -> dict:
    return {"inline_keyboard": [
        [{"text": "📊 Placar agora", "callback_data": "menu:placar"}],
        [{"text": "🗺 Mapa por UF", "callback_data": "menu:mapa"}],
        [{"text": "🔔 Nova assinatura", "callback_data": "sub:cargo"}],
        [{"text": "📋 Minhas assinaturas", "callback_data": "menu:minhas"}],
        [{"text": "⚙ Configurações", "callback_data": "menu:config"}],
        [{"text": "🌐 Abrir site", "url": SITE_URL},
         {"text": "📖 TSE oficial", "url": "https://resultados.tse.jus.br"}],
    ]}


def _kb_escolher_cargo(prefix: str, incluir_prop: bool = False) -> dict:
    cargos = [(1, "Presidente"), (3, "Governador"), (5, "Senador")]
    if incluir_prop:
        cargos += [(6, "Dep. Federal"), (7, "Dep. Estadual")]
    kb = [[{"text": nome, "callback_data": f"{prefix}:{c}"}] for c, nome in cargos]
    kb.append([{"text": "‹ Menu", "callback_data": "menu:home"}])
    return {"inline_keyboard": kb}


def _kb_escolher_uf(prefix: str, cargo: int) -> dict:
    linhas: list[list[dict]] = []
    for i in range(0, len(UFS), 4):
        linhas.append([{"text": u, "callback_data": f"{prefix}:{cargo}:{u}"} for u in UFS[i:i+4]])
    linhas.append([{"text": "‹ Voltar", "callback_data": f"{prefix}back"}])
    return {"inline_keyboard": linhas}


def _kb_tipos(marcados: list[str]) -> dict:
    kb = [[{"text": ("✅ " if t in marcados else "◻ ") + rot,
            "callback_data": f"tipo:{t}"}] for t, rot in TIPOS.items()]
    kb.append([{"text": "✓ Salvar", "callback_data": "sub:salvar"},
               {"text": "‹ Voltar", "callback_data": "sub:cargo"}])
    return {"inline_keyboard": kb}


def _kb_config(cfg: TelegramChatConfig | None) -> dict:
    pausado = cfg and cfg.pausado_global
    sil = None
    if cfg and cfg.silencio_inicio is not None:
        sil = f"{cfg.silencio_inicio:02d}h → {cfg.silencio_fim:02d}h"
    return {"inline_keyboard": [
        [{"text": ("▶ Retomar" if pausado else "⏸ Pausar tudo"),
          "callback_data": "cfg:toggle_pausa"}],
        [{"text": f"🌙 Silêncio: {sil or 'off'}",
          "callback_data": "cfg:silencio"}],
        [{"text": "🗑 Apagar todas as assinaturas",
          "callback_data": "cfg:apagar_tudo"}],
        [{"text": "‹ Menu", "callback_data": "menu:home"}],
    ]}


# ================== queries do banco ==================

async def _snapshot_atual(sess, cargo: int, abr: str) -> tuple[Snapshot, SnapshotTotais, list[SnapshotCandidato]] | None:
    q = (select(Snapshot)
         .where(and_(Snapshot.cod_cargo == cargo, Snapshot.abrangencia == abr,
                     Snapshot.suspeito.is_(False)))
         .order_by(Snapshot.coletado_em.desc()).limit(1))
    snap = (await sess.execute(q)).scalar_one_or_none()
    if not snap:
        return None
    tot = (await sess.execute(
        select(SnapshotTotais).where(SnapshotTotais.snapshot_id == snap.id)
    )).scalar_one()
    cands = (await sess.execute(
        select(SnapshotCandidato).where(SnapshotCandidato.snapshot_id == snap.id)
        .order_by(SnapshotCandidato.posicao)
    )).scalars().all()
    return snap, tot, cands


async def _nome_partido(sess, sq: str) -> tuple[str, str]:
    """Retorna (nome_urna, sigla_partido) já escapados pra Markdown."""
    c = await sess.get(Candidato, sq)
    if not c:
        return _md_escape(sq), ""
    sigla = ""
    if c.partido_numero:
        p = await sess.get(Partido, c.partido_numero)
        sigla = p.sigla if p else ""
    return _md_escape(c.nome_urna or c.nome), _md_escape(sigla)


def _barra(pct: float, largura: int = 12) -> str:
    """Barra visual em blocos unicode pro placar."""
    n = max(0, min(largura, round(pct / 100 * largura)))
    return "█" * n + "░" * (largura - n)


# ================== comandos de consulta ==================

async def cmd_pct(client, chat_id: int, args: list[str]) -> None:
    cargo, uf = _parse_cargo_uf(args)
    async with SessionLocal() as sess:
        res = await _snapshot_atual(sess, cargo, uf)
    if not res:
        await _send(client, chat_id,
                    f"Sem dados de {CARGOS[cargo]}/{uf} ainda. Apuração começa 5/10 17h BRT.")
        return
    snap, tot, _ = res
    pct = (tot.qt_secoes_totalizadas / tot.qt_secoes_total * 100) if tot.qt_secoes_total else 0
    await _send(client, chat_id,
        f"📊 *{CARGOS[cargo]} · {uf}*\n"
        f"Apurado: *{pct:.2f}%* ({tot.qt_secoes_totalizadas:,} / {tot.qt_secoes_total:,} seções)\n"
        f"{_barra(pct, 16)}\n"
        f"_Atualizado {snap.coletado_em.astimezone(BRT).strftime('%H:%M:%S')} BRT_"
        .replace(",", "."))


async def cmd_placar(client, chat_id: int, args: list[str]) -> None:
    cargo, uf = _parse_cargo_uf(args)
    async with SessionLocal() as sess:
        res = await _snapshot_atual(sess, cargo, uf)
        if not res:
            await _send(client, chat_id, f"Sem dados de {CARGOS[cargo]}/{uf} ainda.")
            return
        snap, tot, cands = res
        pct_ap = (tot.qt_secoes_totalizadas / tot.qt_secoes_total * 100) if tot.qt_secoes_total else 0
        linhas = [f"📊 *{CARGOS[cargo]} · {uf}* — {pct_ap:.1f}% apurado\n"]
        for c in cands[:8]:
            nome, sigla = await _nome_partido(sess, c.sq_candidato)
            marca = ["🥇","🥈","🥉","4️⃣","5️⃣","6️⃣","7️⃣","8️⃣"][min(c.posicao-1, 7)]
            linhas.append(
                f"{marca} *{nome}* ({sigla}) — {float(c.pct_validos):.2f}%\n"
                f"    `{_barra(float(c.pct_validos))}` {c.votos:,}".replace(",", "."))
    linhas.append(f"\n_Atualizado {snap.coletado_em.astimezone(BRT).strftime('%H:%M:%S')} BRT_")
    await _send(client, chat_id, "\n".join(linhas))


async def cmd_lider(client, chat_id: int, args: list[str]) -> None:
    cargo, uf = _parse_cargo_uf(args)
    async with SessionLocal() as sess:
        res = await _snapshot_atual(sess, cargo, uf)
        if not res:
            await _send(client, chat_id, f"Sem dados de {CARGOS[cargo]}/{uf} ainda.")
            return
        snap, tot, cands = res
        if not cands:
            await _send(client, chat_id, "Sem candidatos no snapshot.")
            return
        a = cands[0]
        nome_a, sig_a = await _nome_partido(sess, a.sq_candidato)
        texto = (f"👑 *Líder — {CARGOS[cargo]} · {uf}*\n\n"
                 f"*{nome_a}* ({sig_a})\n"
                 f"{a.votos:,} votos · {float(a.pct_validos):.2f}% dos válidos".replace(",", "."))
        if len(cands) >= 2:
            b = cands[1]
            nome_b, sig_b = await _nome_partido(sess, b.sq_candidato)
            diff = a.votos - b.votos
            texto += (f"\n\n2º: *{nome_b}* ({sig_b}) · {float(b.pct_validos):.2f}%\n"
                      f"Margem: {diff:,} votos ({float(a.pct_validos) - float(b.pct_validos):.2f} p.p.)"
                      .replace(",", "."))
    await _send(client, chat_id, texto)


async def cmd_candidato(client, chat_id: int, args: list[str]) -> None:
    if not args:
        await _send(client, chat_id, "Uso: /candidato <número> [uf]\nEx.: /candidato 22 SP")
        return
    numero = args[0]
    uf = args[1].upper() if len(args) > 1 and args[1].upper() in UFS else "BR"
    if not numero.isdigit():
        await _send(client, chat_id, "Número inválido.")
        return
    async with SessionLocal() as sess:
        q = select(Candidato).where(Candidato.numero == int(numero))
        if uf != "BR":
            q = q.where(Candidato.uf == uf)
        else:
            q = q.where(Candidato.cod_cargo == 1)  # presidente é BR
        r = await sess.execute(q)
        cs = r.scalars().all()
    if not cs:
        await _send(client, chat_id,
                    f"Não achei candidato número {numero} em {uf}.")
        return
    partes = []
    for c in cs[:5]:
        raw = c.raw_divulga or {}
        p = raw.get("partido") or {}
        situacao = raw.get("descricaoSituacao") or "?"
        ocupacao = raw.get("ocupacao") or "?"
        nasc = raw.get("dataDeNascimento") or "?"
        partes.append(
            f"*{_md_escape(c.nome_urna)}* ({_md_escape(p.get('sigla', '?'))}, {c.numero})\n"
            f"{CARGOS.get(c.cod_cargo, c.cod_cargo)} · {c.uf or 'BR'}\n"
            f"Nome: {_md_escape(c.nome)}\n"
            f"Ocupação: {_md_escape(ocupacao)}\nNasc.: {nasc}\nSituação: {_md_escape(situacao)}"
        )
    await _send(client, chat_id, "\n\n———\n\n".join(partes))


async def cmd_vs(client, chat_id: int, args: list[str]) -> None:
    if len(args) < 2:
        await _send(client, chat_id, "Uso: /vs <n1> <n2> [uf]\nEx.: /vs 13 22 BR")
        return
    if not args[0].isdigit() or not args[1].isdigit():
        await _send(client, chat_id, "Números inválidos.")
        return
    n1, n2 = int(args[0]), int(args[1])
    uf = args[2].upper() if len(args) > 2 and args[2].upper() in UFS else "BR"
    async with SessionLocal() as sess:
        q = select(Candidato).where(Candidato.numero.in_([n1, n2]))
        if uf != "BR":
            q = q.where(Candidato.uf == uf)
        cs = (await sess.execute(q)).scalars().all()
        if len(cs) < 2:
            await _send(client, chat_id, "Não achei os dois candidatos.")
            return
        # Pega snapshot atual do cargo dos candidatos
        cargo = cs[0].cod_cargo
        abr = uf
        res = await _snapshot_atual(sess, cargo, abr)
        placar = {}
        if res:
            _, _, sc = res
            placar = {c.sq_candidato: c for c in sc}
        linhas = [f"⚔ *Comparação — {CARGOS.get(cargo)} · {uf}*\n"]
        for c in cs[:2]:
            _, sig = await _nome_partido(sess, c.sq_candidato)
            sc = placar.get(c.sq_candidato)
            nome_esc = _md_escape(c.nome_urna)
            if sc:
                linhas.append(
                    f"*{nome_esc}* ({sig}, {c.numero})\n"
                    f"  {sc.votos:,} votos · {float(sc.pct_validos):.2f}%\n"
                    f"  `{_barra(float(sc.pct_validos))}`".replace(",", "."))
            else:
                linhas.append(f"*{nome_esc}* ({sig}, {c.numero}) — sem dados")
        if len(cs) >= 2 and all(c.sq_candidato in placar for c in cs[:2]):
            a = placar[cs[0].sq_candidato]; b = placar[cs[1].sq_candidato]
            diff = a.votos - b.votos
            lider = cs[0] if diff > 0 else cs[1]
            linhas.append(f"\n👑 Lidera: *{lider.nome_urna}* por {abs(diff):,} votos"
                          .replace(",", "."))
    await _send(client, chat_id, "\n".join(linhas))


async def cmd_mapa(client, chat_id: int, args: list[str]) -> None:
    cargo, _ = _parse_cargo_uf(args, default_cargo=1)
    async with SessionLocal() as sess:
        linhas = [f"🗺 *Líderes por UF — {CARGOS.get(cargo)}*\n"]
        contas: dict[str, int] = {}  # sigla → n_ufs
        for uf in (["BR"] if cargo == 1 else UFS):
            res = await _snapshot_atual(sess, cargo, uf if cargo != 1 else "BR")
            if not res:
                continue
            snap, tot, cands = res
            if not cands:
                continue
            top = cands[0]
            nome, sig = await _nome_partido(sess, top.sq_candidato)
            contas[sig] = contas.get(sig, 0) + 1
            linhas.append(f"`{uf}` {nome} ({sig}) · {float(top.pct_validos):.1f}%")
        if len(linhas) <= 1:
            linhas.append("Sem dados ainda.")
        elif contas:
            resumo = " · ".join(f"{s}: {n}" for s, n in sorted(contas.items(), key=lambda x: -x[1]))
            linhas.append(f"\n_Contagem: {resumo}_")
    await _send(client, chat_id, "\n".join(linhas))


async def cmd_proporcional(client, chat_id: int, args: list[str], cargo: int = 6) -> None:
    if not args or args[0].upper() not in UFS:
        await _send(client, chat_id, f"Uso: /{'proporcional' if cargo==6 else 'estadual'} <uf>")
        return
    uf = args[0].upper()
    try:
        from math_engine.proporcional import calcular_apuracao_proporcional
    except Exception:
        await _send(client, chat_id, "Motor proporcional indisponível.")
        return
    async with SessionLocal() as sess:
        res = await _snapshot_atual(sess, cargo, uf)
        if not res:
            await _send(client, chat_id, f"Sem dados de {CARGOS[cargo]} · {uf}.")
            return
        snap, tot, cands = res
        # Precisa da relação candidato → partido
        sqs = [c.sq_candidato for c in cands]
        rows = (await sess.execute(
            select(Candidato.sq_candidato, Candidato.partido_numero)
            .where(Candidato.sq_candidato.in_(sqs))
        )).all()
        mapa_part = {sq: pn for sq, pn in rows}
        entrada = [{"sq_candidato": c.sq_candidato, "votos": c.votos,
                    "partido_numero": mapa_part.get(c.sq_candidato, 0)} for c in cands]
        try:
            r = calcular_apuracao_proporcional(entrada, cargo, uf, tot.qt_votos_validos)
        except Exception:
            log.exception("proporcional falhou")
            await _send(client, chat_id, "Falha ao calcular proporcional.")
            return
        eleitos = [c for c in r["candidatos"] if c["status"] == "eleito"][:20]
        linhas = [f"🪑 *{CARGOS[cargo]} · {uf}* — {r['vagas']} vagas",
                  f"Quociente Eleitoral: `{r['quociente_eleitoral']:,}`".replace(",", "."), ""]
        if eleitos:
            for e in eleitos:
                nome, sig = await _nome_partido(sess, e["sq_candidato"])
                linhas.append(f"✅ {nome} ({sig}) — {e['votos']:,}".replace(",", "."))
        else:
            linhas.append("_Nenhum eleito ainda._")
    await _send(client, chat_id, "\n".join(linhas))


async def cmd_eventos(client, chat_id: int, args: list[str]) -> None:
    cargo, uf = _parse_cargo_uf(args, default_cargo=0)
    async with SessionLocal() as sess:
        q = select(Evento).order_by(desc(Evento.ocorrido_em)).limit(15)
        if cargo:
            q = q.where(Evento.cod_cargo == cargo)
        if uf != "BR":
            q = q.where(Evento.abrangencia == uf)
        r = await sess.execute(q)
        evs = r.scalars().all()
        if not evs:
            await _send(client, chat_id, "Sem eventos matemáticos ainda.")
            return
        linhas = ["🕐 *Últimos eventos matemáticos:*\n"]
        for e in evs:
            hora = e.ocorrido_em.astimezone(BRT).strftime("%H:%M")
            nome, sig = await _nome_partido(sess, e.sq_candidato_a)
            emo = EMOJI_TIPO.get(e.tipo, "🔔")
            onde = f"{CARGOS.get(e.cod_cargo, '?')}·{e.abrangencia}"
            linhas.append(f"`{hora}` {emo} *{nome}* ({sig}) — {onde}")
    await _send(client, chat_id, "\n".join(linhas))


async def cmd_status(client, chat_id: int) -> None:
    async with SessionLocal() as sess:
        r = await sess.execute(
            select(Snapshot).order_by(desc(Snapshot.coletado_em)).limit(1)
        )
        snap = r.scalar_one_or_none()
        if not snap:
            await _send(client, chat_id, "Ainda não há snapshots. Aguardando TSE.")
            return
        n = (await sess.execute(
            select(func.count(Snapshot.id))
        )).scalar_one()
        ne = (await sess.execute(
            select(func.count(Evento.id))
        )).scalar_one()
    await _send(client, chat_id,
        f"🔍 *Status da apuração*\n\n"
        f"Snapshots coletados: *{n:,}*\n".replace(",", ".") +
        f"Eventos matemáticos: *{ne}*\n"
        f"Último snapshot: {snap.coletado_em.astimezone(BRT).strftime('%d/%m %H:%M:%S')} BRT\n\n"
        f"*Hash do snapshot:*\n`{snap.hash_conteudo[:32]}…`\n"
        f"_Verifique contra o JSON original do TSE em resultados.tse.jus.br_")


async def cmd_cola(client, chat_id: int, args: list[str]) -> None:
    if not args or not args[0].isdigit():
        await _send(client, chat_id, "Uso: /cola <número> [uf]")
        return
    numero = int(args[0])
    uf = args[1].upper() if len(args) > 1 and args[1].upper() in UFS else "BR"
    async with SessionLocal() as sess:
        q = select(Candidato).where(Candidato.numero == numero)
        if uf != "BR":
            q = q.where(Candidato.uf == uf)
        c = (await sess.execute(q)).scalars().first()
    if not c:
        await _send(client, chat_id, "Não achei esse candidato.")
        return
    settings = get_settings()
    foto = (f"https://divulgacandcontas.tse.jus.br/divulga/rest/arquivo/img/"
            f"{settings.eleicao_cod_divulga}/{c.sq_candidato}/{c.uf or 'BR'}")
    await _send(client, chat_id,
                f"🗳 *{_md_escape(c.nome_urna)}* — {c.numero}\n_{_md_escape(c.nome)}_",
                foto=foto)


# ================== assinatura ==================

async def _tratar_assinar_start(client, chat_id: int, msg_id: int | None = None) -> None:
    est = _ESTADOS.setdefault(chat_id, {"tipos": [], "cargo": None, "uf": None})
    est.clear(); est.update({"tipos": [], "cargo": None, "uf": None})
    kb = _kb_escolher_cargo("subc")
    if msg_id:
        await _api(client, "editMessageText", chat_id=chat_id, message_id=msg_id,
                   text="🔔 *Nova assinatura* — escolha o cargo:",
                   parse_mode="Markdown", reply_markup=kb)
    else:
        await _send(client, chat_id, "🔔 *Nova assinatura* — escolha o cargo:", keyboard=kb)


async def _listar_assinaturas(client, chat_id: int, msg_id: int | None = None) -> None:
    async with SessionLocal() as sess:
        r = await sess.execute(
            select(TelegramSubscription).where(TelegramSubscription.chat_id == chat_id)
            .order_by(TelegramSubscription.cod_cargo, TelegramSubscription.abrangencia)
        )
        subs = r.scalars().all()
    if not subs:
        texto = "Você ainda não tem assinaturas.\nUse /assinar ou o botão do menu."
        kb = _kb_principal()
    else:
        linhas = ["📋 *Suas assinaturas:*\n"]
        kb_rows = []
        for s in subs:
            rot = f"{CARGOS.get(s.cod_cargo, s.cod_cargo)} · {s.abrangencia}"
            linhas.append(f"• {rot} — {len(s.tipos_evento or [])} evento(s)")
            kb_rows.append([{"text": f"🗑 {rot}", "callback_data": f"rm:{s.id}"}])
        kb_rows.append([{"text": "‹ Menu", "callback_data": "menu:home"}])
        texto = "\n".join(linhas); kb = {"inline_keyboard": kb_rows}
    if msg_id:
        await _api(client, "editMessageText", chat_id=chat_id, message_id=msg_id,
                   text=texto, parse_mode="Markdown", reply_markup=kb)
    else:
        await _send(client, chat_id, texto, keyboard=kb)


# ================== callbacks ==================

async def _tratar_callback(client, cb: dict) -> None:
    chat_id = cb["message"]["chat"]["id"]
    user_id = cb["from"]["id"]
    msg_id = cb["message"]["message_id"]
    data = cb.get("data", "")
    ack_id = cb["id"]
    ack_done = {"v": False}
    async def ack(text: str | None = None, alert: bool = False) -> None:
        if ack_done["v"]:
            return
        ack_done["v"] = True
        payload = {"callback_query_id": ack_id}
        if text:
            payload["text"] = text
            payload["show_alert"] = alert
        await _api(client, "answerCallbackQuery", **payload)

    # Volta genérica: qualquer callback terminado em "back" volta pra
    # escolha de cargo do mesmo fluxo. Ex.: plcuback → escolher cargo do placar.
    if data.endswith("back"):
        prefix = data[:-4].rstrip(":")
        # sub → sub:cargo | plc → placar cargo | mp → mapa cargo
        base_prefix = {"subu": "subc", "sub": "subc",
                       "plcu": "plc", "plc": "plc",
                       "mpu": "mp", "mp": "mp"}.get(prefix, prefix)
        await ack()
        await _api(client, "editMessageText", chat_id=chat_id, message_id=msg_id,
                   text="Escolha o cargo:", reply_markup=_kb_escolher_cargo(base_prefix))
        return

    if data == "menu:home":
        await ack()
        await _api(client, "editMessageText", chat_id=chat_id, message_id=msg_id,
                   text="🗳 *Menu principal*", parse_mode="Markdown",
                   reply_markup=_kb_principal())
        return
    if data == "menu:placar":
        await ack()
        await _api(client, "editMessageText", chat_id=chat_id, message_id=msg_id,
                   text="Placar de qual cargo?", reply_markup=_kb_escolher_cargo("plc"))
        return
    if data.startswith("plc:"):
        cargo = int(data.split(":")[1])
        await ack()
        if cargo == 1:
            await cmd_placar(client, chat_id, ["1"])
        else:
            await _api(client, "editMessageText", chat_id=chat_id, message_id=msg_id,
                       text=f"{CARGOS[cargo]} — escolha o estado:",
                       reply_markup=_kb_escolher_uf("plcu", cargo))
        return
    if data.startswith("plcu:"):
        _, cargo, uf = data.split(":")
        await ack()
        await cmd_placar(client, chat_id, [cargo, uf])
        return
    if data == "menu:mapa":
        await ack()
        await _api(client, "editMessageText", chat_id=chat_id, message_id=msg_id,
                   text="Mapa de qual cargo?", reply_markup=_kb_escolher_cargo("mp"))
        return
    if data.startswith("mp:"):
        await ack()
        await cmd_mapa(client, chat_id, [data.split(":")[1]])
        return
    if data == "menu:minhas":
        await ack()
        await _listar_assinaturas(client, chat_id, msg_id)
        return
    if data == "menu:config":
        await ack()
        async with SessionLocal() as sess:
            cfg = await sess.get(TelegramChatConfig, chat_id)
        await _api(client, "editMessageText", chat_id=chat_id, message_id=msg_id,
                   text="⚙ *Configurações*", parse_mode="Markdown",
                   reply_markup=_kb_config(cfg))
        return
    # ---- assinatura ----
    if data == "sub:cargo":
        await ack()
        await _tratar_assinar_start(client, chat_id, msg_id)
        return
    if data.startswith("subc:"):
        cod = int(data.split(":")[1])
        await ack()
        est = _ESTADOS.setdefault(chat_id, {"tipos": [], "cargo": None, "uf": None})
        est["cargo"] = cod
        if cod == 1:
            est["uf"] = "BR"
            est["tipos"] = ["ELEITO_1T", "SEGUNDO_TURNO_DEFINIDO", "VIRADA"]
            await _api(client, "editMessageText", chat_id=chat_id, message_id=msg_id,
                       text="Presidente · BR — quais eventos?",
                       reply_markup=_kb_tipos(est["tipos"]))
        else:
            await _api(client, "editMessageText", chat_id=chat_id, message_id=msg_id,
                       text=f"{CARGOS[cod]} — escolha o estado:",
                       reply_markup=_kb_escolher_uf("subu", cod))
        return
    if data.startswith("subu:"):
        _, cargo, uf = data.split(":")
        await ack()
        est = _ESTADOS.setdefault(chat_id, {"tipos": [], "cargo": None, "uf": None})
        est["cargo"] = int(cargo); est["uf"] = uf
        est["tipos"] = ["ELEITO_MAJORITARIO", "VIRADA"]
        await _api(client, "editMessageText", chat_id=chat_id, message_id=msg_id,
                   text=f"{CARGOS[int(cargo)]} · {uf} — quais eventos?",
                   reply_markup=_kb_tipos(est["tipos"]))
        return
    if data.startswith("tipo:"):
        t = data.split(":")[1]
        await ack()
        est = _ESTADOS.setdefault(chat_id, {"tipos": [], "cargo": None, "uf": None})
        if t in est["tipos"]:
            est["tipos"].remove(t)
        else:
            est["tipos"].append(t)
        await _api(client, "editMessageReplyMarkup", chat_id=chat_id, message_id=msg_id,
                   reply_markup=_kb_tipos(est["tipos"]))
        return
    if data == "sub:salvar":
        est = _ESTADOS.get(chat_id) or {}
        if not est.get("cargo") or not est.get("uf") or not est.get("tipos"):
            await ack("Falta escolher cargo/UF/evento", alert=True)
            return
        await ack()
        async with SessionLocal() as sess:
            stmt = pg_insert(TelegramSubscription).values(
                criado_em=datetime.now(timezone.utc),
                chat_id=chat_id, cod_cargo=est["cargo"],
                abrangencia=est["uf"], tipos_evento=est["tipos"],
            ).on_conflict_do_update(
                index_elements=["chat_id", "cod_cargo", "abrangencia"],
                set_={"tipos_evento": est["tipos"]},
            )
            await sess.execute(stmt); await sess.commit()
        rot = f"{CARGOS[est['cargo']]} · {est['uf']}"
        await _api(client, "editMessageText", chat_id=chat_id, message_id=msg_id,
                   text=f"✅ Salvo: *{rot}* ({len(est['tipos'])} evento(s))",
                   parse_mode="Markdown", reply_markup=_kb_principal())
        _ESTADOS.pop(chat_id, None)
        return
    if data.startswith("rm:"):
        sub_id = int(data.split(":")[1])
        await ack()
        async with SessionLocal() as sess:
            await sess.execute(
                delete(TelegramSubscription).where(and_(
                    TelegramSubscription.id == sub_id,
                    TelegramSubscription.chat_id == chat_id))
            )
            await sess.commit()
        await _listar_assinaturas(client, chat_id, msg_id)
        return
    # ---- config ----
    if data == "cfg:toggle_pausa":
        await ack()
        async with SessionLocal() as sess:
            cfg = await sess.get(TelegramChatConfig, chat_id)
            if not cfg:
                cfg = TelegramChatConfig(chat_id=chat_id, pausado_global=True,
                                          criado_em=datetime.now(timezone.utc))
                sess.add(cfg)
            else:
                cfg.pausado_global = not cfg.pausado_global
            await sess.commit(); await sess.refresh(cfg)
        await _api(client, "editMessageText", chat_id=chat_id, message_id=msg_id,
                   text="⚙ *Configurações*", parse_mode="Markdown",
                   reply_markup=_kb_config(cfg))
        return
    if data == "cfg:silencio":
        await ack()
        await _send(client, chat_id,
            "Envie a janela de silêncio no formato *HH-HH* (BRT).\n"
            "Ex.: `/silencio 00-07` (não envia entre 00h e 07h)\n"
            "Ou: `/silencio off` pra desligar.")
        return
    if data == "cfg:apagar_tudo":
        await ack()
        async with SessionLocal() as sess:
            await sess.execute(
                delete(TelegramSubscription).where(TelegramSubscription.chat_id == chat_id)
            )
            await sess.commit()
        await _api(client, "editMessageText", chat_id=chat_id, message_id=msg_id,
                   text="🗑 Todas as suas assinaturas foram removidas.",
                   reply_markup=_kb_principal())
        return


# ================== dispatcher de mensagens ==================

async def _tratar_mensagem(client, msg: dict) -> None:
    chat_id = msg["chat"]["id"]
    text = (msg.get("text") or "").strip()
    if not text:
        return
    # Comando: /cmd arg1 arg2  (aceita @botname sufixado)
    partes = text.split()
    cmd = partes[0].lower().split("@")[0]
    args = partes[1:]
    if cmd in ("/start", "/menu"):
        await _send(client, chat_id,
            f"🗳 *Apuração 2026 · Brasil*\n\n"
            f"Consulte a apuração ao vivo e receba alertas quando "
            f"um candidato é matematicamente eleito.\n\n"
            f"Digite /help pra ver todos os comandos ou use o menu:",
            keyboard=_kb_principal())
    elif cmd == "/help":
        await _send(client, chat_id,
            "*Consulta ao vivo:*\n"
            "/pct — % apurado\n"
            "/placar — top 8 candidatos\n"
            "/lider — quem lidera + margem\n"
            "/candidato <nº> [uf] — ficha completa\n"
            "/vs <n1> <n2> [uf] — comparar dois\n"
            "/mapa [cargo] — líder por UF\n"
            "/proporcional <uf> — dep. federal\n"
            "/estadual <uf> — dep. estadual\n"
            "/eventos — últimos eventos matemáticos\n"
            "/status — totais + hash (verificável)\n"
            "/cola <nº> [uf] — foto do candidato\n\n"
            "*Alertas:*\n"
            "/assinar — nova assinatura (guiado)\n"
            "/minhas — suas assinaturas\n"
            "/pausar · /retomar — pausa/retoma tudo\n"
            "/silencio HH-HH — janela sem alertas\n"
            "/apagar_tudo — remove todas\n\n"
            "*Info:*\n"
            "/tse — apuração oficial")
    elif cmd == "/pct":            await cmd_pct(client, chat_id, args)
    elif cmd == "/placar":         await cmd_placar(client, chat_id, args)
    elif cmd == "/lider":          await cmd_lider(client, chat_id, args)
    elif cmd == "/candidato":      await cmd_candidato(client, chat_id, args)
    elif cmd == "/vs":             await cmd_vs(client, chat_id, args)
    elif cmd == "/mapa":           await cmd_mapa(client, chat_id, args)
    elif cmd == "/proporcional":   await cmd_proporcional(client, chat_id, args, 6)
    elif cmd == "/estadual":       await cmd_proporcional(client, chat_id, args, 7)
    elif cmd == "/eventos":        await cmd_eventos(client, chat_id, args)
    elif cmd == "/status":         await cmd_status(client, chat_id)
    elif cmd == "/cola":           await cmd_cola(client, chat_id, args)
    elif cmd == "/tse":
        await _send(client, chat_id,
            "🏛 *Apuração oficial do TSE:*\nhttps://resultados.tse.jus.br",
            keyboard={"inline_keyboard": [[{"text": "Abrir TSE", "url": "https://resultados.tse.jus.br"}]]})
    elif cmd in ("/sobre", "/faq", "/termos", "/privacidade"):
        pag = {"/faq": "faq", "/termos": "termos",
               "/privacidade": "privacidade"}.get(cmd, "")
        url = f"{SITE_URL}/sobre" + (f"#{pag}" if pag else "")
        await _send(client, chat_id,
            "📖 *Sobre este site*\n\n"
            "Site independente, *não é o TSE*. Fonte oficial: "
            "resultados.tse.jus.br.\n\n"
            "Não coletamos dados pessoais além do necessário. "
            "Ver FAQ, termos, privacidade e metodologia completa:",
            keyboard={"inline_keyboard": [
                [{"text": "📖 Ler página completa", "url": url}],
                [{"text": "🏛 TSE oficial", "url": "https://resultados.tse.jus.br"}],
            ]})
    elif cmd == "/assinar":        await _tratar_assinar_start(client, chat_id)
    elif cmd == "/minhas":         await _listar_assinaturas(client, chat_id)
    elif cmd in ("/pausar", "/retomar"):
        async with SessionLocal() as sess:
            cfg = await sess.get(TelegramChatConfig, chat_id)
            if not cfg:
                cfg = TelegramChatConfig(chat_id=chat_id,
                                          pausado_global=(cmd == "/pausar"),
                                          criado_em=datetime.now(timezone.utc))
                sess.add(cfg)
            else:
                cfg.pausado_global = (cmd == "/pausar")
            await sess.commit()
        await _send(client, chat_id, "⏸ Alertas pausados." if cmd == "/pausar" else "▶ Alertas retomados.")
    elif cmd == "/silencio":
        if args and args[0].lower() == "off":
            async with SessionLocal() as sess:
                cfg = await sess.get(TelegramChatConfig, chat_id)
                if cfg:
                    cfg.silencio_inicio = None; cfg.silencio_fim = None
                    await sess.commit()
            await _send(client, chat_id, "🌙 Janela de silêncio desligada.")
            return
        if not args:
            await _send(client, chat_id, "Uso: /silencio HH-HH (BRT). Ex.: /silencio 00-07\nOu: /silencio off")
            return
        r = _parse_hora_intervalo(args[0])
        if not r:
            await _send(client, chat_id, "Formato inválido. Ex.: /silencio 00-07")
            return
        ini, fim = r
        async with SessionLocal() as sess:
            cfg = await sess.get(TelegramChatConfig, chat_id)
            if not cfg:
                cfg = TelegramChatConfig(chat_id=chat_id, silencio_inicio=ini,
                                          silencio_fim=fim,
                                          criado_em=datetime.now(timezone.utc))
                sess.add(cfg)
            else:
                cfg.silencio_inicio = ini; cfg.silencio_fim = fim
            await sess.commit()
        await _send(client, chat_id, f"🌙 Silêncio: {ini:02d}h → {fim:02d}h BRT")
    elif cmd == "/apagar_tudo":
        async with SessionLocal() as sess:
            await sess.execute(
                delete(TelegramSubscription).where(TelegramSubscription.chat_id == chat_id)
            )
            await sess.commit()
        await _send(client, chat_id, "🗑 Todas as suas assinaturas foram removidas.")
    else:
        await _send(client, chat_id,
            "Não entendi. Digite /help pra ver os comandos ou /start pro menu.")


async def _processar_update(client, upd: dict) -> None:
    if "callback_query" in upd:
        cb = upd["callback_query"]
        try:
            await _tratar_callback(client, cb)
        except Exception:
            log.exception("callback falhou")
        # Garante que o botão sempre pare de girar (se algum branch esqueceu)
        try:
            await _api(client, "answerCallbackQuery", callback_query_id=cb["id"])
        except Exception:
            pass
        return
    msg = upd.get("message")
    if msg:
        try:
            await _tratar_mensagem(client, msg)
        except Exception:
            log.exception("mensagem falhou")


# ================== loop principal ==================

async def loop_bot() -> None:
    base = _api_base()
    if not base:
        log.info("telegram bot desabilitado (sem TELEGRAM_BOT_TOKEN)")
        return
    log.info("telegram bot iniciado")
    offset = 0
    async with httpx.AsyncClient() as client:
        try:
            await _api(client, "setMyCommands", commands=[
                {"command": "start", "description": "Menu principal"},
                {"command": "placar", "description": "Placar ao vivo"},
                {"command": "lider", "description": "Quem lidera agora"},
                {"command": "pct", "description": "% apurado"},
                {"command": "candidato", "description": "Ficha por número"},
                {"command": "vs", "description": "Comparar dois candidatos"},
                {"command": "mapa", "description": "Líder por UF"},
                {"command": "eventos", "description": "Eventos matemáticos"},
                {"command": "status", "description": "Totais + hash"},
                {"command": "assinar", "description": "Nova assinatura"},
                {"command": "minhas", "description": "Minhas assinaturas"},
                {"command": "help", "description": "Todos os comandos"},
            ])
        except Exception:
            pass
        while True:
            try:
                r = await client.get(f"{base}/getUpdates",
                                     params={"offset": offset, "timeout": 30},
                                     timeout=40.0)
                j = r.json()
                for upd in j.get("result", []):
                    offset = upd["update_id"] + 1
                    await _processar_update(client, upd)
            except (asyncio.CancelledError, KeyboardInterrupt):
                raise
            except Exception:
                log.exception("telegram poll falhou")
                await asyncio.sleep(5)


# ================== envio de alertas ==================

def _em_silencio(cfg: TelegramChatConfig | None) -> bool:
    if not cfg or cfg.silencio_inicio is None or cfg.silencio_fim is None:
        return False
    h = datetime.now(BRT).hour
    ini, fim = cfg.silencio_inicio, cfg.silencio_fim
    if ini <= fim:
        return ini <= h < fim
    # janela que atravessa meia-noite (ex.: 22-07)
    return h >= ini or h < fim


async def _formatar_mensagem(sess, ev: dict, cargo: int, uf: str) -> str:
    tipo = ev["tipo"]
    a = ev.get("sq_candidato_a"); b = ev.get("sq_candidato_b")
    emo = EMOJI_TIPO.get(tipo, "🔔")
    titulo = TIPOS.get(tipo, tipo).lstrip("🎉🏆⚡🔄❌ ")
    onde = f"{CARGOS.get(cargo, cargo)} · {uf}"
    async def _fmt(sq: str) -> str:
        if not sq: return ""
        nome, sig = await _nome_partido(sess, sq)
        return f"*{nome}* ({sig})"
    corpo = f"{emo} *{titulo}*\n{onde}\n\n"
    fa = await _fmt(a)
    fb = await _fmt(b) if b else ""
    if tipo == "VIRADA":
        corpo += f"{fa} passou {fb}"
    elif tipo == "SEGUNDO_TURNO_DEFINIDO":
        corpo += f"Vão pro 2º turno: {fa} × {fb}"
    else:
        corpo += fa
    corpo += f"\n\n🔗 {SITE_URL}"
    return corpo


async def enviar_notificacoes(eventos: list[dict], cargo: int, uf: str) -> None:
    if not eventos or not _api_base():
        return
    async with SessionLocal() as sess:
        q = select(TelegramSubscription).where(and_(
            TelegramSubscription.cod_cargo == cargo,
            TelegramSubscription.abrangencia == uf,
        ))
        subs = (await sess.execute(q)).scalars().all()
        if not subs:
            return
        chats = {s.chat_id for s in subs}
        cfgs = (await sess.execute(
            select(TelegramChatConfig).where(TelegramChatConfig.chat_id.in_(chats))
        )).scalars().all()
        cfg_map = {c.chat_id: c for c in cfgs}
        # Pré-formata mensagens (uma vez cada tipo)
        mensagens: dict[str, str] = {}
        for ev in eventos:
            if ev["tipo"] not in mensagens:
                mensagens[ev["tipo"]] = await _formatar_mensagem(sess, ev, cargo, uf)
    # Bot API do Telegram tem limite de 30 msgs/s pra bots. Enviar
    # serial pra 1000+ chats travaria o poller por dezenas de segundos.
    # Paralelismo com semáforo controla concorrência sem estourar rate.
    sem = asyncio.Semaphore(20)  # 20 concorrentes → ~30 msg/s comfortavelmente

    async def _enviar_um(client, chat_id: int, texto: str) -> None:
        async with sem:
            try:
                await _api(client, "sendMessage",
                           chat_id=chat_id, text=texto,
                           parse_mode="Markdown",
                           disable_web_page_preview=True)
            except Exception:
                log.exception("envio telegram chat=%s falhou", chat_id)

    async with httpx.AsyncClient() as client:
        for ev in eventos:
            texto = mensagens[ev["tipo"]]
            tarefas = []
            for s in subs:
                if ev["tipo"] not in (s.tipos_evento or []):
                    continue
                cfg = cfg_map.get(s.chat_id)
                if cfg and cfg.pausado_global:
                    continue
                if _em_silencio(cfg):
                    continue
                tarefas.append(_enviar_um(client, s.chat_id, texto))
            if tarefas:
                await asyncio.gather(*tarefas, return_exceptions=True)
