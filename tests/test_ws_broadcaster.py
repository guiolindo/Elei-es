"""Testes do WebSocket broadcaster — garante que mensagem publicada
pelo poller chega aos clientes conectados ao WS endpoint.

Blind spot que o load_test não cobre: pré-apuração dedup silencia
tudo e o teste de carga não emite nenhum broadcast. Esses testes
simulam snapshot novo diretamente no broadcaster.
"""
from __future__ import annotations

import asyncio
import pytest

from app.ws import Broadcaster


class FakeWS:
    """Fake WebSocket que captura send_json em uma lista pra assertions."""
    def __init__(self, falhar: bool = False, lento: bool = False):
        self.recebidas: list[dict] = []
        self.falhar = falhar
        self.lento = lento
        self.fechado = False

    async def send_json(self, data: dict) -> None:
        if self.falhar:
            raise ConnectionError("socket morto")
        if self.lento:
            await asyncio.sleep(10)  # > SEND_TIMEOUT
        self.recebidas.append(data)


@pytest.mark.asyncio
async def test_broadcaster_envia_pra_cliente_registrado():
    """Mensagem enviada em (cargo, UF) chega ao cliente registrado nessa chave."""
    b = Broadcaster()
    ws = FakeWS()
    await b.register(1, "BR", ws)
    await b.broadcast(1, "BR", {"type": "snapshot", "id": 42})
    assert ws.recebidas == [{"type": "snapshot", "id": 42}]


@pytest.mark.asyncio
async def test_broadcaster_nao_envia_pra_chave_diferente():
    """Cliente registrado em (1, BR) não recebe broadcast de (1, SP)."""
    b = Broadcaster()
    ws_br = FakeWS()
    ws_sp = FakeWS()
    await b.register(1, "BR", ws_br)
    await b.register(1, "SP", ws_sp)
    await b.broadcast(1, "SP", {"type": "snapshot", "id": 99})
    assert ws_br.recebidas == []
    assert ws_sp.recebidas == [{"type": "snapshot", "id": 99}]


@pytest.mark.asyncio
async def test_broadcaster_cargos_separados():
    """Senador e presidente ficam em canais separados."""
    b = Broadcaster()
    ws_pres = FakeWS()
    ws_sen = FakeWS()
    await b.register(1, "BR", ws_pres)
    await b.register(5, "BR", ws_sen)
    await b.broadcast(1, "BR", {"type": "presidente"})
    assert ws_pres.recebidas == [{"type": "presidente"}]
    assert ws_sen.recebidas == []


@pytest.mark.asyncio
async def test_broadcaster_multiplos_clientes_mesma_chave():
    """Vários clientes na mesma (cargo, UF) todos recebem."""
    b = Broadcaster()
    wss = [FakeWS() for _ in range(10)]
    for ws in wss:
        await b.register(1, "BR", ws)
    await b.broadcast(1, "BR", {"type": "snapshot", "n": 42})
    for ws in wss:
        assert ws.recebidas == [{"type": "snapshot", "n": 42}]


@pytest.mark.asyncio
async def test_broadcaster_cliente_falho_e_dropado():
    """Cliente que levanta erro é removido; outros continuam recebendo."""
    b = Broadcaster()
    ws_bom = FakeWS()
    ws_morto = FakeWS(falhar=True)
    await b.register(1, "BR", ws_bom)
    await b.register(1, "BR", ws_morto)
    await b.broadcast(1, "BR", {"type": "ping"})
    # Bom recebeu, morto não
    assert ws_bom.recebidas == [{"type": "ping"}]
    assert ws_morto.recebidas == []
    # Segundo broadcast: morto já foi dropado, só o bom está lá
    await b.broadcast(1, "BR", {"type": "ping2"})
    assert ws_bom.recebidas == [{"type": "ping"}, {"type": "ping2"}]


