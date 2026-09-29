# Security & LGPD

Superfícies de ataque e proteções em vigor.

## Threat model

Este site expõe **dados públicos** (apuração do TSE) — não há informação sensível ou proprietária a proteger. As principais ameaças são:

1. **Vandalismo/DoS** nos endpoints admin — atacante limpar candidatos, injetar dados.
2. **Scraping abusivo** — bots martelando `/api/apuracao/*` a cada 100ms.
3. **DDoS** volumétrico no pico da noite eleitoral.
4. **Manipulação de conteúdo** — alguém alegar que o site exibiu resultado diferente do TSE.

## Proteções em vigor

### Admin token
Todos os endpoints `/api/admin/*` exigem header `X-Admin-Token: <valor>`. Sem match, 401. Configurado via `ADMIN_TOKEN` env var (dep. em `_exigir_admin` aplicada a todas as 8 rotas admin).

**Se o token estiver vazio (dev), libera.** Sempre setar em produção. Rotacionar se vazar.

### Rate limit
slowapi com `100/min` por IP global. Endpoints admin poderiam ter limite menor, mas o token já os protege.

### CORS
`CORS_ORIGINS` env var define hosts permitidos. Setar pra URL pública do Railway.

### Cache-Control
`GET /api/apuracao/*` retorna `Cache-Control: public, max-age=3, s-maxage=5, stale-while-revalidate=15`. Isso permite CDN/browser cachearem por poucos segundos — reduz carga no pico sem comprometer o "ao vivo".

### Hash SHA-256 dos snapshots
Cada `snapshots.hash_conteudo` guarda o SHA-256 do JSON bruto do TSE. Exposto em `/api/apuracao/atual`. Qualquer um pode baixar o JSON do TSE, calcular o SHA, e verificar contra o hash do site — prova criptográfica de que exibimos o que o TSE publicou.

### CSP
`static/index.html` declara Content-Security-Policy restringindo scripts a `self + cdn.jsdelivr.net`, styles a `self + fonts.googleapis.com`, imgs a `self + divulgacandcontas.tse.jus.br`.

### Sem PII no site
Não há login. Não há sessão. Não há cookies de rastreio. `localStorage` guarda apenas preferências de UI (cargo, UF, filtros, tab ativa). Web Push registra um endpoint anônimo do navegador — sem IP, sem nome.

### PII mínima no bot Telegram
Coletamos:
- `chat_id` (número gerado pelo Telegram — não é telefone, não é nome).
- Assinaturas (cargo, UF, tipos de evento).
- Configuração (pausa, janela de silêncio).

**Não coletamos** nome, email, telefone, foto de perfil, mensagens fora do bot.

**Base legal LGPD**: art. 7º I (consentimento — o usuário inicia interação voluntariamente) e IX (legítimo interesse pra executar o serviço).

**Retenção**: os dados ficam enquanto a assinatura existir. `/apagar_tudo` remove todas do chat. Deletar a conversa deixa o registro órfão até limpeza periódica.

**Compartilhamento**: nenhum. Zero terceiros, zero analytics externos.

## Auditoria

Toda alteração ao banco via endpoints admin deve ser justificável. Logar (via logger padrão do Python) cada:
- Chamada a `/api/admin/limpar-seed` (destrutiva).
- Erro 401 em admin (tentativa de acesso).
- Snapshot marcado suspeito (regressão).

Logs vão pro stdout — Railway retém por padrão 30 dias.

## LGPD — direitos do titular (art. 18)

Usuários do bot podem exercer via:

- **Consulta** — comando `/minhas`.
- **Correção** — refazer assinatura com `/assinar`.
- **Anonimização/eliminação** — `/apagar_tudo` remove todas as assinaturas. Deletar a conversa do Telegram acaba com o histórico da interação.
- **Portabilidade** — pedir por email; export JSON manual das linhas de `telegram_subs` do chat_id.

## Divulgação responsável

Se você encontrar uma vulnerabilidade, por favor:
1. NÃO publicar publicamente.
2. Abrir issue no GitHub com `[SECURITY]` no título e descrição resumida (sem exploit completo).
3. Aguardar contato.

Vulnerabilidades verificadas e corrigidas ganham crédito no `CREDITS.md`.

## Marcos legais aplicáveis

- **LGPD** (Lei 13.709/2018) — art. 4º III (fins jornalísticos/informativos exclui parte do escopo), art. 7º (bases legais), art. 18 (direitos).
- **Marco Civil da Internet** (Lei 12.965/2014) — retenção de logs, neutralidade.
- **LAI** (Lei 12.527/2011) — os dados eleitorais são de acesso público.
- **Lei 9.279/1996** — uso nominativo de marcas partidárias (logos).
- **Lei 9.504/1997** — Lei das Eleições. Uso do site pra fins de propaganda irregular é proibido pelos Termos.
- **Resoluções TSE 2026** — regras de divulgação de resultado.
