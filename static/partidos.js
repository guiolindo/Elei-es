// Cores e siglas dos partidos brasileiros registrados no TSE em 2026.
// Fonte: portal TSE (janeiro 2026). Cores extraídas dos manuais de marca
// dos próprios partidos. Uso decorativo, não altera identidade.
//
// Nota sobre fusões recentes:
//  - PSL (17) + DEM (25) → União Brasil (25) em 2022
//  - PROS (90) + Solidariedade (77) → Solidariedade em 2022
//  - Patriota (51) + PL (22) → PL em 2023
//  - PTB (14) renomeado para PRD em 2024 (mantém nº 14)
// Mantemos os extintos aqui pra compatibilidade com dados históricos.
export const PARTIDOS = {
  10: { sigla: "REPUBLICANOS", cor: "#045FB4" },
  11: { sigla: "PP",           cor: "#002F70" },
  12: { sigla: "PDT",          cor: "#C8102E" },
  13: { sigla: "PT",           cor: "#C4171E" },
  14: { sigla: "PRD",          cor: "#3B7FBF" },  // ex-PTB
  15: { sigla: "MDB",          cor: "#1B5E20" },
  16: { sigla: "PSTU",         cor: "#E30613" },
  17: { sigla: "PSL",          cor: "#005EB8" },  // extinto (fusão UNIÃO)
  18: { sigla: "REDE",         cor: "#35A751" },
  19: { sigla: "PODEMOS",      cor: "#003DA5" },
  20: { sigla: "PSC",          cor: "#F7A800" },
  21: { sigla: "PCB",          cor: "#B71C1C" },
  22: { sigla: "PL",           cor: "#1E3A8A" },
  23: { sigla: "CIDADANIA",    cor: "#E30613" },
  25: { sigla: "UNIÃO",        cor: "#FFB300" },
  27: { sigla: "DC",           cor: "#005CB9" },
  28: { sigla: "PRTB",         cor: "#F58220" },
  29: { sigla: "PCO",          cor: "#EE1D23" },
  30: { sigla: "NOVO",         cor: "#FF7F00" },
  33: { sigla: "PMN",          cor: "#009E4D" },
  35: { sigla: "PMB",          cor: "#E6007E" },
  36: { sigla: "AGIR",         cor: "#001489" },
  40: { sigla: "PSB",          cor: "#FED700" },
  43: { sigla: "PV",           cor: "#008C46" },
  45: { sigla: "PSDB",         cor: "#005CB9" },
  50: { sigla: "PSOL",         cor: "#E80D48" },
  51: { sigla: "PATRIOTA",     cor: "#003399" },  // extinto (fusão PL)
  55: { sigla: "PSD",          cor: "#00BFFF" },
  65: { sigla: "PC do B",      cor: "#C21818" },
  70: { sigla: "AVANTE",       cor: "#FFC700" },
  77: { sigla: "SOLIDARIEDADE", cor: "#F58220" },
  80: { sigla: "UP",           cor: "#F60E0E" },
  90: { sigla: "PROS",         cor: "#005CB9" },  // extinto (fusão Solidariedade)
};

// 32 entradas cobrindo TODOS os partidos que já apareceram desde 2018.
// Ativos em 2026 (23): 10, 11, 12, 13, 14, 15, 16, 18, 19, 20, 21, 22, 23,
//                       25, 28, 30, 40, 43, 45, 50, 55, 65, 70, 77.
// Nanicos com registro recente (5): 27, 29, 33, 35, 36, 80.
// Extintos mantidos pra retrocompat (4): 17, 51, 90 (26 se aparecer).

export function corDoPartido(numero) {
  return PARTIDOS[numero]?.cor || `hsl(${((numero || 0) * 137.508) % 360}, 55%, 42%)`;
}

export function siglaDoPartido(numero) {
  return PARTIDOS[numero]?.sigla || `P${numero || "?"}`;
}
