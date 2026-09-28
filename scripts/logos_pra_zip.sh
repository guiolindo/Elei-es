#!/data/data/com.termux/files/usr/bin/bash
# Baixa logos dos partidos brasileiros da Wikimedia Commons e monta um zip.
# Rodar no Termux (Android). Depois anexe o zip na conversa.

set -u
cd "$HOME"

DEST="$HOME/logos-partidos"
ZIP="$HOME/logos-partidos.zip"

# Instala dependências se faltarem
for pkg in curl zip; do
  command -v $pkg >/dev/null 2>&1 || { echo "instalando $pkg…"; pkg install -y $pkg >/dev/null 2>&1; }
done

rm -rf "$DEST" "$ZIP"
mkdir -p "$DEST"

# Lista: numero_urna | nome_wikimedia (arquivo na Commons, sem "File:")
mapping=(
  "10|Republicanos_logo.svg.png"
  "11|Progressistas_logo.svg.png"
  "12|PDT_Brasil_logo.svg.png"
  "13|Logo_do_Partido_dos_Trabalhadores.svg.png"
  "15|MDB_Brasil_logo.svg.png"
  "16|PSTU_logo.svg.png"
  "18|Rede_Sustentabilidade_logo.svg.png"
  "20|Podemos_logo_2017.svg.png"
  "21|PCB_logo.svg.png"
  "22|Partido_Liberal_logo.svg.png"
  "23|Cidadania23_logo.svg.png"
  "28|PRTB_logo.svg.png"
  "29|Partido_da_Causa_Operária_logo.svg.png"
  "30|Partido_Novo_logo.svg.png"
  "36|Agir_logo.svg.png"
  "40|PSB_Brasil_logo.svg.png"
  "43|Partido_Verde_logo.svg.png"
  "44|União_Brasil_logo.svg.png"
  "45|PSDB_logo_2015.svg.png"
  "50|PSOL_logo.svg.png"
  "55|Partido_Social_Democrático_logo.svg.png"
  "65|PCdoB_logo.svg.png"
  "70|Avante_logo.svg.png"
  "77|Solidariedade_logo.svg.png"
)

baixar_via_api() {
  # Usa a API oficial da Wikipedia pra resolver o thumb (evita hash de path)
  local arquivo="$1"
  local destino="$2"
  local encoded
  encoded=$(python3 -c "import urllib.parse; print(urllib.parse.quote('$arquivo'))" 2>/dev/null || echo "$arquivo")
  local url="https://commons.wikimedia.org/w/api.php?action=query&titles=File:${encoded}&prop=imageinfo&iiprop=url&iiurlwidth=240&format=json"
  local thumb_url
  thumb_url=$(curl -sSL --max-time 15 -A "Mozilla/5.0" "$url" 2>/dev/null \
    | grep -oE '"thumburl":"[^"]+' | head -1 | sed 's/.*":"//;s/\\//g')
  if [ -z "$thumb_url" ]; then
    return 1
  fi
  curl -sSL --max-time 20 -A "Mozilla/5.0" -o "$destino" "$thumb_url"
  [ -s "$destino" ] && return 0 || return 1
}

n_ok=0
n_fail=0
falhas=()

echo "Baixando ${#mapping[@]} logos…"
echo ""

for item in "${mapping[@]}"; do
  numero="${item%%|*}"
  arquivo="${item##*|}"
  destino="$DEST/${numero}.png"

  if baixar_via_api "$arquivo" "$destino"; then
    tam=$(du -h "$destino" 2>/dev/null | cut -f1)
    printf "  ✓ %3s %-45s  %s\n" "$numero" "$arquivo" "$tam"
    n_ok=$((n_ok + 1))
  else
    rm -f "$destino"
    printf "  ✗ %3s %s\n" "$numero" "$arquivo"
    falhas+=("$numero")
    n_fail=$((n_fail + 1))
  fi
done

echo ""
echo "=== $n_ok ok, $n_fail falhas ==="
if [ ${#falhas[@]} -gt 0 ]; then
  echo "Falharam: ${falhas[*]}"
fi

if [ "$n_ok" -eq 0 ]; then
  echo ""
  echo "Nenhum logo baixou. Sem zip pra criar."
  echo "Provavelmente a Wikimedia bloqueou temporariamente. Tenta de novo em uns minutos."
  exit 1
fi

cd "$DEST"
zip -q "$ZIP" *.png
cd "$HOME"

echo ""
echo "════════════════════════════════════════"
echo " ✓ ZIP CRIADO: $ZIP"
echo "   Tamanho: $(du -h "$ZIP" | cut -f1)"
echo "════════════════════════════════════════"
echo ""
echo "Pra anexar aqui na conversa:"
echo "  1) Abre o Files (Arquivos) do Android"
echo "  2) Navega até: Interno → data → data → com.termux → files → home"
echo "  3) Copia logos-partidos.zip pra Downloads (ou compartilha)"
echo ""
echo "Ou:  termux-open $ZIP  (abre menu de compartilhar)"
