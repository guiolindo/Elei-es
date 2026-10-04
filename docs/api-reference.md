# API Reference

Endpoints REST + WebSocket. Todos sob prefixo `/api`. Rate limit global: 100/min por IP.

## Público (sem autenticação)

### `GET /api/config-publica`
Config exposta ao frontend (username do bot, ano da eleição, códigos TSE em uso). Só devolve `telegram_bot` se o token estiver configurado.

### `GET /api/poller-status`
Observabilidade do loop de coleta. Permite confirmar externamente que o poller está rodando no intervalo esperado.
```json
{
  "ciclo_atual": 42, "intervalo_s": 20, "alvos_total": 193,
  "ultimo_ciclo_em": "2026-10-04T20:14:23+00:00",
  "ultimo_ciclo_duracao_s": 3.21,
  "segundos_desde_ultimo_ciclo": 7.4,
  "uptime_s": 851.2,
  "ultimo": {"novos": 2, "dedup": 135, "falhas": 0,
              "nao_publicado": 56, "retrocesso": 0}
}
```
`nao_publicado` = alvos que o TSE devolve 404 (ex.: 2º turno antes de ser aberto) — **não** é falha. `falhas > 0` significa erro real (5xx, timeout, DNS).

### `GET /api/cargos`
Lista dos cargos (Presidente, Governador, Senador, Dep. Federal, Dep. Estadual/Distrital). DF usa cargo `7` no nosso enum (unificado com Dep. Estadual); a tradução pra `c0008` do TSE acontece internamente.

### `GET /api/ufs`
27 UFs com sigla, nome e código IBGE.

### `GET /api/candidatos?cargo={n}[&uf={UF}]`
Lista de candidatos daquele cargo (opcionalmente por UF). **Dedup por `(uf, numero)`**: quando o TSE mantém dois `sq_candidato` pra mesma vaga (substituição/reregistro), devolve só um — preferência pra `situacao='ativo'`; empate → sq_candidato mais recente.

### `GET /api/candidato/{sq}`
Ficha completa. Campos:
- `situacao`: enum interno (`ativo` | `renunciou` | `cancelado` | `cassado` | `indeferido_sem_recurso`). Fonte da verdade pra motor e UI.
- `situacao_tse`: `descricaoSituacao` cru do TSE (ex.: `"Renúncia"`, `"Inapto"`, `"Pendente de julgamento"`).
- `situacao_candidatura`: alias do campo acima pra compatibilidade.
- `sexo`, `cor_raca`, `estado_civil`, `data_nascimento`, `grau_instrucao`, `ocupacao`, `uf_nascimento`, `municipio_nascimento`, `gasto_campanha`, `cnpj_campanha`, `vice_nome`, `vice_partido_sigla`.

### `GET /api/apuracao/atual?cargo={n}&abrangencia={BR|UF}[&inflate=true]`
Último snapshot não-suspeito.
```json
{
  "disponivel": true,
  "coletado_em": "2026-10-04T20:14:23Z",
  "gerado_em_tse": "2026-10-04T20:13:00-03:00",
  "snapshot_id": 1234,
  "hash_conteudo": "abc...",
  "totais": {"secoes_total": 499248, "secoes_totalizadas": 100000, ...},
  "candidatos": [{"sq_candidato", "votos", "pct_validos", "posicao",
                   "projecao_linear", "projecao_tendencia"}],
  "orfaos": []
}
```
- `orfaos`: lista de `sq_candidato` presentes no snapshot mas **sem registro em `candidatos`** (importação pendente via Termux). Frontend usa isso pra re-fetchar `/api/candidatos` sem recarregar.
- `inflate=true` adiciona `nome_urna`, `numero`, `partido`, `situacao`, `uf` em cada candidato (payload mais pesado, útil pra evitar join no cliente).
- `projecao_linear`: extrapolação aritmética simples (`votos_atual × secoes_total ÷ secoes_apuradas`). Sempre presente.
- `projecao_tendencia`: estimativa de **votos** pela janela móvel das últimas 15 snapshots. `null` antes de 30% apurado, após 100%, ou sem histórico suficiente (<10 snapshots na janela). Reage ao ritmo recente mas não modela composição regional das urnas faltantes. Clipada entre `votos_atual` e `2 × projecao_linear` (guard de UX).
- `projecao_pct_tendencia`: estimativa de **% dos válidos** final pela mesma janela. Só presente em cargos majoritários (1=Presidente, 3=Governador, 5=Senador). Em proporcional (6, 7) a % individual não é o KPI que decide eleição — ver `status_projetado` em `/api/apuracao/proporcional`.
- `gerado_em_tse` vem em BRT (`-03:00`); demais datas em UTC.

### `GET /api/apuracao/historico?cargo={n}&abrangencia={...}[&desde=ISO8601]`
Séries temporais dos votos de cada candidato.

### `GET /api/apuracao/proporcional?cargo={6|7}&uf={UF}`
Cálculo proporcional completo: QE, barreiras, eleitos/suplentes por status, partidos com vagas ganhas em cada fase. **Candidatos com `situacao != "ativo"` são excluídos antes do cálculo** (Lei 9.504/97 art. 175 §3º). Ver `docs/metodologia.md` seção 7.

Cada candidato também recebe `status_projetado`: resultado do mesmo motor rodado sobre os votos projetados pela janela móvel. Útil pra ver "se o ritmo recente continuar, quem se elege" — frontend mostra isso como badge discreto apenas quando `status_projetado != status` (ex.: candidato ainda não eleito mas projetado como eleito).

### `GET /api/apuracao/municipio?uf={UF}&cargo={n}[&cod_ibge={7-digits}]`
Resultados por município (quando TSE inclui breakdown `abr[].mu[]`).

