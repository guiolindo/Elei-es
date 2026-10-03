from __future__ import annotations

import asyncio
import logging
import os
import re
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.api import router, ws_router
from app.config import get_settings
from app.ws import broadcaster
from poller.service import loop as poller_loop
from poller.candidatos_tse import sincronizar_candidatos, corrigir_partidos_orfaos
from poller.descoberta import descobrir_cods_eleicao

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
log = logging.getLogger("app")

limiter = Limiter(key_func=get_remote_address, default_limits=["100/minute"])

async def _descobrir_cod_loop():
    """A cada 5 min tenta descobrir os códigos reais da Eleição Geral 2026
    no TSE. Descobre os 4 códigos (presidencial + estadual, 1T + 2T).
    Quando TSE publica um novo/atualiza um existente, o config em memória
    se atualiza sozinho e o poller começa a puxar os arquivos certos no
    próximo ciclo.
    """
    settings = get_settings()
    while True:
        try:
            achados = await descobrir_cods_eleicao()
            for chave, valor in achados.items():
                atual = getattr(settings, chave, None)
                if atual != valor:
                    object.__setattr__(settings, chave, valor)
                    log.info("%s atualizado para %s (era %s)", chave, valor, atual)
        except Exception:
            log.exception("descoberta cod falhou")
        await asyncio.sleep(300)

async def _cleanup_snapshots_loop():
    """Retenção enxuta de snapshots: mantém os N=200 mais recentes por
    (cargo, abrangencia, turno) e apaga o resto.
    """
    from sqlalchemy import select, delete, func
    from app.db import SessionLocal
    from app.models import Snapshot, SnapshotTotais, SnapshotCandidato, SnapshotMunicipio, Evento
    settings = get_settings()
    N = settings.snapshots_retention_per_key
    await asyncio.sleep(120)
    while True:
        try:
            async with SessionLocal() as sess:
                zero = (await sess.execute(
                    select(Snapshot.id, Snapshot.cod_cargo, Snapshot.abrangencia,
                           Snapshot.turno, Snapshot.coletado_em)
                    .join(SnapshotTotais, SnapshotTotais.snapshot_id == Snapshot.id)
                    .where(SnapshotTotais.qt_secoes_totalizadas == 0)
                    .order_by(Snapshot.coletado_em.desc())
                )).all()
                if zero:
                    mantidos: set[int] = set()
                    vistos: set[tuple] = set()
                    for row in zero:
                        k = (row.cod_cargo, row.abrangencia, row.turno)
                        if k not in vistos:
                            vistos.add(k)
                            mantidos.add(row.id)
                    ids_zero = [r.id for r in zero if r.id not in mantidos]
                    if ids_zero:
                        for tabela in (Evento, SnapshotCandidato, SnapshotMunicipio, SnapshotTotais):
                            await sess.execute(delete(tabela).where(tabela.snapshot_id.in_(ids_zero)))
                        await sess.execute(delete(Snapshot).where(Snapshot.id.in_(ids_zero)))
                chaves = (await sess.execute(
                    select(Snapshot.cod_cargo, Snapshot.abrangencia, Snapshot.turno)
                    .group_by(Snapshot.cod_cargo, Snapshot.abrangencia, Snapshot.turno)
                )).all()
                total_apagado = 0
                for cargo, abr, turno in chaves:
                    corte = (await sess.execute(
                        select(Snapshot.coletado_em)
                        .where(Snapshot.cod_cargo == cargo, Snapshot.abrangencia == abr,
                               Snapshot.turno == turno)
                        .order_by(Snapshot.coletado_em.desc()).offset(N).limit(1)
                    )).scalar_one_or_none()
                    if not corte:
                        continue
                    ids_antigos = [r[0] for r in (await sess.execute(
                        select(Snapshot.id)
                        .where(Snapshot.cod_cargo == cargo, Snapshot.abrangencia == abr,
                               Snapshot.turno == turno, Snapshot.coletado_em < corte)
                    )).all()]
                    if not ids_antigos:
                        continue
                    for tabela in (SnapshotCandidato, SnapshotMunicipio, SnapshotTotais):
                        await sess.execute(delete(tabela).where(tabela.snapshot_id.in_(ids_antigos)))
                    await sess.execute(delete(Snapshot).where(Snapshot.id.in_(ids_antigos)))
                    total_apagado += len(ids_antigos)
                if total_apagado or ids_zero:
                    await sess.commit()
        except Exception:
            log.exception("cleanup snapshots falhou")
        await asyncio.sleep(settings.cleanup_interval_seconds)

