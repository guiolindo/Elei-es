"""Rotação automática de proxies para contornar o bloqueio do TSE.

O TSE bloqueia IPs fora do BR via Akamai. Este módulo mantém uma lista
de proxies (residenciais/datacenter BR) e escolhe automaticamente o que
está funcionando.

Fluxo:
  1. Se um proxy está marcado como "vivo" e passou pelo TSE recentemente,
     usa esse.
  2. Se não, testa cada proxy da lista contra o endpoint de sanidade do
     TSE (a home do divulga, que retorna 200 quando OK).
  3. Cacheia o primeiro que passa; se todos falharem, tenta sem proxy.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional

import httpx

log = logging.getLogger(__name__)


# Lista default de proxies BR — testados em 27/09/2026 do Termux (Brasil).
# Free proxies caem/voltam sem aviso; o pool tolera queda e roteia pro
# próximo que estiver vivo. Se todos morrerem, atualize TSE_PROXY_LIST
# com uma lista fresca.
DEFAULT_PROXIES = [
    "http://167.234.251.155:8880",
    "http://18.230.14.91:3128",
    "http://200.229.76.160:3128",
    "http://201.20.42.46:3128",
    "http://138.0.143.119:8080",
    "http://201.157.235.197:8080",
    # extras da mesma lista, caso os 6 primeiros caiam
    "http://186.65.104.52:2024",
    "http://187.72.72.209:5151",
    "http://45.70.52.248:8080",
    "http://186.235.123.3:8080",
    "http://201.20.42.46:3127",
    "http://186.65.106.90:2024",
    "http://170.254.201.46:3180",
    "http://167.250.23.13:9090",
    "http://187.94.220.85:8080",
    "http://201.20.79.182:8088",
    "http://201.62.125.142:8080",
]


# URL leve pra testar se o proxy passa pelo TSE (Akamai).
# A home retorna 200 (HTML) quando o acesso é permitido, 403 quando bloqueado.
SANIDADE_URL = "https://divulgacandcontas.tse.jus.br/divulga/"
SANIDADE_TIMEOUT = 6.0
TTL_VIVO_SEG = 300  # 5 minutos — depois retesta


class ProxyPool:
    def __init__(self, proxies: list[str]):
        self.proxies = [p.strip() for p in proxies if p.strip()]
        self._atual: Optional[str] = None
        self._validado_em: float = 0.0
        self._lock = asyncio.Lock()

    async def _testar(self, proxy: Optional[str]) -> bool:
        """True se o proxy consegue chegar no TSE (200 OK)."""
        cfg = {"timeout": SANIDADE_TIMEOUT}
        if proxy:
            cfg["proxy"] = proxy
        try:
            async with httpx.AsyncClient(**cfg) as c:
                r = await c.get(SANIDADE_URL, headers={"User-Agent": "Mozilla/5.0"})
                return r.status_code == 200
        except Exception:
            return False

    async def escolher(self) -> Optional[str]:
        """Retorna o proxy ativo, revalidando se o cache expirou. None = sem proxy."""
        async with self._lock:
            agora = time.time()
            if self._atual and (agora - self._validado_em) < TTL_VIVO_SEG:
                return self._atual
            # Revalidar o atual primeiro (é o mais provável de ainda funcionar)
            if self._atual and await self._testar(self._atual):
                self._validado_em = agora
                return self._atual
            # Testa todos em paralelo (rápido)
            resultados = await asyncio.gather(*[self._testar(p) for p in self.proxies])
            for p, ok in zip(self.proxies, resultados):
                if ok:
                    self._atual = p
                    self._validado_em = agora
                    log.info("proxy_pool: usando %s", p)
                    return p
            # Nenhum funciona: tenta sem proxy (útil se o app estiver hospedado no BR)
            if await self._testar(None):
                self._atual = None
                self._validado_em = agora
                log.info("proxy_pool: acesso direto OK (sem proxy)")
                return None
            log.warning("proxy_pool: nenhum proxy da lista passou pelo TSE")
            self._atual = None
            self._validado_em = agora
            return None

    def diagnostico(self) -> dict:
        return {
            "total": len(self.proxies),
            "atual": self._atual,
            "validado_ha_seg": int(time.time() - self._validado_em) if self._validado_em else None,
        }


_pool: Optional[ProxyPool] = None


def get_pool() -> ProxyPool:
    global _pool
    if _pool is None:
        from app.config import get_settings
        s = get_settings()
        proxies: list[str] = []
        # Preferência: TSE_PROXY_LIST customizado > TSE_PROXY único > defaults
        if s.tse_proxy_list:
            proxies.extend([p.strip() for p in s.tse_proxy_list.split(",") if p.strip()])
        if s.tse_proxy and s.tse_proxy not in proxies:
            proxies.insert(0, s.tse_proxy)
        # Se nada foi configurado, cai nos defaults (proxies BR conhecidos)
        if not proxies:
            proxies = list(DEFAULT_PROXIES)
            log.info("proxy_pool: usando lista default de %d proxies BR", len(proxies))
        _pool = ProxyPool(proxies)
    return _pool
