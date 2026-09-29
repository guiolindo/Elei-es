# Operations

Guia de operação: Railway, admin token, coleta via Termux, migrations Alembic, monitoramento, troubleshooting.

## Deploy inicial no Railway

1. **Novo projeto** a partir do repositório GitHub.
2. **Adicionar PostgreSQL** (`+ New → Database → Add PostgreSQL`). Railway injeta `DATABASE_URL` automaticamente. O app normaliza `postgres://` → `postgresql+asyncpg://` em `app/config.py`.
3. **Setar variáveis** (Settings → Variables):

| Variável | Obrigatória | Descrição |
|---|---|---|
| `ADMIN_TOKEN` | sim | Protege endpoints `/api/admin/*`. Gere um valor forte (32+ chars). |
| `CORS_ORIGINS` | sim | URL pública do serviço, ex.: `https://apuracao-2026.up.railway.app`. |
| `TELEGRAM_BOT_TOKEN` | não | Token do BotFather. Sem isso o bot fica desligado. |
| `TELEGRAM_BOT_USERNAME` | não | Username sem @, default `avisoeleicao_bot`. |
| `POLL_INTERVAL_SECONDS` | não | Default 20. |
| `SESSION_SECRET` | não | Chave pra sessões futuras. Setar em prod. |
| `VAPID_PUBLIC_KEY` / `VAPID_PRIVATE_KEY` | não | Web Push. Deixar vazio desabilita. |
| `TSE_CDN_BASE` / `TSE_FOTOS_BASE` / `TSE_DIVULGA_BASE` | não | Override das URLs base do TSE. Só setar se o TSE mudar de host. |
| `ELEICAO_ANO`, `ELEICAO_COD_1T`, `ELEICAO_COD_2T`, `ELEICAO_COD_DIVULGA` | não | Códigos internos do TSE. Auto-detect via `poller/descoberta.py`. |

4. **Deploy**: Railway usa `Procfile` + `nixpacks.toml`. O start command roda:
   ```
   alembic upgrade head && python -m scripts.seed && uvicorn app.main:app --host 0.0.0.0 --port $PORT
   ```
   `alembic upgrade head` e `scripts.seed` são idempotentes — rodam a cada deploy sem duplicar dados.

5. **Domínio**: `Settings → Networking → Generate Domain`. Healthcheck aponta pra `/health` (SELECT 1 no banco).

## Rotina de deploy

- **Push pra main** → Railway detecta, roda build, aplica migrations, sobe novo container.
- **Zero-downtime**: Railway faz rolling deploy.
- **Rollback**: `Deployments` → deploy anterior → `Redeploy`.

## Migrations Alembic

Estrutura:
```
alembic/
  versions/
    20260101_0000_0001_inicial.py
    20260928_1000_0002_snapshot_municipio.py
    20260928_2300_0003_candidato_raw.py
    20260929_1000_0004_telegram_subs.py
```

Nova migration:
```bash
# Criar manualmente pra evitar autogenerate ruim
touch alembic/versions/YYYYMMDD_HHMM_NNNN_descricao.py
```

Template:
```python
"""descricao curta

Revision ID: NNNN
Revises: <NNNN anterior>
Create Date: 2026-MM-DD
"""
from alembic import op
import sqlalchemy as sa

revision = "NNNN"
down_revision = "<anterior>"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.add_column("tabela", sa.Column("nova_coluna", sa.String(64)))

def downgrade() -> None:
    op.drop_column("tabela", "nova_coluna")
```

Aplicar local: `alembic upgrade head`. Railway aplica no start automaticamente.

## Bot do Telegram

### Criar o bot

