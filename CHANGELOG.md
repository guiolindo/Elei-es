# Changelog

Histórico de mudanças relevantes. Formato inspirado em Keep a Changelog. Datas em ISO 8601 (BRT).

## [Unreleased]

## 2026-10-05 / 2026-10-06 — Dia D (1T) + transição pro 2T

### Corrigido
- **Motor — sub judice**: `qt_votos_validos` vinha direto do `v.vv` do TSE, que separa votos de candidato "Indeferido em prazo recursal" (Lei 9.504 art. 16-A: votos contam como válidos enquanto roda o recurso). Em RJ Gov 1T o motor declarou `ELEITO_MAJORITARIO` com "50,88%" quando o pct real era 49,27% (TSE já havia declarado 2T com Douglas Ruas × Eduardo Paes). Parser agora usa `max(TSE.vv, soma dos candidatos)`. Testes `test_parse_qt_votos_validos_inclui_sub_judice` + `_mantem_vv_quando_maior`. Correção retroativa via `POST /api/admin/corrigir-rj-gov-sub-judice`.
- **Motor — proporcional**: engine aplicava regra majoritária a cargos 6 e 7 com `vagas=1` default, emitindo `ELEITO_MAJORITARIO` + `MATEMATICAMENTE_ELIMINADO` falsos (candidato com AMBAS as tarjas verde eleito + vermelha eliminado). Early return `[]` em `avaliar_apuracao` pra `cod_cargo in (6, 7)`. Frontend `_absorverEventoNoState` filtra na mesma linha.
- **Presidente / abrangência UF**: eventos passavam a ser gerados pra alvos `(cargo=1, UF)` individuais (CF art. 77 §2º é nacional). Guard em `poller/service.py`. Presidente só avaliado em `abrangencia=BR`.
- **Telegram**: cache de notificações usava `ev["tipo"]` como chave → sempre enviava o mesmo nome quando múltiplos eventos do mesmo tipo. Chave corrigida pra `(tipo, sq_a, sq_b)`.
- **Mapa**: ECharts map series usa `itemStyle.areaColor` pro fill, não `color`. UFs não pintavam. Fixado em `mapa-br.js`.
- **Cards zerando**: `refreshApuracao` chamava `renderLista` depois de `atualizarPainelTotais`, que recriava templates com "0 votos" sem repreencher. Ordem invertida + `atualizarPainelTotais` no fim do `renderLista` pra garantir.
- **Comparação / margem matemática**: antes plotava `A.votos − (B.votos + B.restantes)` só, confundia (uma linha mesmo com 2 selecionados). Agora pra 2 selecionados mostra 1 linha com a margem do líder dinâmico; 3+ mostra uma linha por candidato. Rótulos "lidera/atrás no confronto" (durante apuração), "venceu/perdeu o confronto" (100% apurado) — não mais "venceu" absoluto, que confundia com vitória real da urna.

### Adicionado
- **Modo 2º turno**: toggle 1T/2T no header (desktop + mobile), countdown pro dia D 2T (26/10 17h BRT), state.turno persistido em URL + localStorage. Cargos filtrados por turno (`CARGOS_POR_TURNO = {1: [1,3,5,6,7], 2: [1,3]}` — só Pres e Gov têm 2T).
- **Env var `POLL_TURNO`**: `"1"`, `"2"` ou `"all"` (default). Permite desligar o polling do 1T entre 05/10 e 26/10/2026 sem perder dados históricos.
- **Todos os endpoints com `?turno=`**: `/api/apuracao/atual`, `historico`, `lideres-por-uf`, `lideres-por-municipio`, `proporcional`, `/api/eventos`, `/api/candidatos`.
- **`GET /api/segundo-turno/ufs-governador`**: lista distinct de UFs com evento `SEGUNDO_TURNO_DEFINIDO` em `cod_cargo=3`. Frontend usa pra esconder do dropdown de UF, no modo 2T + cargo Gov, estados decididos no 1T.
- **`POST /api/apuracao/popular-municipios?cargo=X&uf=Y&turno=Z`**: lazy populate on-demand do breakdown por município. O endpoint `{uf}-c{cargo}-e{el}-u.json` do TSE não traz `mu[]` pra nenhum cargo em 2026; dados municipais estão em arquivos individuais `{uf}{cod_tse}-c{cargo}-e{el}-u.json` (~5570 municípios). Puxa em paralelo (semáforo 40) direto do TSE e persiste em `SnapshotMunicipio`. TTL in-memory 15 min por `(cargo, uf, turno)`. Limpeza automática: só o snapshot UF mais recente retém dados municipais. Mapping TSE↔IBGE embarcado em `app/data/tse_municipios.json` (289 KB).
- **`POST /api/admin/corrigir-rj-gov-sub-judice`**: correção retroativa one-shot do falso-positivo descrito acima. Remove `ELEITO_MAJORITARIO` + `MATEMATICAMENTE_ELIMINADO` falsos e emite `SEGUNDO_TURNO_DEFINIDO` com Douglas Ruas × Eduardo Paes. Idempotente. Alternativa: `python -m scripts.corrigir_rj_gov_sub_judice`.
- **Modal de vitória + troféu**: `abrirModalVitoria(sq, cor)` — overlay fullscreen com troféu dourado pulsante, foto, nome, cargo, abrangência, % final. Dispara em `ELEITO_1T` / `ELEITO_MAJORITARIO` ao vivo pelo WS (canal-based, só pra quem está vendo aquele cargo+UF). Dismiss ✕ / ESC / backdrop / 25s.
- **Faixa persistente de vencedor**: `renderFaixaVencedor(eventos)` no topo da página quando o user NAVEGA pra um cargo já decidido (modal é one-shot ao vivo; faixa fica fixa).
- **TV 2T head-to-head**: layout grid-areas `mapa + side-top + side-mid + side-bot + eventos` com mapa dominante (1.8fr) + sidebar com 2 cards grandes empilhados, placar (DIFERENÇA + spread bar + TENDÊNCIA + progresso) e gráfico.
- **Comparação / 4º gráfico "Margem até vitória matemática"**: visualização independente das outras 3 (não mais uma cópia do "Votos absolutos"). Gradient verde (ganhando) → amarelo (fronteira) → vermelho (perdendo). Fronteira Y=0 em dashed amarelo.

