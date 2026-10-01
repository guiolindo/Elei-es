# PLANO — próximas rodadas

Documento vivo com o backlog priorizado. Atualiza a cada sessão. Foco:
o que ainda falta pro dia D (04/10/2026) e o que pode esperar.

## Status atual (30/09/2026)

Backend maduro:
- Poller multi-cargo (Presidente + Governador + Senador + Dep. Federal + Dep. Estadual) rodando com 2 códigos TSE distintos (6257 federal / 6259 estadual), descoberta automática.
- Parser tolerante lendo `s/e/v` como dicts (bug crítico corrigido).
- Endpoints on-demand: `/api/apuracao/municipio` e `/api/apuracao/zona` com cache 45s em memória (mapa não pesa no banco).
- Retenção enxuta: cleanup a cada 1h mantém 200 snapshots por chave (~50 MB total previstos).
- Self-heal de `partido_numero` no startup (fix histórico do senador sem logo).
- Cache-busting em `app.js`/`app.css` via `?v=<mtime>` — fixes de frontend chegam sem hard-reload.
- Motor matemático completo: presidente/governador unificados (art. 77 CF), 2º turno com desempate por idade (art. 110 CE), sobras em 3 fases (QP → 80/20 → residual STF).
- 55 testes passando em 0.15s.
- Documentação: README, ARCHITECTURE, AGENTS, CHANGELOG, docs/metodologia, docs/security, docs/operations, docs/api-reference, docs/faq.

## Auditoria externa de 30/09/2026 — veredictos

Uma auditoria técnica foi feita por outra IA. Verifiquei cada bug
contra o código real. Resumo:

| Bug alegado | Veredicto | Status |
|---|---|---|
| BUG-01 (API ignora votos de legenda) | **Verdadeiro** | Pendente — fix no parser + API |
| BUG-02 (federações desativadas) | **Falso** | Motor usa `FEDERACOES_2026_DEFAULT` quando API passa None; as 5 federações estão lá (BRASIL ESPERANCA, PSDB CIDADANIA, PSOL REDE, UNIÃO PROGRESSISTA, RENOVAÇÃO SOLIDÁRIA) |
| BUG-03 (QE arredonda 0,5 pra cima) | **Verdadeiro** | ✅ **Corrigido** — divmod + `2*r > vagas` (sem float) |
| BUG-04 (vaga QP vira eleição < 10%) | **Falso** | Código já faz `min(vagas_teoricas, passam_barreira)`; o que a auditoria chamou de "eleição abaixo de 10%" é a Fase 3 residual STF (ADI 7228/7263), legalmente correta |
| BUG-05 (desempates proporcionais) | **Verdadeiro** | ✅ Parcialmente corrigido — desempate por maior votação da unidade (produto cruzado em `_MediaKey`). Desempate por idade entre candidatos ainda pendente |
| BUG-06 (float em médias) | **Verdadeiro** | ✅ **Corrigido** — `_MediaKey` compara por produto cruzado em inteiros |
| BUG-07 (senador empate idade) | **Verdadeiro** | Pendente — depende de ter `data_nascimento` no modelo |
| BUG-08 (idade só em anos) | **Verdadeiro** | Pendente — mesma dependência de BUG-07 |

Novos testes adicionados cobrindo QE em todas as franjas (0.5 exato,
> 0.5, < 0.5, exato sem fração). Suíte: **59 testes passando**.

## P0 — antes do dia D (04/10)

### 1. Frontend do mapa consumindo os endpoints novos
- [ ] `bootMapa()` em `app/static/app.js`: renderizar mapa SVG do Brasil por UF (fill = cor do partido líder na UF)
- [ ] Ao clicar UF → carrega municípios via `/api/apuracao/municipio` em batch (max 20 paralelos, com `Promise.all` limitado)
- [ ] Ao clicar município → carrega zonas via `/api/apuracao/zona`
- [ ] Loading skeleton por camada
- [ ] Legenda com cor de cada líder possível

Estimativa: 4-6h. Bloqueador: SVG do Brasil (usar `simplemaps` ou similar, ~30 KB).

