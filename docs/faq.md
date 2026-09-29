# FAQ técnica (dev-facing)

FAQ pra desenvolvedores e mantenedores. A FAQ do usuário final (com linguagem acessível, explicando conceitos eleitorais) está em `static/sobre.html` seção "Perguntas Frequentes", servida em `/sobre#faq`.

## Motor matemático

### Por que desigualdades estritas em tudo?

Porque `≥` deixa a porta aberta pra empate exato. Se `b.votos + restantes == a.votos`, um empate ainda é possível no fim — o TSE precisa recontar. Chamar "eleito" nessa situação é um erro potencialmente catastrófico. Preferimos chamar tarde do que errado.

### Por que o motor só corre depois de 20% apurado?

Antes disso, `votos_restantes_max` é enorme (pouca coisa apurada = muito eleitorado sem votar computado). Qualquer desigualdade que use `restantes_max` fica trivialmente aberta. Rodar o motor com 5% apurado seria puro barulho — nenhum evento fecharia, mas gastaria CPU comparando snapshots. 20% é o threshold onde as fórmulas começam a fechar em casos reais.

### Por que usar `eleitorado_apto` como upper bound e não `expected_comparecimento`?

Porque é matematicamente seguro. Em 2022 a abstenção foi 20,9%; se usássemos 80% do eleitorado como upper, poderia falhar quando o comparecimento for maior (ex.: eleição municipal onde as pessoas votam mais). Ser conservador significa nunca chamar errado — a única penalidade é chamar alguns snapshots depois do que seria estritamente necessário.

### Como o motor lida com snapshots "não-monotônicos" (TSE reprocessando)?

`poller/service.py` compara `qt_secoes_totalizadas` com o snapshot anterior. Se diminui, marca `suspeito=True`. Snapshots suspeitos são persistidos (pra auditoria) mas não disparam eventos nem broadcast WebSocket. Também não contam pra "último snapshot" das queries.

### O que acontece se um candidato aparecer do nada num snapshot novo?

`detectar_viradas` usa sentinel `len(pos_anterior)` (posição virtual "atrás de todos") pra SQs inéditos. Isso evita virada fantasma — o candidato novo não é tratado como se estivesse à frente antes. Regressão coberta em `test_detectar_virada_ignora_candidato_novo_no_snapshot_atual`.

### E se o TSE mudar o schema JSON entre eleições?

Os parsers (`poller/parser.py`, `poller/candidatos_tse.py`, `app/api.py::ficha`) usam `_pick(*keys)` com múltiplos aliases (`sqCandidato`, `sq_candidato`, `id`, ...). Tolerantes por design. Se um campo novo aparecer, adicionar ao `_pick`. Se um campo mudar de tipo, adicionar coerção.

## Coleta e TSE

### Por que dois endpoints diferentes do TSE?

- `resultados.tse.jus.br` — apuração ao vivo (JSONs com totais e votos). **Sem Akamai**, Railway acessa direto.
- `divulgacandcontas.tse.jus.br` — ficha dos candidatos, fotos, dados biográficos. **Com Akamai**, backend fora do BR toma 403. Solução: coleta manual do Termux (celular do usuário com IP residencial BR).

### O que acontece se `resultados.tse.jus.br` também ativar Akamai?

Cenário nunca ocorreu, mas se acontecer: adicionar Cloudflare Worker em SP como proxy, ou implementar `POST /api/admin/importar-snapshot` recebendo snapshots do Termux.

### Como sei se o TSE liberou os códigos definitivos da eleição?

`poller/descoberta.py` roda a cada 5 min e tenta descobrir automaticamente. Enquanto o TSE não publica, o app usa os defaults do `.env`. Quando publica, o config em memória é atualizado sozinho.

### Por que `raw_divulga JSONB` na tabela candidatos?

Guarda TODO o payload do TSE — futuro-prova. Se o TSE adicionar um campo (ex.: `dataDiplomacao`), não precisamos re-sincronizar todos os candidatos: basta ajustar o `/api/candidato/{sq}` pra ler do JSONB existente.

