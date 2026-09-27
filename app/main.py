from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.api import router, ws_router
from app.config import get_settings
from app.ws import broadcaster
from poller.service import loop as poller_loop
from poller.candidatos_tse import sincronizar_candidatos

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
log = logging.getLogger("app")

limiter = Limiter(key_func=get_remote_address, default_limits=["100/minute"])


async def _sync_candidatos_loop():
    """Sincroniza candidatos oficiais do TSE.

    Roda uma vez logo no startup (30s de warmup pra DB e pool estarem
    prontos) e depois a cada 6h. Nas semanas antes da eleição o TSE
    atualiza a lista com frequência (impugnações, substituições); após
    a apuração começar, as mudanças são raras.
    """
    await asyncio.sleep(30)  # warmup
    while True:
        try:
            log.info("sync_candidatos: iniciando ciclo")
            n = await sincronizar_candidatos(baixar_fotos=True)
            log.info("sync_candidatos: %d candidatos atualizados", n)
        except Exception:
            log.exception("sync_candidatos falhou")
        await asyncio.sleep(6 * 3600)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    tasks: list[asyncio.Task] = []
    if not getattr(app.state, "poller_disabled", False):
        tasks.append(asyncio.create_task(poller_loop(broadcaster=broadcaster)))
        tasks.append(asyncio.create_task(_sync_candidatos_loop()))
        log.info("poller + sync candidatos iniciados (intervalo=%ss)", settings.poll_interval_seconds)
    try:
        yield
    finally:
        for t in tasks:
            t.cancel()
        for t in tasks:
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Apuração 2026", lifespan=lifespan)
    app.state.limiter = limiter
    app.add_middleware(SlowAPIMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(RateLimitExceeded)
    async def _rl(request: Request, exc: RateLimitExceeded):
        from starlette.responses import JSONResponse
        return JSONResponse({"detail": "rate limit"}, status_code=429)

    app.include_router(router)
    app.include_router(ws_router)
    app.mount("/static", StaticFiles(directory="static"), name="static")

    @app.get("/")
    async def index():
        return FileResponse("static/index.html")

    return app


app = create_app()