### 2. Teste do dia D — carga sintética
- [ ] Simular 500 conexões WS simultâneas + 100 req/s no `/api/apuracao/atual`
- [ ] Verificar rate limit (100/min por IP — pode precisar afrouxar pra 300/min)
- [ ] Confirmar autovacuum tuning da migration 0005 tá segurando

Estimativa: 2h. Rodar `locust` ou script `asyncio` no scratchpad.

### 3. Ajuste de cadência no dia D
- [ ] `_cleanup_snapshots_loop`: no dia D reduzir de 1h pra 15min (mais fluxo)
- [ ] `poll_interval_seconds`: manter 20s até 17h de domingo, subir pra 10s durante apuração
- [ ] Considerar `POLL_INTERVAL_APURACAO=10` como env var separada

Estimativa: 1h. Preferir env vars sobre hardcode.

### 4. Candidatos que desistiram / foram cassados aparecem como normais
Pergunta do usuário: Leonardo Avalanche (número 28, cargo 1) desistiu
da candidatura. O que o sistema faz? Hoje:
- Parser só filtra `descricaoSituacao=indeferido` sem recurso
- `renunciou`, `cancelado`, `cassado` passam direto como candidato ativo
- Se receber votos no dia D (vai receber — eleitor pode não saber),
  aparece no ranking, pode até ser marcado "eleito" se tiver muito voto
- Nenhuma tag visual indica que ele saiu da disputa

Impacto jurídico: Lei 9.504/97 art. 175 §3º — votos em candidato com
registro cancelado após convenção são considerados **nulos** na
apuração oficial. O sistema não implementa isso.

Fix necessário (maior, ~3h):
- [ ] Migration: coluna `situacao` em `candidatos` (`ativo | renunciou |
  cancelado | indeferido_sem_recurso | cassado`)
- [ ] `parse_candidato`: lê `descricaoSituacao` do divulga e popula
- [ ] `sincronizar_candidatos`: também atualiza situacao em candidatos
  já existentes (TSE pode mudar depois de registrado)
- [ ] Motor (`avaliar_apuracao`): exclui candidatos com situacao não
  ativa do cálculo de "eleito" e "2º turno". Votos aparecem no total
  mas candidato não ganha nada.
- [ ] UI: badge vermelha "CANDIDATURA RETIRADA" + foto grayscale,
  distinta da tarja "matematicamente eliminado". Linha explicando
  que os votos nele são nulos por lei.
- [ ] Testes: cenário "candidato retirado com 60% dos votos não é eleito"

### 5. Tarja de proporcional mentindo pré-apuração
Reportado 01/10/2026 via screenshot. Antes da apuração começar, cards
de Dep. Estadual GO mostram:
- Ana Carolina (Republicanos) → "PARTIDO S/ VAGA"
- Ana Carol (PT) → "SUPLENTE · FED."
- Carol do Amiltinho (MDB) → "PARTIDO S/ VAGA"

Todas com 0 votos. Os status vêm do motor rodando com votos_validos=0:
QE=0, barreira=0, ninguém ganha vaga real, mas candidatos de federação
são marcados "suplente · fed" porque entram na lista federativa unificada
e os de partido isolado viram "partido_sem_vaga". **A tarja mente**:
sugere que a candidata do PT está em posição diferente da do Republicanos,
quando na verdade ninguém tem voto.

Fix: `apuracao_proporcional` retorna `disponivel: false` quando
`votos_validos = 0` (ou `pct_apurado = 0`). Frontend então não desenha
badge. Mesma lógica do título da aba — nada de status até haver apuração
real.

Estimativa: 15 min.

### 6. Voto do exterior (abrangência "ZZ")
- Só vota presidente no exterior (CF art. 14 §1º c/c LC 44/82)
- Eleitorado ~1 M em 2026 (consulados). Já ESTÁ incluído no total BR
  — mas o TSE publica corte separado como UF virtual "ZZ":
  `resultados.tse.jus.br/oficial/ele2026/6257/dados/zz/zz-c0001-e006257-u.json`
- [ ] Poller: adicionar "ZZ" aos `ufs` quando cargo=1
- [ ] API/`/apuracao/atual`: suportar `abrangencia=ZZ` (já funciona de
  graça — tabela genérica)
- [ ] Frontend: chip "Exterior" no seletor de UFs, visível só quando
  cargo=presidente
