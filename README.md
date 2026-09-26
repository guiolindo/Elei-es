# Apuração 2026

App web em Python + PostgreSQL para acompanhar a apuração das Eleições Gerais 2026 em tempo real, com foco em **comparar dois candidatos lado a lado**.

## Arquitetura

```
app/            FastAPI: endpoints REST, WebSocket, config, modelos SQLAlchemy
poller/         Coleta assíncrona dos JSONs públicos do TSE + parser
math_engine/    Motor matemático puro (eleição no 1T, 2º turno definido, majoritário)
alembic/        Migrations
scripts/        seed, prefetch de fotos
static/         HTML/CSS/JS (ECharts, WebSocket)
tests/          pytest
```

- **Backend**: FastAPI + SQLAlchemy 2 async + asyncpg
- **Banco**: PostgreSQL 16 (JSONB para snapshots brutos)
- **Frontend**: Vanilla JS + ECharts
- **Push em tempo real**: WebSocket + Web Push API (opcional)

## Rodando em dev

```bash
cp .env.example .env
docker compose up --build           # sobe postgres + app + nginx em http://localhost:8080
docker compose run --rm app alembic upgrade head
docker compose run --rm app python -m scripts.seed
```

Ou local, sem docker:

```bash
pip install -e .[dev]
alembic upgrade head
python -m scripts.seed
uvicorn app.main:app --reload
```

## Testes

```bash
python -m pytest tests/ -v
```

O motor matemático (`math_engine/`) é 100% coberto por testes puros — sem I/O.

## Coleta manual (debug)

```bash
python -m poller.once --cargo 1 --abrangencia BR
```

## Motor matemático

Regras (todas com desigualdade **estrita** — enquanto empate exato ainda for possível o resultado permanece em disputa):

- `votos_restantes_max = eleitorado_apto − eleitorado_apto_totalizadas` (clampeado em 0).
- Presidencial 1T: `votos_lider × 2 > votos_validos + restantes_max`.
- 2º turno definido: `votos_3o + restantes_max < votos_2o`.
- Majoritário (governador/senador/prefeito): `votos_2o + restantes_max < votos_lider`.

Antes de 20% das seções totalizadas, o motor fica silenciado.

## Feature principal — comparação

Clique em dois candidatos do mesmo cargo. Abre uma tela com:

- Cards simétricos com foto, número, partido, votos e %.
- Card central com diferença absoluta e em pontos percentuais, ao vivo.
- Gráficos ECharts (linhas de votos, % dos válidos, diferença acumulada, faixa de vitória).
- Atualização via WebSocket, sem reload.

## Deploy no Railway

1. **Crie o projeto** no Railway a partir do repositório (`New Project → Deploy from GitHub repo`).
2. **Adicione o plugin PostgreSQL** (`+ New → Database → Add PostgreSQL`). O Railway injeta automaticamente a variável `DATABASE_URL` no formato `postgres://…` — o app normaliza sozinho para `postgresql+asyncpg://…`.
3. **Variáveis** (Settings → Variables):
   - `CORS_ORIGINS` = URL pública do serviço (ex.: `https://apuracao-2026.up.railway.app`)
   - `POLL_INTERVAL_SECONDS` = `20` (opcional)
   - `TSE_CDN_BASE`, `ELEICAO_COD_1T`, `ELEICAO_COD_2T` — só se o TSE mudar de CDN
   - `VAPID_PUBLIC_KEY` / `VAPID_PRIVATE_KEY` — só se quiser Web Push
4. **Deploy**: o Railway usa `nixpacks.toml` + `Procfile`. O comando de start roda `alembic upgrade head` (migrations idempotentes), `python -m scripts.seed` (cargos/UFs/partidos idempotentes) e sobe o uvicorn na `$PORT` que o Railway define.
5. **Domínio**: `Settings → Networking → Generate Domain` — o healthcheck aponta para `/api/cargos`.

Arquivos usados pelo Railway: `Procfile`, `railway.json`, `nixpacks.toml`.

## Configuração

Todas via `.env` — ver `.env.example`. Se o TSE mudar de CDN, basta trocar `TSE_CDN_BASE` e reiniciar.

## Notas

- O TSE não fornece o flag "matematicamente definido". É este app que calcula.
- O histórico é responsabilidade da aplicação: cada iteração do poller salva um snapshot novo (deduplicado por SHA-256).
- Fotos: baixe uma vez antes do dia D com `python -m scripts.prefetch_candidatos`.
