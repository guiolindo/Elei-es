# Deploy no Fly.io (região GRU / São Paulo)

Necessário para acessar o TSE sem proxy — TSE bloqueia IPs fora do Brasil.

## 1. Instalar Fly CLI

**No PC (Windows/Mac/Linux):**
```bash
# Linux/Mac
curl -L https://fly.io/install.sh | sh

# Windows (PowerShell)
iwr https://fly.io/install.ps1 -useb | iex
```

**No Termux (Android):**
```bash
pkg install flyctl
```

## 2. Login

```bash
fly auth login
```
Abre o navegador → cria conta ou faz login. Adiciona um cartão de crédito (**não vai cobrar** dentro do free tier: 3 VMs pequenas + 3GB storage).

## 3. Pegar a URL pública do Postgres do Railway

No painel do Railway → serviço **Postgres** → **Variables** → copia o valor de `DATABASE_PUBLIC_URL`

Formato: `postgresql://postgres:senha@caboose.proxy.rlwy.net:XXXXX/railway`

## 4. Deploy no Fly

Na pasta do projeto:

```bash
# Cria o app na região GRU (São Paulo)
fly launch --no-deploy --region gru --name apuracao-2026

# Configura o banco (cola a URL pública do Railway)
fly secrets set DATABASE_URL="postgresql://postgres:SENHA@caboose.proxy.rlwy.net:PORTA/railway"

# Deploy!
fly deploy
```

## 5. Ver logs

```bash
fly logs
```

Deve mostrar em segundos:
```
proxy_pool: usando lista default de 17 proxies BR
sync_candidatos: iniciando ciclo
candidatos 2026 cargo=1 uf=SP: 12 encontrados       ← agora vai funcionar!
...
sync_candidatos: 1247 candidatos atualizados
```

## 6. Abrir o app

```bash
fly open
```

URL fica tipo: `https://apuracao-2026.fly.dev`

## 7. Domínio custom (opcional)

```bash
fly certs create meudominio.com.br
```

## Como funciona sem proxy

O Fly.io GRU roda em São Paulo. O TSE **não bloqueia** IPs BR pelo Akamai (só bloqueia estrangeiros). Como o `TSE_PROXY_LIST` e `TSE_PROXY` ficam vazios, o `cliente_tse()` faz acesso direto e passa.

## Manter o Railway?

**Pode desligar** o serviço da app no Railway (deixa só o Postgres rodando). O Fly.io é onde o app fica agora.

Se quiser desligar tudo do Railway depois: migre o banco pro Fly Postgres. Mas por enquanto usar o Postgres do Railway é mais rápido.
