# Cloudflare Worker — Proxy TSE

Worker que faz proxy dos endpoints do TSE, hospedado nos PoPs BR do Cloudflare.
Isso contorna o bloqueio do Akamai que barra IPs estrangeiros (como os do Railway).

## Deploy em 5 minutos

### 1. Cria conta grátis no Cloudflare
https://dash.cloudflare.com/sign-up

### 2. Cria o Worker
- Painel Cloudflare → sidebar → **Workers & Pages** → **Create** → **Create Worker**
- Nome: `apuracao-2026` (fica `apuracao-2026.SEU-USUARIO.workers.dev`)
- Clica em **Deploy** (com o código Hello World padrão só pra criar)

### 3. Cola o código
- Depois de criado, clica em **Edit code**
- Apaga tudo e cola o conteúdo de `worker.js`
- Clica em **Deploy**

### 4. Testa
Abre no navegador:
```
https://apuracao-2026.SEU-USUARIO.workers.dev/divulga/rest/v1/candidatura/listar/2026/SP/619/1/candidatos
```
Se retornar JSON com candidatos, tá funcionando.

### 5. Configura o Railway
Railway → serviço da app → Variables:
- `TSE_CDN_BASE` = `https://apuracao-2026.SEU-USUARIO.workers.dev/oficial`
- `TSE_DIVULGA_BASE` = `https://apuracao-2026.SEU-USUARIO.workers.dev/divulga/rest/v1/candidatura/listar`
- `TSE_FOTOS_BASE` = `https://apuracao-2026.SEU-USUARIO.workers.dev/fotos`

(Substitui `SEU-USUARIO` pelo seu username do Cloudflare.)

Salva. Railway redeploya. Confere em `/api/admin/testar-tse` que agora retorna 200.

## Como funciona

```
Railway (fora do BR)  →  Cloudflare Worker (São Paulo/BR)  →  TSE (Akamai)
      403 direto              passa como IP BR                    200 OK
```

O Worker:
- Roda em PoPs perto do usuário (Cloudflare tem SP, RJ, Fortaleza no BR)
- Faz `fetch` interno pro TSE de dentro dessas PoPs
- Repassa a resposta pro Railway

## Limites do free tier

- **100.000 requests/dia** — mais que suficiente. O poller faz ~82 requests a cada 20s = 82 × 3 × 60 × 24 = 354k/dia se rodasse full-throttle. Mas na maior parte do dia é 404 (fora da apuração), e ainda que os requests conte, dá pra facilmente dobrar o intervalo.
- **CPU limit** de 10ms por request — TSE responde em <5ms, cabe folgado.
- **Custo se exceder**: US$ 5/mês pra 10 milhões de requests. Praticamente impossível chegar lá.

## Rate limit do TSE

O TSE tem rate limit por IP. Como todos os requests do Worker saem do mesmo IP da PoP Cloudflare, muitos requests seguidos podem ser rate-limited pelo próprio TSE (não pelo Akamai). Nesse caso: aumentar `POLL_INTERVAL_SECONDS` no Railway pra 30s ou 60s.
