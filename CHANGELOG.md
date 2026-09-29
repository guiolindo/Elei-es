# Changelog

Histórico de mudanças relevantes. Formato inspirado em Keep a Changelog. Datas em ISO 8601 (BRT).

## [Unreleased]

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

