"""Vigia do coletor: loop travado é reiniciado; travando sempre, encerra o processo."""
import asyncio
from datetime import datetime, timezone

import poller.service as sv


def test_vigia_reinicia_loop_travado_e_desiste_depois_de_3(monkeypatch):
    iniciados = []

    async def loop_travado(broadcaster=None):
        iniciados.append(1)
        sv._poller_info["alvos_total"] = 1
        sv._poller_info["iniciado_em"] = datetime.now(timezone.utc)
        await asyncio.sleep(3600)   # nunca fecha um ciclo

    monkeypatch.setattr(sv, "loop", loop_travado)
    monkeypatch.setitem(sv._poller_info, "reinicios_vigia", 0)
    saiu = []

    async def main():
        await asyncio.wait_for(
            sv.vigia(verificar_a_cada=0.02, limite_s=0.1, sair=lambda: saiu.append(1)), timeout=5)

    asyncio.run(main())
    assert len(iniciados) == 4          # original + 3 reinícios
    assert sv._poller_info["reinicios_vigia"] == 3
    assert saiu == [1]


def test_vigia_nao_mexe_em_loop_saudavel(monkeypatch):
    async def loop_ok(broadcaster=None):
        sv._poller_info["alvos_total"] = 1
        sv._poller_info["iniciado_em"] = datetime.now(timezone.utc)
        while True:
            sv._poller_info["ultimo_ciclo_em"] = datetime.now(timezone.utc)
            await asyncio.sleep(0.02)

    monkeypatch.setattr(sv, "loop", loop_ok)
    monkeypatch.setitem(sv._poller_info, "reinicios_vigia", 0)

    async def main():
        try:
            await asyncio.wait_for(sv.vigia(verificar_a_cada=0.02, limite_s=0.1, sair=lambda: None), timeout=0.6)
        except asyncio.TimeoutError:
            pass

    asyncio.run(main())
    assert sv._poller_info["reinicios_vigia"] == 0
