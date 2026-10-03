# AGENTS.md — mapa "o que ler pra qual tarefa"

Este documento é otimizado pra IAs e desenvolvedores novos que precisam entrar no projeto rápido. Não lista tudo — só o essencial pra cada tipo de tarefa.

## Se você vai...

### ...trabalhar no motor matemático (regras eleitorais)

**Leia primeiro**: `docs/metodologia.md` (as fórmulas com fontes primárias e o link pra cada artigo do Código Eleitoral / STF).

**Depois**: `math_engine/engine.py` e `math_engine/proporcional.py`. São puros — nada de I/O.

**Testes**: `tests/test_math_engine.py`, `tests/test_proporcional.py` e `tests/test_candidatos_tse_situacao.py`. Rodam em <1s. `pytest -k <nome>` pra rodar caso específico.

**Regra de ouro**: toda alteração aqui precisa de teste. Bugs matemáticos no dia D são catastróficos. Sempre desigualdade estrita.

**Invariantes que não podem ser quebradas**:
- Ambos motores (majoritário e proporcional) **filtram `situacao != "ativo"`** antes de qualquer cálculo. Lei 9.504/97 art. 175 §3º: votos em cassados/renunciados/indeferidos são nulos — não contam no QE, QP, barreira, D'Hondt, nem no total de válidos pra maioria absoluta. Se adicionar novo `CandidatoResumo`/`CandidatoProporcional`, propague o campo `situacao`.
- Alvos `(cargo=1 Presidente, UF)` **não geram eventos**. Guard em `poller/service.py`. Presidente só é avaliado quando `abrangencia="BR"` (CF art. 77 §2º é nacional).

### ...ajustar o poller / coleta do TSE

**Leia primeiro**: `poller/service.py` (loop principal, semáforo, gather).

**Depois**: `poller/parser.py` (parser tolerante), `poller/candidatos_tse.py` (upsert de candidatos), `poller/descoberta.py` (autodetect do `cod_eleicao`).

**Cliente HTTP**: `poller/tse_client.py` — headers de navegador (Akamai bloqueia curl padrão).

**Gotcha crítico**: `divulgacandcontas.tse.jus.br` bloqueia o backend do Railway. Se você mexer nesses endpoints, use `scripts/importar_termux.py` do celular. `resultados.tse.jus.br` funciona direto.

### ...trabalhar no bot do Telegram

**Leia primeiro**: `notif/telegram_bot.py` (arquivo único ~750 linhas).

**Sections do arquivo**:
- Constantes + helpers HTTP (topo)
- `cmd_*` — cada comando de consulta ao vivo
- `_tratar_assinar_start`, `_listar_assinaturas`, `_tratar_callback` — wizard inline
- `_tratar_mensagem` — dispatcher de comandos texto
- `loop_bot` — long polling principal
- `enviar_notificacoes` — chamado pelo poller quando um evento novo é emitido

**Testar mudança**: setar `TELEGRAM_BOT_TOKEN` no `.env` e conversar com o bot. Zero test suite pra ele (interação humana).

### ...ajustar frontend (design / animação)

**Leia primeiro**: `static/app.css` (~1250 linhas, comentado em blocos):
- Design tokens no topo
- Motion tokens + reduced-motion
- Cards de candidato (redesign v2)
- Iconografia SVG
- Mobile app chrome (media query <=768px)
- Rodapé, modal, comparação, mapa

**Depois**: `static/app.js`:
- Motion helpers (`addRipple`, `anexarEntradaCascata`, `flipReorder`)
- State + persistência em `localStorage`
- `renderLista()`, `refreshApuracao()`
- WebSocket com backoff
- `bootMobile()` pra chrome mobile

**HTML principal**: `static/index.html` (~350 linhas). Sprite SVG de ícones no topo do body.

**Regra**: só animar `transform` e `opacity`. `will-change` só durante o movimento e removido depois. Todas as animações honram `prefers-reduced-motion`.

### ...adicionar endpoint HTTP

**Leia primeiro**: `app/api.py` (todos os endpoints em um arquivo, ~800 linhas).

**Padrão**: `@router.get("/rota")` retornando `dict`. Injetar sessão com `sess: AsyncSession = Depends(get_session)`.

**Admin**: qualquer rota sob `/admin/*` recebe o dependency `_exigir_admin` automaticamente. Novos endpoints admin herdam a proteção.

**Rate limit**: global 100/min por IP via slowapi (`app.main`). Se precisar mais restrito, decorar com `@limiter.limit("10/minute")`.

### ...ajustar schema do banco

**Leia primeiro**: `app/models.py` (~150 linhas — todos os modelos).

**Padrão**: nova migration em `alembic/versions/YYYYMMDD_HHMM_NNNN_descricao.py`, incrementando o número. Sempre `upgrade()` e `downgrade()` (mesmo que downgrade seja apenas descartar).

**Aplicar**: `alembic upgrade head` (local ou Railway roda no start via Procfile).

### ...corrigir bug reportado

**Ordem**:
1. Reproduzir com teste que falha antes da correção.
2. Fix.
3. Rodar `pytest tests/ -q` — precisa passar tudo (44 casos hoje).
4. Commit com mensagem no formato do CHANGELOG.

### ...revisar segurança / LGPD

**Leia primeiro**: `docs/security.md`, depois `static/sobre.html` seção §5 (política de privacidade).

**Superfícies de risco**:
- Endpoints `/api/admin/*` — todos protegidos por token.
- Rate limit global slowapi 100/min.
- CORS configurável.
- Nada de PII coletado no site (só `chat_id` no bot; sem nome, email, telefone).

## Se você é IA

**Não invente rotas ou nomes de tabela**. Confirme lendo `app/api.py` e `app/models.py`.

**Não presuma que uma regra eleitoral é X**. Leia `docs/metodologia.md`, e se estiver em dúvida sobre jurisprudência atual, pesquise fontes primárias (portal STF, senado.leg.br, TSE) antes de escrever código. Regras mudam entre eleições (ex.: Lei 14.211/2021 introduziu 80/20; STF derrubou em 2024).

**Não delete `raw_divulga JSONB` dos candidatos**. É o payload completo do TSE — permite adicionar campos novos no futuro sem re-sincronizar todos os candidatos.

**Não desabilite `admin_token`** em prod. Sem ele, qualquer um pode `POST /api/admin/limpar-seed`.

**Não anime propriedades que não sejam `transform` ou `opacity`**. Trava dispositivo do usuário.

**Não mude o valor de `VAGAS_MAJORITARIO_PADRAO`** sem verificar o ano da eleição. 2026 = 2 vagas de senador; 2022 e 2018 = 1.

**Não confie que o TSE nunca muda o schema JSON**. Parsers em `poller/parser.py` e `poller/candidatos_tse.py` são tolerantes (usam `_pick` com fallbacks). Mantenha assim.

**Não mude a lista de federações partidárias** (`FEDERACOES_2026_DEFAULT`) sem cross-check com fontes eleitorais atualizadas do TSE.

## Guia rápido de comandos

```bash
# Setup
cp .env.example .env
docker compose up --build

# Testes
python -m pytest tests/ -q                    # todos
python -m pytest tests/test_math_engine.py    # só matemática

# Migrations
alembic upgrade head
alembic revision --autogenerate -m "descricao"  # crie manualmente pra evitar autogenerate ruim

# Coleta manual
python -m poller.once --cargo 1 --abrangencia BR
python scripts/importar_termux.py https://... TOKEN

# Bot local (setar TELEGRAM_BOT_TOKEN no .env)
uvicorn app.main:app --reload
# → bot conecta em long-polling automaticamente
```
