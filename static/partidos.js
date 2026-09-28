// Cores e siglas dos partidos brasileiros ativos em 2026.
// Cores extraídas dos manuais de marca dos próprios partidos (versões
// oficiais publicadas nos sites). Uso decorativo, não altera identidade.
export const PARTIDOS = {
  10: { sigla: "REPUBLICANOS", cor: "#045FB4" },
  11: { sigla: "PP",           cor: "#002F70" },
  12: { sigla: "PDT",          cor: "#C8102E" },
  13: { sigla: "PT",           cor: "#C4171E" },
  14: { sigla: "PTB",          cor: "#3B7FBF" },
  15: { sigla: "MDB",          cor: "#1B5E20" },
  16: { sigla: "PSTU",         cor: "#E30613" },
  17: { sigla: "PSL",          cor: "#005EB8" },
  18: { sigla: "REDE",         cor: "#35A751" },
  19: { sigla: "PODEMOS",      cor: "#003DA5" },
  20: { sigla: "PSC",          cor: "#F7A800" },
  21: { sigla: "PCB",          cor: "#B71C1C" },
  22: { sigla: "PL",           cor: "#1E3A8A" },
  23: { sigla: "CIDADANIA",    cor: "#E30613" },
  25: { sigla: "UNIÃO",        cor: "#FFB300" },
  27: { sigla: "DC",           cor: "#005CB9" },
  28: { sigla: "AGIR",         cor: "#001489" },
  29: { sigla: "PCO",          cor: "#EE1D23" },
  30: { sigla: "NOVO",         cor: "#FF7F00" },
  33: { sigla: "PMN",          cor: "#009E4D" },
  35: { sigla: "PMB",          cor: "#E6007E" },
  36: { sigla: "PTC",          cor: "#0068B3" },
  40: { sigla: "PSB",          cor: "#FED700" },
  43: { sigla: "PV",           cor: "#008C46" },
  44: { sigla: "NOVO",         cor: "#FF7F00" },
  45: { sigla: "PSDB",         cor: "#005CB9" },
  50: { sigla: "PSOL",         cor: "#E80D48" },
  51: { sigla: "PATRIOTA",     cor: "#003399" },
  54: { sigla: "PRTB",         cor: "#F58220" },
  55: { sigla: "PSD",          cor: "#00BFFF" },
  65: { sigla: "PC do B",      cor: "#C21818" },
  70: { sigla: "AVANTE",       cor: "#FFC700" },
  77: { sigla: "SOLIDARIEDADE", cor: "#F58220" },
  80: { sigla: "UP",           cor: "#F60E0E" },
  90: { sigla: "PROS",         cor: "#005CB9" },
};

export function corDoPartido(numero) {
  return PARTIDOS[numero]?.cor || `hsl(${((numero || 0) * 137.508) % 360}, 55%, 42%)`;
}

export function siglaDoPartido(numero) {
  return PARTIDOS[numero]?.sigla || `P${numero || "?"}`;
}