## Frontend

### Por que sem framework?

Escopo cabe em ~1200 linhas de JS puro. Sem build step significa deploy simples no Railway (arquivos servidos pelo próprio FastAPI). Sem framework significa upgrade zero-effort.

### Por que só animar `transform` e `opacity`?

São as únicas propriedades que rodam no GPU compositor thread (não passam por layout/paint). Isso garante 60fps mesmo em dispositivos low-end. Animar `width`, `height`, `top`, `background`, etc. força reflow/repaint e trava. Regra vale pra qualquer código no projeto.

### Por que o mapa esticado foi corrigido com `aspectScale: 1`?

O default do ECharts é `aspectScale: 0.75` (compensa distorção da projeção Mercator perto do equador). Como o container do mapa tinha aspect ratio próximo de 1:1, o mapa achatado do ECharts ficava esticado verticalmente. Trocar pra `aspectScale: 1` preserva a proporção real do GeoJSON.

### Por que o desktop e o mobile compartilham CSS?

Dois chromes visuais separados, mas mesmo state e mesmo JS. Media query `(max-width: 768px)` esconde chrome desktop e mostra mobile. Um único stateful controller (state global) alimenta os dois — mudar cargo no chip mobile sincroniza o `<select>` desktop.

## Bot Telegram

### Por que long polling em vez de webhook?

Long polling roda como task asyncio dentro do mesmo processo do FastAPI. Compartilha `SessionLocal`. Não precisa de infra extra (webhook exigiria endpoint público específico, TLS válido, etc.). Trade-off aceito: 1 conexão HTTP contínua com `api.telegram.org`.

### Como escalar o bot pra múltiplas réplicas?

Long polling não escala. Se subir >1 réplica, ambas pegam updates duplicados. Soluções:
1. Trocar pra webhook — 1 endpoint recebe POST, banco de fila com Redis.
2. Só uma réplica processa bot (lock no banco).

Hoje o app roda em 1 réplica no Railway; não é problema.

### O que faz o `_send` retornar sem enviar?

Se `TELEGRAM_BOT_TOKEN` está vazio, `_api_base()` retorna None e `_api` retorna dict vazio. Zero side-effect. Rodar o app sem bot Telegram é OK.

## Arquitetura

### Por que Railway e não Fly / AWS / GCP?

Railway roda em SP, passa pelo Akamai do TSE. Fly.io tem workers em regiões que caem no bloqueio. AWS/GCP exigem setup mais complexo. Railway custa ~$5-10/mês, tem Postgres integrado, healthcheck automático.

### Por que Python e não Node/Go?

Ecossistema científico (numpy/scipy) útil pro motor. FastAPI é excelente pra APIs assíncronas com pouca cerimônia. Time do projeto (1 dev) prefere Python.

### Por que 4 migrations Alembic separadas?

Uma por feature. Facilita reverter uma mudança específica sem afetar as outras. Ver `alembic/versions/`.

## Legal

### Podemos usar as fotos dos candidatos?

Sim. LGPD art. 4º III excluí dados tratados pra fins jornalísticos/informativos. Candidatos a cargo eletivo são pessoas públicas em contexto de exposição voluntária. As fotos são publicadas pelo próprio TSE em endpoint público.

### Podemos usar os logos dos partidos?

Sim, uso nominativo. Lei 9.279/1996 permite uso de marca pra identificar produto/entidade sem endosso. Logos usados apenas pra identificar candidato → partido, sem vínculo comercial ou associativo.

### Precisa do disclaimer "não é o TSE"?

Sim. Está no rodapé de todas as páginas + no `/sobre`. Divergências entre o site e o TSE resolvem-se a favor do TSE.

### Podemos exibir resultado antes do TSE fechar?

Sim, desde que a fonte seja transparente (TSE) e o hash SHA-256 permita verificação. A Constituição garante liberdade de informação (art. 5º XIV + 220).
