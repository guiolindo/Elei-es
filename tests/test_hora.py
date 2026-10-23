import asyncio
import time

from app.api import hora_servidor


def test_hora_do_servidor_em_ms():
    antes = int(time.time() * 1000)
    r = asyncio.run(hora_servidor())
    depois = int(time.time() * 1000)
    assert antes <= r["agora_ms"] <= depois
