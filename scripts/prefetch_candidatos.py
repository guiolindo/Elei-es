"""Baixa e cacheia fotos dos candidatos do TSE em static/candidatos/.

Uso: python -m scripts.prefetch_candidatos
Lê a lista de sq_candidato do banco e busca cada foto uma vez. Se 404,
deixa o fallback (silhueta.svg) atuar.
"""
from __future__ import annotations

import asyncio
import os

import httpx
from sqlalchemy import select

from app.config import get_settings
from app.db import SessionLocal
from app.models import Candidato


async def main() -> None:
    settings = get_settings()
    destino = "static/candidatos"
    os.makedirs(destino, exist_ok=True)
    async with SessionLocal() as sess, httpx.AsyncClient(timeout=15) as client:
        r = await sess.execute(select(Candidato))
        cands = r.scalars().all()
        for c in cands:
            path = f"{destino}/{c.sq_candidato}.jpg"
            if os.path.exists(path):
                continue
            url = f"{settings.tse_fotos_base}/{settings.eleicao_ano}/{c.sq_candidato}"
            try:
                resp = await client.get(url)
                if resp.status_code == 200 and resp.content:
                    with open(path, "wb") as f:
                        f.write(resp.content)
                    print(f"ok {c.sq_candidato}")
                else:
                    print(f"skip {c.sq_candidato}: {resp.status_code}")
            except httpx.HTTPError as e:
                print(f"erro {c.sq_candidato}: {e}")


if __name__ == "__main__":
    asyncio.run(main())
