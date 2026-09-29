# Getting started — dev local

Setup do projeto pra desenvolvimento. Deploy em produção está em `docs/operations.md`.

## Pré-requisitos

- Python 3.11+
- PostgreSQL 15+ (ou Docker)
- Node não é necessário — frontend é vanilla JS servido diretamente.

## Setup com Docker (recomendado)

```bash
git clone https://github.com/guiolindo/Elei-es.git
cd Elei-es
cp .env.example .env
docker compose up --build
```

Isso sobe:
- `postgres` na porta 5432
- `app` (FastAPI + poller) na porta 8000
- `nginx` na porta 8080 (serve `static/` + proxy para `app`)

Aplicar migrations e seed inicial:
```bash
docker compose run --rm app alembic upgrade head
docker compose run --rm app python -m scripts.seed
```

Site em `http://localhost:8080`.

## Setup sem Docker

```bash
git clone https://github.com/guiolindo/Elei-es.git
cd Elei-es
python -m venv .venv && source .venv/bin/activate
pip install -e .[dev]
cp .env.example .env
```

Configurar `.env`:
```
DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/apuracao
CORS_ORIGINS=http://localhost:8000
ADMIN_TOKEN=dev-token-qualquer-coisa
```

Criar banco e aplicar schema:
```bash
createdb apuracao
alembic upgrade head
python -m scripts.seed
```

Rodar:
```bash
uvicorn app.main:app --reload
```

Site em `http://localhost:8000`.

## Rodando os testes

```bash
python -m pytest tests/ -v
```

Devem passar 44 casos em ~0.2s. Tudo é teste puro — sem I/O, sem banco.

Rodar um teste específico:
```bash
python -m pytest tests/test_math_engine.py::test_eleito_1t_presidencial_confirmado -v
```

## Comandos úteis

**Coleta manual do TSE** (útil pra debug):
```bash
python -m poller.once --cargo 1 --abrangencia BR
```

**Sincronizar candidatos** (só funciona no BR ou via Termux — Akamai bloqueia):
```bash
python -m poller.candidatos_tse
```

**Testar conectividade com o TSE**:
```bash
curl http://localhost:8000/api/admin/testar-tse -H "X-Admin-Token: dev-token-qualquer-coisa"
```

## Estrutura de código pra ler primeiro

Se você é novo no projeto:

1. **`README.md`** — visão geral
2. **`AGENTS.md`** — mapa "o que ler pra qual tarefa"
3. **`math_engine/engine.py`** — regras matemáticas (motor puro)
4. **`docs/metodologia.md`** — fórmulas com fontes primárias
5. **`app/api.py`** — todos os endpoints REST
6. **`app/models.py`** — modelo de dados (12 tabelas)
7. **`ARCHITECTURE.md`** — decisões e contratos internos

## IDE

- **VS Code**: extensões recomendadas Python, Pylance, Ruff.
- **PyCharm**: importar como projeto Python normal.

## Convenções

- **Python**: PEP 8, type hints obrigatórios em funções públicas.
- **Docstrings**: em português. Explicam o **porquê**, não o **quê** (o código já diz o quê).
- **Commits**: título em português, imperativo minúsculo. Corpo com bullet points explicando decisões. Attribution footer automática.
- **CSS**: comentários em blocos separando seções. Design tokens no `:root`.
- **JS**: vanilla, sem framework. Funções nomeadas em português (`renderLista`, `atualizarPainelTotais`).
