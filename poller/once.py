"""CLI: python -m poller.once --cargo 1 --abrangencia BR [--turno 1]"""
from __future__ import annotations

import argparse
import asyncio
import logging

import httpx

from poller.service import AlvoColeta, processar_alvo


async def _run(cargo: int, abr: str, turno: int) -> None:
    async with httpx.AsyncClient() as client:
        await processar_alvo(client, AlvoColeta(turno, cargo, abr))


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    p = argparse.ArgumentParser()
    p.add_argument("--cargo", type=int, required=True)
    p.add_argument("--abrangencia", default="BR")
    p.add_argument("--turno", type=int, default=1)
    args = p.parse_args()
    asyncio.run(_run(args.cargo, args.abrangencia, args.turno))


if __name__ == "__main__":
    main()