### Alterado
- **Hierarquia visual nos cards**: `%` virou o hero (36px bold, cor do partido), `votos` secundário (13px muted). KPI da apuração é %, não votos absolutos.
- **Paginação**: lista de candidatos (quando >20) ganha paginador. Cascade entry desligado acima de 30 itens. `.candidato` com `contain: content; content-visibility: auto` + `atualizarPainelTotais` com índice 1-pass em vez de 4 × N querySelectors.
- **A11y**: touch targets 44px (WCAG 2.5.5), `:focus-visible` universal (WCAG 2.4.7), `prefers-reduced-motion` honrado em todas as novas animações.
- **Error states com retry**: `/api/candidatos` falhando → `.error-state` com botão "Tentar novamente".
- **Spread bar TV 2T**: com 0 votos mostrava 50/50 cheio (mentia "empate"). Agora: barra listrada neutra + "AGUARDANDO APURAÇÃO".

### Documentação
- README reescrito com estado atual: bot Telegram, mobile chrome, motor 3-fases pós-STF, senador 2 vagas em 2026.
- `ARCHITECTURE.md` — camadas, contratos internos, decisões arquiteturais.
- `AGENTS.md` — mapa "o que ler pra qual tarefa" pra IAs/devs.
- `docs/metodologia.md` — motor matemático completo com fontes primárias.
- `docs/operations.md` — Railway, admin token, Termux, Alembic, bot Telegram.
- `docs/getting-started.md` — setup dev local.
- `docs/api-reference.md` — endpoints REST + WebSocket.
- `docs/security.md` — LGPD, admin token, threat model.
- `docs/faq.md` — dev-facing (complementa `/sobre` público).
- `CREDITS.md` — dependências e atribuições.

## 2026-09-29

### Corrigido
- **Motor — bug grave**: `segundo_turno_definido` retornava falso positivo quando o líder ainda podia fechar 1º turno. Agora exige duas condições estritas (líder não pode fechar 1T + 3º não alcança 2º). Coberto por `test_segundo_turno_nao_definido_lider_pode_vencer_1t`.
- **Motor — Senador 2026**: `avaliar_apuracao` tratava senador como 1 vaga. Corrigido: renovação de 2/3 elege 2 por UF em 2026. Nova função `eleitos_majoritario_multivaga` retorna top-N eleitos.
- **Proporcional — pós Lei 14.211/2021 + STF ADI 7228/7263 (2024)**: implementadas 3 fases (QP direto + sobras 80/20 + residual sem barreira). Antes só QP + D'Hondt simples.
- **Proporcional — federações**: separação entre `votos_partido` (individual) e `votos_unidade` (federação inteira).
- **`detectar_viradas`**: virada fantasma quando aparecia candidato novo — corrigido com sentinel `len(pos_anterior)`.

### Adicionado
- **Bot do Telegram**: 13 comandos de consulta ao vivo (`/placar`, `/lider`, `/vs`, `/mapa`, `/candidato`, etc.) + wizard de assinaturas (`/assinar`, `/minhas`, `/pausar`, `/silencio`). Long polling em asyncio Task. Migração 0004 com tabelas `telegram_subs` e `telegram_chat_config`.
- **Mobile chrome dedicado**: bottom nav com 5 abas, chips de cargo/UF, bottom sheet, FAB de comparar. Zero framework.
- **Design system**: motion tokens, ícones SVG unificados (sprite), logo próprio, honra `prefers-reduced-motion`.
- **Página `/sobre`** com FAQ (10 perguntas), termos, LGPD, bases legais, metodologia.
- **Endpoint `/health`** — SELECT 1 no banco.
- **`ADMIN_TOKEN`** protegendo todos os endpoints `/api/admin/*`.

### Alterado
- Confete + banner + beep ao ELEITO_1T / ELEITO_MAJORITARIO.
- Título dinâmico da aba (`Lula 52% · 68% apurado`).
- Compartilhar via Web Share API + URL restauradora de estado.
- Countdown compacto pro dia D em faixa fininha.
- Prefs salvas em `localStorage` (cargo, UF, filtros, tab ativa).
- Card do candidato redesenhado: 3 blocos verticais (topo + métricas + rodapé) com 2 botões explícitos "＋ comparar" / "ver ficha →". Zero `position: absolute`.
- Cache-Control público em `/api/apuracao/*`.
- WS com backoff exponencial + jitter.

## 2026-09-28

### Adicionado
- Motor proporcional inicial (QE + D'Hondt + barreira 10% + federações).
- Sincronização de candidatos via Termux (curl-cffi + IP residencial BR).
- Modal de detalhes do candidato.
- Mapa geográfico real (GeoJSON) com ECharts.
- Colorização por candidato líder por UF e por município.

## 2026-09-27

### Adicionado
- Setup inicial no Railway.
- Motor matemático básico (eleito 1T, 2t definido, majoritário simples).
- Frontend com comparação lado a lado de 4 candidatos.
- WebSocket + polling do TSE.

## 2026-09-26

### Adicionado
- Projeto criado.
- Schema inicial (candidatos, snapshots, eventos, comparações).