### `GET /api/apuracao/lideres-por-uf?cargo={n}`
Líder de cada UF pra montar o mapa cloroplético. **Exige `votos > 0`** pra o candidato ser considerado líder — evita "líder fantasma" pré-apuração (candidato com 0 votos aparecendo colorido).

### `GET /api/apuracao/lideres-por-municipio?uf={UF}&cargo={n}`
Idem, mas por município da UF.

### `GET /api/apuracao/bu?uf={UF}&municipio={cod_tse}&zona={n}&secao={n}&cargo={n}[&turno={1|2}]`
Boletim de urna (BU) por seção eleitoral individual. Inclui `url_imagem_bu`: link direto pra imagem JPEG assinada digitalmente pelo TSE da seção.

### `GET /api/municipios?uf={UF}`
Lista de municípios da UF pra o wizard do `/urna`. Dados vindos de `arquivo-urna/3220/config/{uf}/{uf}-p003220-cs.json` do TSE.

### `GET /api/municipios/{municipio}/zonas?uf={UF}`
Zonas eleitorais do município, cada uma com a lista de seções disponíveis. Alimenta os pickers em cascata do wizard do BU.

### `GET /api/eventos?[cargo={n}][&abrangencia={...}]`
Timeline dos eventos matemáticos (ELEITO_1T, VIRADA, SEGUNDO_TURNO_DEFINIDO, ELEITO_MAJORITARIO, ELEITO_2T, MATEMATICAMENTE_ELIMINADO). Ordenados por `ocorrido_em` desc, limit 100.

**Garantia importante**: eventos NUNCA são emitidos pra alvos `(cargo=1 Presidente, UF)`. Maioria absoluta pra Presidente é nacional (CF art. 77 §2º).

## Admin (requer `X-Admin-Token`)

### `GET /api/admin/status`
Contadores por cargo/UF, total de snapshots, hora do último.

### `GET /api/admin/testar-tse`
Testa 5 endpoints do TSE a partir do IP do backend (Railway).

### `GET /api/admin/diagnostico-ids`
Confere consistência entre SQs em snapshots e SQs importados. Alerta candidatos faltando ficha.

### `GET /api/admin/diagnostico-mismatches`
Alias do anterior focado em sq_candidatos vistos em snapshots **mas não em `candidatos`** — órfãos. Diz quantos existem e lista até 50.

### `GET /api/admin/duplicatas`
Lista `(cod_cargo, uf, numero)` com mais de um `sq_candidato` ativo no DB — sinal de substituição/reregistro TSE em que o antigo ainda não foi marcado como `cancelado`. Payload inclui todos os sq_candidatos conflitantes com nome e situação de cada.

### `POST /api/admin/reavaliar-situacao`
Reaplica o parser de `descricaoSituacao` sobre o `raw_divulga` salvo pra TODOS os candidatos. Útil quando um fix no parser (ex.: acentos) precisa valer sem esperar o próximo ciclo de sync. Retorna `{"mudados": N}`.

### `POST /api/admin/limpar-seed`
Remove candidatos de seed (`PR2026_`, `GO2026_`, …).

### `POST /api/admin/importar-candidatos`
Recebe `{cargo, uf, json}` — payload bruto do TSE. Faz upsert em `candidatos` + **marca como `cancelado` qualquer ativo daquele (cargo, uf) que o TSE não devolveu** (self-heal pra "candidato sumiu da listagem oficial"). Retorna `{"atualizados": N, "removidos": M, ...}`.

### `POST /api/admin/atualizar-detalhe`
Recebe `{sq_candidato, detalhe}` — mescla no `raw_divulga` + denormaliza `foto_url`/`coligacao`/`vice`.

### `POST /api/admin/upload-foto`
Recebe `{sq_candidato, b64}` → salva em `static/candidatos/{sq}.jpg`.

### `POST /api/admin/sync-candidatos`
Dispara `sincronizar_candidatos()` programaticamente. Falha nos endpoints bloqueados pelo Akamai.

## Compare

### `POST /api/comparacoes`
Registra comparação de 2 candidatos (analytics anônimo por `session_id`).

## Web Push (opcional)

### `POST /api/push/subscribe`
Registra endpoint anônimo do navegador pra receber push notifications.

## WebSocket

### `WS /ws/apuracao?cargo={n}&abrangencia={BR|UF}`
Broadcast a cada snapshot novo (não-suspeito):
```json
{
  "type": "snapshot",
  "snapshot_id": 1234,
  "eventos": [
    {"tipo": "ELEITO_1T", "sq_candidato_a": "...", "detalhes": {...}}
  ]
}
```
Cliente deve reconectar com backoff exponencial. Frontend usa 1s → 15s teto + jitter. Ao reconectar, chama `GET /api/apuracao/atual` imediatamente pra evitar "buraco" de eventos.

## Sistema

### `GET /health`
`SELECT 1` + 200 OK se banco responde; 503 caso contrário.

## Modos de visualização do frontend

A mesma URL (`/`) adapta o layout automaticamente ao dispositivo:

- **Mobile** (≤768px): tabs de bottom nav (Placar/Mapa/Comparar/Eventos/Mais), stats sticky encolhendo ao scroll, chrome compacto.
- **Desktop** (769px+): layout clássico com hero + conteúdo em coluna.
- **TV / 10-foot UI**: ativado quando `navigator.userAgent` casa SmartTV/Tizen/WebOS/AndroidTV/Roku/consoles, OU manualmente via `?tv=1`. Dashboard com lista de candidatos à esquerda e mapa + gráfico + eventos à direita (todos visíveis ao mesmo tempo), fontes maiores, navegação por setas do controle remoto (Home/End/←→↑↓), sem elementos que exigem toque ou mouse (botões "comparar", filtros, CTAs). Testável em qualquer browser via `?tv=1`.
