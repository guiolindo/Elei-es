# Architecture

Documento de decisões arquiteturais e contratos internos. Complementa o `README.md` (visão geral) e a `docs/metodologia.md` (motor matemático em detalhe).

## Princípios de design

1. **Motor matemático puro**. `math_engine/` não importa nada de `app/`, `poller/` ou `notif/`. Só dataclasses e Python padrão. Isso permite 44 testes unitários rodando em 0.2s e reuso do motor no bot Telegram sem circular imports.
2. **Desigualdade estrita em tudo**. Se ainda existe cenário de empate exato, o resultado fica "em disputa". Erro pra menos (chamar tarde) é preferível a erro pra mais (chamar cedo).
3. **Conservador no `votos_restantes_max`**. Usa `eleitorado_apto − apto_totalizadas` como upper bound. Na realidade ~20% se abstém e ~10% dos válidos vira branco/nulo, mas o motor não presume — é matematicamente seguro.
4. **Snapshots idempotentes e auditáveis**. Cada snapshot tem `hash_conteudo` SHA-256 do JSON bruto do TSE. Deduplicação por esse hash. Terceiros podem verificar que o site exibiu exatamente o que o TSE publicou.
5. **Snapshots suspeitos são marcados, não descartados**. Se `qt_secoes_totalizadas` retrocede (TSE reprocessando seção), o snapshot vai com `suspeito=True` e não dispara eventos.
6. **Frontend zero-framework**. HTML/CSS/JS vanilla + ECharts (CDN). Nenhum build step, nenhum bundler. Simplicidade de deploy no Railway compensa a ausência de reactividade automática.

## Camadas e fluxo de dados

```
                                                             ┌───────────────┐
                                                             │  TSE (JSONs)  │
                                                             └───────┬───────┘
                                                                     │
                                        ┌────────────────────────────┼─────────────────────────────┐
                                        │                            │                             │
                                        ▼                            ▼                             ▼
                             /resultados.tse (apuração)  /divulgacandcontas (fichas)     /divulga (fotos)
                                        │                            │                             │
                                        │                            │                             │
     ┌──────────────────────────────────┴─────┐                     (via Termux com curl-cffi
     │  poller.service.loop()                 │                      pra bypass Akamai)
     │    a cada 20s, semáforo(6), gather     │
     │    baixa, hash SHA-256, dedup,         │
     │    parser, persiste Snapshot +         │
     │    SnapshotTotais + SnapshotCandidato  │
     │    + SnapshotMunicipio (quando existe) │
     └──┬──────────────────┬──────────────────┘
        │                  │
        │                  ▼
        │       math_engine.avaliar_apuracao(cands, totais, cargo)
        │            └─ pct_apurado ≥ 20%? sim → eleito_1t / 2t_definido / majoritario / eliminado
        │                                        detectar_viradas(atual, anterior)
        │                                        emite eventos
        │
        │       persiste em `eventos` (dedup por tipo+sq_a[+sq_b])
        │
        ├────────► app.ws.broadcaster.broadcast(cargo, abr, {snapshot, eventos})
        │              ├─► WS clients (frontend abre por [cargo, abrangencia])
        │              └─► frontend renderiza + toast + confete se eleito
        │
        └────────► notif.telegram_bot.enviar_notificacoes(eventos, cargo, abr)
                       ├─► match (cod_cargo, abrangencia, tipo) com telegram_subs
                       ├─► respeita telegram_chat_config.pausado_global + silêncio BRT
                       └─► sendMessage por chat
```

Todos os módulos são acionáveis também via API HTTP:
- `poller` roda via lifespan do FastAPI, ou manualmente com `python -m poller.once`.
- `math_engine` é chamado pelo endpoint `/api/apuracao/proporcional` on-demand.
- `notif` sobe se `TELEGRAM_BOT_TOKEN` estiver setado; se não, fica desligado sem erro.

## Contratos internos (dataclasses e schemas)