@pytest.mark.asyncio
async def test_broadcaster_cliente_lento_nao_bloqueia_outros():
    """Cliente lento é dropado após SEND_TIMEOUT; outros não esperam."""
    b = Broadcaster()
    ws_rapido = FakeWS()
    ws_lento = FakeWS(lento=True)
    await b.register(1, "BR", ws_rapido)
    await b.register(1, "BR", ws_lento)
    # Patch SEND_TIMEOUT para o teste rodar rápido
    import app.ws as m
    original_timeout = m.SEND_TIMEOUT
    m.SEND_TIMEOUT = 0.1
    try:
        import time
        t0 = time.monotonic()
        await b.broadcast(1, "BR", {"type": "ping"})
        elapsed = time.monotonic() - t0
        # Deve voltar em ~0.1s (SEND_TIMEOUT), não em 10s (sleep do lento)
        assert elapsed < 1.0, f"broadcast travou {elapsed}s"
        assert ws_rapido.recebidas == [{"type": "ping"}]
    finally:
        m.SEND_TIMEOUT = original_timeout


@pytest.mark.asyncio
async def test_broadcaster_sem_clientes_nao_quebra():
    """Broadcast em chave sem clientes é no-op silencioso."""
    b = Broadcaster()
    await b.broadcast(1, "BR", {"type": "ping"})  # não levanta


@pytest.mark.asyncio
async def test_broadcaster_unregister():
    """unregister para de enviar pra aquele cliente."""
    b = Broadcaster()
    ws = FakeWS()
    await b.register(1, "BR", ws)
    await b.broadcast(1, "BR", {"n": 1})
    await b.unregister(1, "BR", ws)
    await b.broadcast(1, "BR", {"n": 2})
    assert ws.recebidas == [{"n": 1}]


# ============ Teste integrado: poller → broadcaster → WS cliente ============
@pytest.mark.asyncio
async def test_integracao_broadcast_do_poller():
    """Simula fluxo real do dia D:
      1. WS cliente conecta em (cargo=1, abrangencia=BR)
      2. Poller processa um snapshot NOVO (hash diferente do anterior)
      3. Poller chama broadcaster.broadcast()
      4. Cliente DEVE receber a mensagem

    Esse é o fluxo que o load_test NÃO exercita (dedup silencia tudo
    pré-apuração). Se isso quebrar, o site fica sem WS no dia D.
    """
    b = Broadcaster()
    ws = FakeWS()
    await b.register(1, "BR", ws)

    # Simula o payload que o poller envia (poller/service.py linha ~400)
    payload = {
        "type": "snapshot",
        "snapshot_id": 1234,
        "eventos": [{"tipo": "VIRADA", "sq_candidato_a": "X", "sq_candidato_b": "Y"}],
    }
    await b.broadcast(1, "BR", payload)

    assert len(ws.recebidas) == 1
    msg = ws.recebidas[0]
    assert msg["type"] == "snapshot"
    assert msg["snapshot_id"] == 1234
    assert len(msg["eventos"]) == 1
    assert msg["eventos"][0]["tipo"] == "VIRADA"


@pytest.mark.asyncio
async def test_integracao_cargos_e_abrangencias_isolados():
    """No dia D vários broadcasts rodam em paralelo (191 alvos). Cada
    cliente só deve receber do canal certo."""
    b = Broadcaster()
    ws_pres_br = FakeWS()
    ws_gov_sp = FakeWS()
    ws_sen_sp = FakeWS()
    await b.register(1, "BR", ws_pres_br)
    await b.register(3, "SP", ws_gov_sp)
    await b.register(5, "SP", ws_sen_sp)

    # Vários broadcasts quase simultâneos
    await asyncio.gather(
        b.broadcast(1, "BR", {"id": "pres"}),
        b.broadcast(3, "SP", {"id": "gov_sp"}),
        b.broadcast(5, "SP", {"id": "sen_sp"}),
        b.broadcast(3, "RJ", {"id": "gov_rj"}),  # ninguém escuta
    )

    assert ws_pres_br.recebidas == [{"id": "pres"}]
    assert ws_gov_sp.recebidas == [{"id": "gov_sp"}]
    assert ws_sen_sp.recebidas == [{"id": "sen_sp"}]