async def _sync_candidatos_loop():
    """Sincroniza candidatos oficiais do TSE."""
    await asyncio.sleep(30)
    try:
        n = await corrigir_partidos_orfaos()
        if n:
            log.info("self-heal: %d candidatos com partido_numero corrigido", n)
    except Exception:
        log.exception("self-heal partidos falhou")
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
        tasks.append(asyncio.create_task(_descobrir_cod_loop()))
        tasks.append(asyncio.create_task(poller_loop(broadcaster=broadcaster)))
        tasks.append(asyncio.create_task(_sync_candidatos_loop()))
        tasks.append(asyncio.create_task(_cleanup_snapshots_loop()))
    log.info("poller + descoberta + sync + cleanup iniciados (intervalo=%ss)", settings.poll_interval_seconds)
    if (settings.telegram_bot_token or "").strip():
        from notif.telegram_bot import loop_bot
        tasks.append(asyncio.create_task(loop_bot()))
        log.info("telegram bot iniciado (@%s)", settings.telegram_bot_username)
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

    @app.middleware("http")
    async def _cache_publico(request: Request, call_next):
        resp = await call_next(request)
        if request.method == "GET" and request.url.path.startswith("/api/apuracao"):
            resp.headers.setdefault(
                "Cache-Control", "public, max-age=3, s-maxage=5, stale-while-revalidate=15"
            )
        return resp

    @app.get("/health")
    async def health():
        from sqlalchemy import text
        from app.db import SessionLocal
        try:
            async with SessionLocal() as sess:
                await sess.execute(text("SELECT 1"))
            return {"ok": True}
        except Exception as e:
            from starlette.responses import JSONResponse
            return JSONResponse({"ok": False, "erro": str(e)[:200]}, status_code=503)

    def _servir_html_com_versao(caminho: str) -> HTMLResponse:
        try:
            with open(caminho, "r", encoding="utf-8") as f:
                html = f.read()
            versoes = {}
            for arq in ("app.js", "app.css", "partidos.js", "verificacao.js", "urna.js"):
                p = os.path.join("static", arq)
                if os.path.exists(p):
                    versoes[arq] = int(os.path.getmtime(p))
            for arq, v in versoes.items():
                html = re.sub(
                    rf'(/static/{re.escape(arq)})(?!\?)',
                    rf'\1?v={v}',
                    html,
                )
            return HTMLResponse(html)
        except OSError:
            return FileResponse(caminho)

    @app.get("/")
    async def index():
        return _servir_html_com_versao("static/index.html")

    @app.get("/importar")
    async def importar_page():
        return _servir_html_com_versao("static/importar.html")

    @app.get("/sobre")
    async def sobre_page():
        return _servir_html_com_versao("static/sobre.html")

    @app.get("/faq")
    async def faq_page():
        return _servir_html_com_versao("static/sobre.html")

    @app.get("/termos")
    async def termos_page():
        return _servir_html_com_versao("static/sobre.html")

    @app.get("/privacidade")
    async def privacidade_page():
        return _servir_html_com_versao("static/sobre.html")

    @app.get("/verificacao")
    async def verificacao_page():
        return _servir_html_com_versao("static/verificacao.html")

    @app.get("/cola")
    async def cola_page():
        return _servir_html_com_versao("static/cola.html")

    @app.get("/urna")
    async def urna_page():
        return _servir_html_com_versao("static/urna.html")

    return app

app = create_app()
