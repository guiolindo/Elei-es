# API Reference

Endpoints REST + WebSocket. Todos sob prefixo `/api`. Rate limit global: 100/min por IP.

## Público (sem autenticação)

### `GET /api/config-publica`
Config exposta ao frontend (username do bot, ano da eleição). Só devolve `telegram_bot` se o token estiver configurado.

### `GET /api/cargos`
Lista dos 5 cargos (Presidente, Governador, Senador, Dep. Federal, Dep. Estadual).

### `GET /api/ufs`
27 UFs com sigla, nome e código IBGE.

### `GET /api/candidatos?cargo={n}[&uf={UF}]`
Lista de candidatos daquele cargo (opcionalmente por UF). Dados básicos.

### `GET /api/candidato/{sq}`
Ficha completa: nome, número, partido, situação, sexo, cor/raça, estado civil, data nascimento, escolaridade, ocupação, UF/município nascimento, gasto de campanha, CNPJ, vice. Todo o `raw_divulga` do TSE mesclado.

### `GET /api/apuracao/atual?cargo={n}&abrangencia={BR|UF}`
Último snapshot não-suspeito. Inclui `snapshot_id` e `hash_conteudo` SHA-256 pra verificação.

**Resposta**:
```json
{
  "disponivel": true,
  "coletado_em": "2026-10-05T20:14:23Z",
  "gerado_em_tse": "2026-10-05T20:13:00Z",
  "snapshot_id": 1234,
  "hash_conteudo": "abc123...",
  "totais": {...},
  "candidatos": [{"sq_candidato", "votos", "pct_validos", "posicao"}]
}
```

### `GET /api/apuracao/historico?cargo={n}&abrangencia={...}[&desde=ISO8601]`
Séries temporais dos votos de cada candidato.

### `GET /api/apuracao/proporcional?cargo={6|7}&uf={UF}`
Cálculo proporcional completo: QE, barreiras, lista de eleitos/suplentes por status, lista de partidos com vagas ganhas em cada fase. Ver `docs/metodologia.md` pras regras.

### `GET /api/apuracao/municipio?uf={UF}&cargo={n}[&cod_ibge={7-digits}]`
Resultados por município (quando o TSE inclui breakdown `abr[].mu[]`).

### `GET /api/apuracao/lideres-por-uf?cargo={n}`
Líder de cada UF pra montar o mapa cloroplético. Retorna `{UF: {sq_candidato, nome_lider, cor, votos}}`.

### `GET /api/apuracao/lideres-por-municipio?uf={UF}&cargo={n}`
Idem, mas por município da UF.

### `GET /api/eventos?[cargo={n}][&abrangencia={...}]`
Timeline dos eventos matemáticos (ELEITO_1T, VIRADA, etc). Ordenados por `ocorrido_em` desc, limit 100.

## Admin (requer `X-Admin-Token`)

### `GET /api/admin/status`
Contadores rápidos: total de snapshots, eventos, candidatos, hora do último snapshot.

### `GET /api/admin/testar-tse`
Faz requisições de teste pros 5 endpoints principais do TSE, retorna status HTTP de cada.

### `GET /api/admin/diagnostico-ids`
Confere consistência entre SQs nos snapshots e SQs nos candidatos importados. Alerta candidatos "faltando ficha".

### `POST /api/admin/limpar-seed`
Remove candidatos com SQ começando em `PR2026_`, `GO2026_`, `SE2026_`, etc. (candidatos de seed antigo).

### `POST /api/admin/importar-candidatos`
Recebe `{cargo, uf, json}` — JSON bruto do TSE — e faz upsert em `candidatos`.

### `POST /api/admin/atualizar-detalhe`
Recebe `{sq_candidato, detalhe}` — mescla `detalhe` no `raw_divulga` do candidato + denormaliza `foto_url`/`coligacao`/`vice` quando vazios.

### `POST /api/admin/upload-foto`
Recebe `{sq_candidato, b64}` — salva foto em `static/candidatos/{sq}.jpg`.

### `POST /api/admin/sync-candidatos`
Roda `sincronizar_candidatos()` programaticamente. Falha nos endpoints que dão 403 do Akamai.

## Compare

### `POST /api/comparacoes`
Registra que uma sessão comparou candidatos A e B (analytics).

## Web Push (opcional)

### `POST /api/push/subscribe`
Registra endpoint anônimo do navegador pra receber push notifications de eventos.

## WebSocket

### `WS /ws/apuracao?cargo={n}&abrangencia={BR|UF}`
Cada snapshot novo (não-suspeito) dispara broadcast:
```json
{
  "type": "snapshot",
  "snapshot_id": 1234,
  "eventos": [
    {"tipo": "ELEITO_1T", "sq_candidato_a": "...", "detalhes": {...}}
  ]
}
```

Cliente deve reconectar com backoff em caso de queda. Frontend implementa exponencial 1s → 15s teto + jitter.

## Sistema

### `GET /health`
Healthcheck: retorna `{"ok": true}` se `SELECT 1` no banco funciona, 503 caso contrário. Usado pelo Railway/UptimeRobot.
