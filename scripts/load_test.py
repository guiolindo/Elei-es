"""Teste de carga sintético pro dia D.

Simula o cenário real do dia 4:
- N conexões WebSocket persistentes (usuários no site)
- M requisições/s em /api/apuracao/atual
- K requisições em /api/apuracao/lideres-por-uf (mapa)

Reporta:
- Latência p50/p95/p99 por endpoint
- Falhas por categoria (timeout, 5xx, conexão)
- Thoughput real alcançado

Uso:
    python -m scripts.load_test --url https://elei-es-production.up.railway.app \\
        --ws 100 --rps 50 --duracao 60

Interpretação:
- p95 < 500ms = ótimo
- p95 < 1500ms = aceitável
- p99 > 3000ms = investigar

NÃO rodar contra produção durante apuração real — pode degradar o
serviço pros usuários legítimos. Rodar antes do dia D (ex.: sexta).
"""
from __future__ import annotations

import argparse
import asyncio
import statistics
import time
from collections import defaultdict
from typing import Any

import httpx


class Stats:
    def __init__(self):
        self.latencias: dict[str, list[float]] = defaultdict(list)
        self.falhas: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        self.ok: dict[str, int] = defaultdict(int)
        self.ws_conectados = 0
        self.ws_desconectados = 0
        self.ws_mensagens = 0

    def registrar(self, endpoint: str, ms: float, ok: bool, erro: str | None = None):
        if ok:
            self.latencias[endpoint].append(ms)
            self.ok[endpoint] += 1
        else:
            self.falhas[endpoint][erro or "desconhecido"] += 1

    def relatorio(self) -> str:
        linhas = ["\n╔══════════════════════════════════════════════════╗",
                  "║  Teste de carga — relatório final                 ║",
                  "╚══════════════════════════════════════════════════╝\n"]
        for endpoint in sorted(set(list(self.latencias.keys()) + list(self.falhas.keys()))):
            lats = self.latencias.get(endpoint, [])
            falhas_total = sum(self.falhas.get(endpoint, {}).values())
            linhas.append(f"── {endpoint} ──")
            if lats:
                lats_sorted = sorted(lats)
                p50 = lats_sorted[len(lats_sorted) // 2]
                p95 = lats_sorted[int(len(lats_sorted) * 0.95)]
                p99 = lats_sorted[int(len(lats_sorted) * 0.99)]
                linhas.append(f"  OK: {len(lats):>5}  p50={p50:>6.1f}ms  p95={p95:>6.1f}ms  p99={p99:>6.1f}ms  média={statistics.mean(lats):>6.1f}ms")
            else:
                linhas.append("  Sem requisições bem-sucedidas")
            if falhas_total:
                detalhes = ", ".join(f"{tipo}={n}" for tipo, n in self.falhas[endpoint].items())
                linhas.append(f"  FALHAS: {falhas_total}  ({detalhes})")
            linhas.append("")
        linhas.append("── WebSocket ──")
        linhas.append(f"  Conectados: {self.ws_conectados}  Desconectados: {self.ws_desconectados}  Mensagens recebidas: {self.ws_mensagens}")
        return "\n".join(linhas)


async def worker_rest(client: httpx.AsyncClient, url: str, stats: Stats,
                      rps: float, duracao: float, endpoint: str):
    """Dispara requisições em rate limitado (1 por 1/rps segundos)."""
    deadline = time.monotonic() + duracao
    intervalo = 1.0 / rps if rps > 0 else 0
    while time.monotonic() < deadline:
        t0 = time.monotonic()
        try:
            r = await client.get(url, timeout=10.0)
            ms = (time.monotonic() - t0) * 1000
            if r.status_code < 400:
                stats.registrar(endpoint, ms, True)
            else:
                stats.registrar(endpoint, ms, False, f"HTTP {r.status_code}")
        except httpx.TimeoutException:
            stats.registrar(endpoint, 0, False, "timeout")
        except Exception as e:
            stats.registrar(endpoint, 0, False, type(e).__name__)
        # Rate limit
        elapsed = time.monotonic() - t0
        if intervalo > elapsed:
            await asyncio.sleep(intervalo - elapsed)


async def ws_cliente(url_ws: str, stats: Stats, duracao: float):
    """Conexão WebSocket persistente. Conta mensagens que chega."""
    try:
        import websockets
    except ImportError:
        print("websockets não instalado — pip install websockets")
        return
    try:
        async with websockets.connect(url_ws, ping_interval=20) as ws:
            stats.ws_conectados += 1
            deadline = time.monotonic() + duracao
            while time.monotonic() < deadline:
                try:
                    await asyncio.wait_for(ws.recv(), timeout=duracao - (time.monotonic() - deadline))
                    stats.ws_mensagens += 1
                except asyncio.TimeoutError:
                    break
                except Exception:
                    break
    except Exception:
        pass
    finally:
        stats.ws_desconectados += 1


async def rodar(url_base: str, n_ws: int, rps: int, duracao: int):
    print(f"→ Alvo: {url_base}")
    print(f"→ {n_ws} WebSockets + {rps} req/s em REST por {duracao}s\n")
    stats = Stats()

    endpoints = [
        (f"{url_base}/api/apuracao/atual?cargo=1&abrangencia=BR", "/apuracao/atual (presidente BR)"),
        (f"{url_base}/api/apuracao/atual?cargo=3&abrangencia=SP", "/apuracao/atual (governador SP)"),
        (f"{url_base}/api/apuracao/lideres-por-uf?cargo=1", "/lideres-por-uf (mapa)"),
        (f"{url_base}/api/cargos", "/cargos"),
    ]
    rps_por_endpoint = max(1, rps // len(endpoints))

    tarefas = []
    async with httpx.AsyncClient() as client:
        # WebSockets
        url_ws = url_base.replace("http://", "ws://").replace("https://", "wss://") + "/ws/apuracao?cargo=1&abrangencia=BR"
        for _ in range(n_ws):
            tarefas.append(asyncio.create_task(ws_cliente(url_ws, stats, duracao)))

        # REST workers (um por endpoint)
        for url, nome in endpoints:
            tarefas.append(asyncio.create_task(
                worker_rest(client, url, stats, rps_por_endpoint, duracao, nome)
            ))

        # Progress bar simples
        progress = asyncio.create_task(_progresso(stats, duracao))
        tarefas.append(progress)

        await asyncio.gather(*tarefas, return_exceptions=True)
    print(stats.relatorio())


async def _progresso(stats: Stats, duracao: float):
    deadline = time.monotonic() + duracao
    while time.monotonic() < deadline:
        await asyncio.sleep(5)
        total_ok = sum(stats.ok.values())
        total_falhas = sum(sum(f.values()) for f in stats.falhas.values())
        print(f"  [t+{int(duracao - (deadline - time.monotonic())):>3}s] OK: {total_ok:>5} · Falhas: {total_falhas:>3} · WS msgs: {stats.ws_mensagens}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--url", default="http://localhost:8000",
                   help="URL base (ex: https://elei-es-production.up.railway.app)")
    p.add_argument("--ws", type=int, default=50, help="Nº de conexões WebSocket concorrentes")
    p.add_argument("--rps", type=int, default=20, help="Requisições REST por segundo total")
    p.add_argument("--duracao", type=int, default=60, help="Duração do teste em segundos")
    args = p.parse_args()
    try:
        asyncio.run(rodar(args.url.rstrip("/"), args.ws, args.rps, args.duracao))
    except KeyboardInterrupt:
        print("\n→ interrompido pelo usuário")


if __name__ == "__main__":
    main()