- Volume: 1 chave extra × 200 snapshots retidos = ~5 MB. Desprezível.
- Estimativa: 15 min.

### 7. Timestamp de "gerado_em_tse" visível na UI
- Info já vem na API (`gerado_em_tse`, `coletado_em`) — só falta subir pra tela
- Ajuda o usuário entender divergências entre níveis (BR × UF × município) que são naturais no dia D (TSE gera cada arquivo em momentos diferentes)
- Estimativa: 15 min. Discricionário do designer.

### 8. Página `/urna` — verificação de boletim de urna
Dá pra desenvolver antes da eleição usando BUs de 2024 como ground truth.
BUs de eleições passadas continuam online no S3 do TSE, então testes
automatizados funcionam hoje.

- [ ] Endpoint `/api/apuracao/bu?uf=SP&mun=71099&zn=130&se=1` com cache 60s
- [ ] Parser do JSON assinado do TSE (estrutura: seção → candidato → votos + hash)
- [ ] Página `/urna` com formulário (UF/mun/zona/seção) + card estilo boletim físico
- [ ] Validação da assinatura ICP-Brasil (offline, cadeia pública do TSE)
- [ ] Testes contra BUs reais de 2024 (`ele2024/545/dados/sp/...`)

Riscos que só se confirmam depois de 04/10:
  - TSE ajustar campos do JSON entre eleições (mitigar com parser tolerante `_pick`)
  - AC do TSE renovar certificados (5 linhas de config no dia D)
  - Rate limit agressivo do `dados_bu_imgbu` no dia D (aumentar cache pra 5min)

Estimativa: 8h. Feature isolada, não bloqueia outros trabalhos.

## P1 — nice-to-have pré-eleição

### 5. Notificações push do resultado final
- Já tem infra VAPID + `PushSubscription` no banco
- Falta o gatilho quando `pct_apurado >= 99.5` E vencedor definido
- Copy da notificação: "Fulano eleito Presidente com X% dos votos"
- Estimativa: 3h.

### 6. Bot do Telegram — comando `/mapa <UF>`
- Retorna o líder de cada município como texto (top 5 municípios)
- Reusa endpoint on-demand
- Estimativa: 2h.

## P2 — pós-eleição

### 7. Análise histórica
- Página `/historico` comparando 2022 vs 2026 (se tivermos dados de 2022 importados)
- Requer sincronizar candidatos de 2022 no divulga
- Estimativa: 6h.

### 8. Export CSV/JSON dos resultados
- Endpoint `/api/apuracao/export?cargo=X&formato=csv`
- Para pesquisadores, jornalistas
- Estimativa: 2h.

### 9. Rate limit por API key (não só IP)
- Se abrir a API pra terceiros, precisa key
- Estimativa: 3h.

## Débitos técnicos identificados

- `poller/service.py` tem lógica de retry acoplada ao loop principal — poderia virar decorator.
- `notif/telegram_bot.py` está com ~750 linhas em um arquivo só — funciona, mas revisitável.
- Tests não cobrem os endpoints on-demand novos (`/municipio`, `/zona`) — mockar TSE e adicionar.
- `alembic/versions` tem 5 migrations — se ficar muitas mais, considerar squash pré-produção.

## Contas de capacidade (referência rápida)

Railway Postgres Hobby = 8 GB.

Volume real esperado com retenção enxuta:
- Snapshots: ~200/chave × ~110 chaves (1 presidente + 27 UFs × 4 cargos) × ~30 KB = **~660 MB**
- Candidatos: ~30 mil × 3 KB = **~90 MB**
- Eventos + comparações + subscriptions: **~50 MB**
- Total: **~800 MB** — folga confortável de 7 GB.

Sem cleanup, seria ~30 GB só nos snapshots do dia D.

## Contatos e recursos

- Fontes primárias: `resultados.tse.jus.br/oficial/ele2026/` e `divulgacandcontas.tse.jus.br`
- Doc jurídica: `docs/metodologia.md` (links pra CF/CE/STF)
- Import manual do Termux quando divulgacandcontas bloqueia Railway: `scripts/importar_termux.py`
- Session Claude atual: https://claude.ai/code/session_019SvYDZmwHD39tVfjSPYDWk
