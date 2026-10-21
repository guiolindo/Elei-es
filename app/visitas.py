"""Analytics minimalista — LGPD-safe.

Loga uma linha em `visitas` por request de PÁGINA (html), não pra cada
GET de /api/* ou /static/*. IP vai sempre como SHA-256(ip + salt),
irreversível — serve só pra contar únicos. Nada de PII armazenado.

Dedup: fire-and-forget pra não bloquear a resposta. Buffer in-memory
descarta se o DB engasgar (analytics nunca derruba o site).
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import insert

from app.db import SessionLocal
from app.models import Visita

log = logging.getLogger(__name__)

# Salt pra hash de IP. Setar via env em prod — padrão vazio só pra dev.
# Se mudar o salt, perde a continuidade da contagem de únicos (desejado
# a cada rotação de privacidade).
_SALT = os.environ.get("VISITAS_SALT", "elei-es-dev-salt")

# Paths que CONTAM como visita (páginas HTML servidas). Tudo que não bate
# aqui (api, static, health, favicon) é ignorado pra não poluir.
_PATHS_CONTAM = re.compile(r"^/(sobre|urna|verificacao|cola)?$")

# User-agent → família simplificada. Ordem importa (bots primeiro).
_UA_PATTERNS = [
    (re.compile(r"(bot|crawler|spider|slurp|facebookexternalhit|preview)", re.I), "bot", True),
    # Ferramentas, não navegadores (conferências de deploy, scripts, testes
    # automatizados): não são visitantes.
    (re.compile(r"(curl|wget|python|httpx|aiohttp|go-http|java/|okhttp|libwww|headless|uptime|monitor)", re.I), "ferramenta", True),
    # Pré-visualização de link (WhatsApp, Skype, Iframely etc.): o app abre a
    # página para montar título e imagem quando alguém compartilha o link.
    # O WhatsApp manda só "WhatsApp/2.x"; o navegador embutido de outros apps
    # traz "Mozilla/..." e continua contando como visita.
    (re.compile(r"^WhatsApp/|SkypeUriPreview|Iframely|Embedly|vkShare|redditbot|Snapchat|Pinterest", re.I), "previa-link", True),
    (re.compile(r"Edg/", re.I),       "Edge",    False),
    (re.compile(r"OPR/|Opera", re.I), "Opera",   False),
    (re.compile(r"Firefox/", re.I),   "Firefox", False),
    (re.compile(r"Chrome/", re.I),    "Chrome",  False),
    (re.compile(r"Safari/", re.I),    "Safari",  False),
]


def _classificar_ua(ua: str) -> tuple[str, bool]:
    if not ua:
        return ("ferramenta", True)  # navegador de verdade sempre manda user-agent
    for pat, nome, is_bot in _UA_PATTERNS:
        if pat.search(ua):
            return (nome, is_bot)
    return ("outro", False)


def _hash_ip(ip: str) -> str:
    return hashlib.sha256((ip + _SALT).encode("utf-8")).hexdigest()


def deve_logar(path: str) -> bool:
    """True pra páginas HTML que a gente serve (não API/static/health)."""
    return bool(_PATHS_CONTAM.match(path))


async def registrar(path: str, ip: str, referrer: str | None, user_agent: str | None) -> None:
    """Insere uma linha em `visitas`. Chamar fire-and-forget via
    `asyncio.create_task(registrar(...))` pra não bloquear a resposta."""
    try:
        ua_familia, is_bot = _classificar_ua(user_agent or "")
        async with SessionLocal() as sess:
            await sess.execute(insert(Visita).values(
                ocorreu_em=datetime.now(timezone.utc),
                path=path[:256],
                ip_hash=_hash_ip(ip),
                referrer=(referrer[:256] if referrer else None),
                ua_familia=ua_familia,
                is_bot=is_bot,
            ))
            await sess.commit()
    except Exception as exc:  # analytics NUNCA derruba o site
        log.debug("falhou ao registrar visita: %s", exc)