### `math_engine.engine`

```python
@dataclass(frozen=True)
class CandidatoResumo:
    sq_candidato: str
    votos: int

@dataclass(frozen=True)
class TotaisResumo:
    qt_secoes_total: int
    qt_secoes_totalizadas: int
    qt_eleitorado_apto: int
    qt_eleitorado_apto_totalizadas: int
    qt_votos_validos: int
```

Todas as funções principais aceitam `Sequence[CandidatoResumo]` — não precisam ser ordenadas, o motor ordena internamente. As funções internas (`matematicamente_eliminado`, `virada_iminente`, `margem_de_seguranca`) têm fast path que evita re-sort quando a Sequence já vem ordenada.

Constante `VAGAS_MAJORITARIO_PADRAO`:
```python
{
    1: 1,   # Presidente
    3: 1,   # Governador
    5: 2,   # Senador em 2026 (renovação de 2/3 = 2 por UF)
}
```

Eventos emitidos por `avaliar_apuracao`:
- `ELEITO_1T` — Presidente eleito no 1º turno.
- `SEGUNDO_TURNO_DEFINIDO` — top 2 pra 2T está fechado.
- `ELEITO_MAJORITARIO` — Governador eleito, ou senador multi-vaga (emite 1 por vaga fechada).
- `MATEMATICAMENTE_ELIMINADO` — candidato fora do top-N.
- `VIRADA` — mudança de posição no top-5 entre snapshots consecutivos.

### `math_engine.proporcional`

Entrada: lista de `CandidatoProporcional(sq_candidato, nome_urna, numero, partido_numero, votos)`, vagas do cargo (`VAGAS_DEP_FEDERAL[uf]` ou `vagas_dep_estadual(uf)`), opcional `votos_legenda_por_partido` e `federacoes`.

Saída: `ResultadoProporcional` com QE, lista de candidatos com status (`eleito`, `suplente`, `nao_atingiu_barreira`, `partido_sem_vaga`) e lista de partidos com `votos_partido`, `votos_unidade`, `vagas_qp`, `vagas_sobras`, `passou_qe`, `passou_80_qe`.

Ver `docs/metodologia.md` pra formalização das 3 fases.

### Modelo de dados

12 tabelas em `app/models.py`, todas com SQLAlchemy 2 declarative:

| Tabela | Papel |
|---|---|
| `cargos` | 5 cargos (Presidente, Gov, Sen, Dep Fed, Dep Est) |
| `ufs` | 27 UFs com código IBGE |
| `partidos` | Partidos registrados (idempotente via `on_conflict_do_update`) |
| `candidatos` | Ficha do candidato + `raw_divulga JSONB` (todo o payload do TSE) |
| `snapshots` | Coleta bruta indexada por (cargo, abr, coletado_em); `hash_conteudo` único |
| `snapshot_totais` | Totais por snapshot (seções, comparecimento, brancos/nulos) |
| `snapshot_candidato` | Votos por candidato por snapshot |
| `snapshot_municipio` | Breakdown por município quando o JSON traz `abr[].mu[]` |
| `eventos` | Timeline de eventos matemáticos (dedup por tipo+A[+B]) |
| `comparacoes` | Analytics: quais candidatos são comparados juntos (session-scoped) |
| `push_subscriptions` | Web Push endpoints anônimos |
| `telegram_subs` | Assinatura de alerta (chat_id × cargo × abr → tipos_evento JSONB) |
| `telegram_chat_config` | Config por chat (pausa, janela de silêncio BRT) |

## Padrões operacionais

### Rate limit e admin token

- **Global**: slowapi com `100/min` por IP em todos os endpoints (configurado em `app.main`).
- **Admin**: dependency `_exigir_admin` verifica header `X-Admin-Token` contra `settings.admin_token`. Aplicado automaticamente em todas as 8 rotas `/api/admin/*`. Se `ADMIN_TOKEN` estiver vazio (dev), libera.

