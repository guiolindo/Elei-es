#!/data/data/com.termux/files/usr/bin/bash
# Baixa candidatos do TSE (do celular, IP residencial BR) e envia pro app.
# Uso: bash importar_do_celular.sh https://elei-es-production.up.railway.app

APP_URL="${1:-https://elei-es-production.up.railway.app}"
COD=619   # código da eleição 2026 — troca se descobrir outro
ANO=2026

UFS="AC AL AM AP BA CE DF ES GO MA MG MS MT PA PB PE PI PR RJ RN RO RR RS SC SE SP TO"
CARGOS_ESTADUAIS="3 5 6 7"

ok=0; fail=0

enviar() {
  local cargo=$1
  local uf=$2
  local url="https://divulgacandcontas.tse.jus.br/divulga/rest/v1/candidatura/listar/$ANO/$uf/$COD/$cargo/candidatos"
  local body=$(curl -sS --max-time 15 -A "Mozilla/5.0" "$url")
  if [ -z "$body" ] || [[ "$body" == *"Access Denied"* ]] || [[ "$body" == *"NÃO ENCONTRADO"* ]]; then
    echo "-- cargo=$cargo uf=$uf: sem dados"
    fail=$((fail+1))
    return
  fi
  local resp=$(curl -sS -X POST "$APP_URL/api/admin/importar-candidatos" \
    -H "content-type: application/json" \
    -d "{\"cargo\":$cargo,\"uf\":\"$uf\",\"json\":$body}")
  echo "OK cargo=$cargo uf=$uf → $resp"
  ok=$((ok+1))
}

# Presidente (nacional)
enviar 1 BR

# Estaduais em cada UF
for uf in $UFS; do
  for cargo in $CARGOS_ESTADUAIS; do
    enviar $cargo $uf
  done
done

echo ""
echo "=== $ok sucessos, $fail sem dados ==="