1. Falar com [@BotFather](https://t.me/BotFather) no Telegram.
2. `/newbot` → escolher nome + username (deve terminar em `bot`).
3. Copiar o token que ele devolve.
4. Setar `TELEGRAM_BOT_TOKEN` e `TELEGRAM_BOT_USERNAME` no Railway.
5. Redeploy.

O bot inicia long polling automaticamente no lifespan da app. Se o token estiver vazio, fica desligado sem erro.

### Monitorar o bot

Logs do Railway mostram cada update processado. Erros de rede são logados como warning e o loop continua.

### Comandos disponíveis

Ver `README.md#bot-do-telegram` — 13 comandos de consulta + 6 de assinatura.

### Escalonar

Long polling roda como uma task asyncio no mesmo processo do FastAPI. Não escala horizontalmente — se subir 2 réplicas, ambas fazem long polling e recebem eventos duplicados. Se precisar escalar:
- Trocar pra webhook (endpoint `/telegram/webhook` recebendo POST do Telegram).
- Ou: fazer só 1 réplica processar bot (via lock no banco / env var).

## Coleta via Termux (bypass Akamai)

**Contexto**: `divulgacandcontas.tse.jus.br` bloqueia backends fora do BR via Akamai. Isso impede o Railway de pegar a **ficha completa** dos candidatos (nascimento, sexo, ocupação, gastos, vice). O endpoint `resultados.tse.jus.br` (apuração ao vivo) NÃO tem Akamai e o Railway acessa direto.

**Solução**: rodar `scripts/importar_termux.py` do celular do usuário (IP residencial BR + `curl-cffi` impersonando o TLS fingerprint do Chrome). O script bate no TSE, extrai fichas, e envia via POST `/api/admin/atualizar-detalhe` no seu Railway.

### Setup Termux

1. Instalar [Termux](https://f-droid.org/en/packages/com.termux/) (F-Droid recomendado; Play Store desatualizado).
2. No Termux:
   ```bash
   pkg update && pkg install python
   pip install curl-cffi
   git clone https://github.com/guiolindo/Elei-es.git
   cd Elei-es
   ```

3. Setar o token e rodar:
   ```bash
   export ADMIN_TOKEN="mesmo_valor_do_railway"
   python scripts/importar_termux.py https://elei-es-production.up.railway.app
   ```

Ou passar o token como 2º argumento:
```bash
python scripts/importar_termux.py https://elei-es-production.up.railway.app SEU_TOKEN
```

### O que o script faz

1. Limpa candidatos-seed antigos via `POST /api/admin/limpar-seed`.
2. Pra cada cargo (Presidente, Governador, Senador, Dep. Federal, Dep. Estadual) × cada UF:
   - Baixa a lista via `divulgacandcontas/rest/v1/candidatura/listar/...`.
   - Envia pro Railway via `POST /api/admin/importar-candidatos`.
3. Pra cada majoritário (cargos 1, 3, 5): baixa a **ficha completa** via `divulgacandcontas/rest/v1/candidatura/buscar/{ano}/{uf}/{cod}/candidato/{sq}` — com fallback de UFs pra presidente (tenta BR + SP + RJ + MG + DF + UF do payload).
4. Baixa a **foto** via `divulgacandcontas/rest/arquivo/img/{cod}/{sq}/{uf}` e envia base64 pro Railway via `/api/admin/upload-foto`.

Todo com header `X-Admin-Token`.

### Rodagem recomendada

- **Antes da apuração** (D-1 e D-0 manhã): rodar 1x pra popular candidatos + fotos + fichas completas.
- **Durante a apuração**: NÃO precisa. A apuração ao vivo vem por `resultados.tse.jus.br` que o Railway acessa direto.

## Endpoints admin

Todos exigem header `X-Admin-Token: <valor>`. Se `ADMIN_TOKEN` está vazio (dev), libera — nunca deixar vazio em prod.

| Endpoint | Método | Uso |
|---|---|---|
| `/api/admin/status` | GET | Contadores rápidos do banco |
| `/api/admin/testar-tse` | GET | Testa conectividade com 5 endpoints do TSE |
| `/api/admin/diagnostico-ids` | GET | Confere se SQs de snapshots batem com candidatos |
| `/api/admin/limpar-seed` | POST | Remove candidatos "PR2026_*" (seed antigo) |
| `/api/admin/importar-candidatos` | POST | Recebe JSON do TSE (via Termux) e upsert |
| `/api/admin/atualizar-detalhe` | POST | Merge do JSON de detalhe em `raw_divulga` |
| `/api/admin/upload-foto` | POST | Recebe base64 e salva em `static/candidatos/` |
| `/api/admin/sync-candidatos` | POST | Roda sincronizador programaticamente |

## Monitoramento

- **Healthcheck**: `/health` retorna 200 (com `SELECT 1`) ou 503. Railway monitora automaticamente.
- **Logs**: Railway → Deployments → clicar no deployment ativo → Logs.
- **Métricas**: Railway mostra CPU, RAM, tráfego. `poller` gasta ~50MB.
- **UptimeRobot / BetterUptime**: apontar pra `/health` a cada 1min pra alertas externos.

## Troubleshooting

### "Bad Request: object expected as reply markup" nos logs do bot

Já corrigido. Bug de `reply_markup: null` sendo enviado quando o comando não tinha teclado. Se aparecer de novo, verificar `notif/telegram_bot.py` função `_send` — precisa omitir `reply_markup` quando `keyboard is None`.

### Cache/CDN servindo versão antiga do JS/CSS

`Cache-Control: public, max-age=3, s-maxage=5, stale-while-revalidate=15` em `/api/apuracao/*`. Se precisar invalidar imediatamente, adicionar query string com hash ao fim do path (ex.: `/static/app.js?v=abc123`).

### Poller retornando 403 do TSE

Se `resultados.tse.jus.br` retornar 403, provavelmente o TSE ativou Akamai também nessa URL (nunca aconteceu em anos anteriores, mas monitorar). Fallback: adicionar Cloudflare Worker proxy ou rodar coleta via Termux + `POST /api/admin/importar-snapshot`.

### Snapshot suspeito não zerando

Se `poller/service.py` continua marcando `suspeito=True` por várias horas seguidas, é sinal de que o TSE está reprocessando várias seções — normal em horas iniciais. Se persistir >2h em pleno pico de apuração, olhar o JSON bruto em `snapshots.raw`.

### Migration não aplica no Railway

Ver logs do deploy — Alembic loga cada revision. Se falhar, o container não sobe. Fix:
1. `alembic downgrade -1` local.
2. Corrige migration.
3. Re-push.

Nunca editar uma migration já aplicada em prod — sempre criar nova.

### Bot Telegram não responde

1. Confirmar `TELEGRAM_BOT_TOKEN` no Railway.
2. Ver logs pra "telegram bot iniciado".
3. Se rodam 2 réplicas, uma delas está pegando os updates (race). Escalar pra 1.
4. Se aparece "conflict: another instance is running", parar todos os processos locais que possam estar usando o mesmo token.