### CORS

`settings.cors_origins` é comma-separated. Default `http://localhost:8080`. Em prod, setar pra URL pública do Railway.

### Poller resiliente

- Timeout 20s por request, `httpx.AsyncClient` reaproveitado.
- Erro em 1 alvo (ex.: SP falhou) não afeta outros — cada alvo é try/except isolado.
- Semáforo(6) limita paralelismo pra não estourar rate limit do TSE.
- Snapshots duplicados (mesmo hash) são silenciosamente ignorados.
- Snapshots suspeitos gravados com `suspeito=True` — não disparam evento nem broadcast.

### WebSocket

- Endpoint `/ws/apuracao?cargo=X&abrangencia=Y`.
- Broadcaster mantém set de conexões por (cargo, abr). Broadcast só envia pros clients daquela combinação — não flooda.
- Cliente tem reconnect com backoff exponencial + jitter (1s → 2s → 4s → 8s → 15s teto). Ao reabrir, dispara `refreshApuracao()` pra pegar dados perdidos.

### Cache-Control público

Middleware HTTP adiciona `Cache-Control: public, max-age=3, s-maxage=5, stale-while-revalidate=15` em GETs de `/api/apuracao/*`. Isso reduz carga no banco no pico da noite. WebSocket continua tempo real; cache é só fallback pra HTTP polling.

## Decisões arquiteturais

### Por que Railway e não Fly?

Railway roda em SP e passa pelo Akamai do TSE como IP BR (funciona pra `resultados.tse.jus.br`). Fly.io tem worker em regiões que caem no bloqueio. Além disso, deploy do Railway é mais simples (Postgres plugin automático, envs, healthcheck).

### Por que Cloudflare Worker como fallback?

`divulgacandcontas.tse.jus.br` bloqueia até o Railway. Um Worker Cloudflare em SP (roteável como CDN residencial) foi tentado, mas o Akamai ainda bloqueia. Solução final: `scripts/importar_termux.py` roda do celular do usuário (IP residencial BR) com curl-cffi.

### Por que não React/Vue?

Vanilla JS + ECharts + WebSocket cobre 100% do escopo em ~1200 linhas. Zero build step, zero cache-busting, zero framework upgrade. Deploy do Railway serve arquivos estáticos com mesma origem, evitando CORS.

### Por que long polling no bot em vez de webhook?

Setup de webhook exigiria certificado válido, endpoint público específico, e sync com o Railway. Long polling roda como uma task asyncio dentro do mesmo processo do FastAPI, compartilha `SessionLocal` do banco, e não precisa de infra extra. Trade-off: consome 1 conexão HTTP contínua com api.telegram.org. Aceitável.

### Por que motor matemático puro (não em SQL)?

- Testabilidade: 44 testes puros rodam em 0.2s.
- Auditável: alguém pode ler `engine.py` e verificar as fórmulas contra o Código Eleitoral em 5 minutos.
- Reuso: o bot Telegram chama as mesmas funções sem duplicar lógica.

## Gotchas conhecidos

- **Snapshot não-monotônico**: TSE pode reprocessar seção → `qt_secoes_totalizadas` diminui. O motor detecta e marca `suspeito`. Snapshots suspeitos não disparam eventos nem broadcast; ficam persistidos pra auditoria.
- **Fase 3 do STF elege candidato <10% QE**: intencional. Ver `docs/metodologia.md` §Fase 3.
- **Senador multi-vaga**: 2026 é ano de renovação 2/3 = 2 vagas por UF. `VAGAS_MAJORITARIO_PADRAO[5] = 2`. Anos de 1/3 (2018, 2022) precisam passar `vagas_majoritario=1` explicitamente.
- **Federações mudam entre eleições**: default hardcoded reflete 2022. Se 2026 mudar, passar `federacoes=...` na chamada.
- **Admin token vazio em dev libera admin**: intencional, mas em prod é ERRO grave — sempre setar.
