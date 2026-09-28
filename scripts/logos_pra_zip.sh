#!/bin/bash
# Baixa logos dos partidos e empacota em ~/logos-partidos.zip
# Roda no Termux/PC. Depois anexa o zip aqui na conversa.
set -e

DEST="$HOME/logos-partidos-tmp"
ZIP="$HOME/logos-partidos.zip"
rm -rf "$DEST"
mkdir -p "$DEST"
cd "$DEST"

LOGOS=$(cat <<'EOF'
10 https://upload.wikimedia.org/wikipedia/commons/thumb/e/e7/Logo_do_Republicanos.png/240px-Logo_do_Republicanos.png
11 https://upload.wikimedia.org/wikipedia/commons/thumb/1/17/Progressistas_logo.svg/240px-Progressistas_logo.svg.png
12 https://upload.wikimedia.org/wikipedia/commons/thumb/2/2f/PDT_Brasil_logo.svg/240px-PDT_Brasil_logo.svg.png
13 https://upload.wikimedia.org/wikipedia/commons/thumb/4/47/Logo_do_Partido_dos_Trabalhadores.svg/240px-Logo_do_Partido_dos_Trabalhadores.svg.png
15 https://upload.wikimedia.org/wikipedia/commons/thumb/6/64/MDB_Brasil_logo.svg/240px-MDB_Brasil_logo.svg.png
16 https://upload.wikimedia.org/wikipedia/commons/thumb/8/86/PSTU_logo.svg/240px-PSTU_logo.svg.png
18 https://upload.wikimedia.org/wikipedia/commons/thumb/1/1c/Rede_Sustentabilidade_logo.svg/240px-Rede_Sustentabilidade_logo.svg.png
20 https://upload.wikimedia.org/wikipedia/commons/thumb/8/8c/Podemos_logo_2017.svg/240px-Podemos_logo_2017.svg.png
21 https://upload.wikimedia.org/wikipedia/commons/thumb/e/ea/PCB_logo.svg/240px-PCB_logo.svg.png
22 https://upload.wikimedia.org/wikipedia/commons/thumb/4/45/Partido_Liberal_logo.svg/240px-Partido_Liberal_logo.svg.png
23 https://upload.wikimedia.org/wikipedia/commons/thumb/0/06/Cidadania23_logo.svg/240px-Cidadania23_logo.svg.png
28 https://upload.wikimedia.org/wikipedia/commons/thumb/a/a1/PRTB_logo.svg/240px-PRTB_logo.svg.png
29 https://upload.wikimedia.org/wikipedia/commons/thumb/8/8a/Partido_da_Causa_Oper%C3%A1ria_logo.svg/240px-Partido_da_Causa_Oper%C3%A1ria_logo.svg.png
30 https://upload.wikimedia.org/wikipedia/commons/thumb/4/48/Partido_Novo_logo.svg/240px-Partido_Novo_logo.svg.png
36 https://upload.wikimedia.org/wikipedia/commons/thumb/9/97/Agir_logo.svg/240px-Agir_logo.svg.png
40 https://upload.wikimedia.org/wikipedia/commons/thumb/7/77/PSB_Brasil_logo.svg/240px-PSB_Brasil_logo.svg.png
43 https://upload.wikimedia.org/wikipedia/commons/thumb/7/7f/Partido_Verde_logo.svg/240px-Partido_Verde_logo.svg.png
44 https://upload.wikimedia.org/wikipedia/commons/thumb/e/e1/Uni%C3%A3o_Brasil_logo.svg/240px-Uni%C3%A3o_Brasil_logo.svg.png
45 https://upload.wikimedia.org/wikipedia/commons/thumb/3/38/PSDB_logo_2015.svg/240px-PSDB_logo_2015.svg.png
50 https://upload.wikimedia.org/wikipedia/commons/thumb/1/11/PSOL_logo.svg/240px-PSOL_logo.svg.png
55 https://upload.wikimedia.org/wikipedia/commons/thumb/2/2a/Partido_Social_Democr%C3%A1tico_logo.svg/240px-Partido_Social_Democr%C3%A1tico_logo.svg.png
65 https://upload.wikimedia.org/wikipedia/commons/thumb/f/f1/PCdoB_logo.svg/240px-PCdoB_logo.svg.png
70 https://upload.wikimedia.org/wikipedia/commons/thumb/9/9b/Avante_logo.svg/240px-Avante_logo.svg.png
77 https://upload.wikimedia.org/wikipedia/commons/thumb/b/bb/Solidariedade_logo.svg/240px-Solidariedade_logo.svg.png
EOF
)

n_ok=0; n_fail=0
while read numero url; do
  [ -z "$numero" ] && continue
  arq="${numero}.png"
  if curl -sSL --max-time 20 -A "Mozilla/5.0" -o "$arq" "$url" && [ -s "$arq" ]; then
    tam=$(du -k "$arq" | cut -f1)
    echo "OK  $numero (${tam} KB)"
    n_ok=$((n_ok+1))
  else
    rm -f "$arq"
    echo "--  $numero falhou"
    n_fail=$((n_fail+1))
  fi
done <<< "$LOGOS"

echo ""
echo "=== $n_ok baixados, $n_fail falharam ==="

if [ $n_ok -eq 0 ]; then
  echo "Nenhum logo baixou. Sem zip pra criar."
  exit 1
fi

# Instala zip se falta (Termux)
command -v zip >/dev/null 2>&1 || pkg install -y zip 2>/dev/null || true

rm -f "$ZIP"
zip -r "$ZIP" . >/dev/null
echo ""
echo "==================================="
echo "✓ ZIP CRIADO em: $ZIP"
echo "  Tamanho: $(du -h $ZIP | cut -f1)"
echo "==================================="
echo ""
echo "Agora anexa esse arquivo aqui na conversa do Claude:"
echo "   $ZIP"
echo ""
echo "No Termux, você acha ele via:"
echo "   - Files app do Android → Termux → Home → logos-partidos.zip"
echo "   - Ou compartilha pelo Termux: termux-open $ZIP"
