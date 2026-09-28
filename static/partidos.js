// Cores e siglas dos 30 partidos brasileiros registrados no TSE para 2026.
// Lista extraída em 28/09/2026 (fonte: TSE + ric.com.br + wikipedia).
// Cores baseadas na identidade visual pública de cada partido.
// Uso decorativo, não altera identidade.
//
// Mudanças recentes:
//  - 14 Missão (novo, registrado em nov/2025, era PTB→PRD antes)
//  - 20 Podemos (era PSC — PSC fundiu no Podemos em 2024)
//  - 25 PRD (era União Brasil — que migrou pro 44)
//  - 33 Mobiliza (novo nome do ex-PMN)
//  - 35 O Democrata (novo nome do ex-PMB)
//  - 44 União Brasil (mudou de 25 pra 44)
//  - Extintos: 17 PSL, 19 (renumerado), 51 Patriota, 90 PROS
export const PARTIDOS = {
  10: { sigla: "REPUBLICANOS", cor: "#045FB4" },
  11: { sigla: "PP",           cor: "#002F70" },
  12: { sigla: "PDT",          cor: "#C8102E" },
  13: { sigla: "PT",           cor: "#C4171E" },
  14: { sigla: "MISSÃO",       cor: "#2B7A4B" },
  15: { sigla: "MDB",          cor: "#1B5E20" },
  16: { sigla: "PSTU",         cor: "#E30613" },
  18: { sigla: "REDE",         cor: "#35A751" },
  20: { sigla: "PODE",         cor: "#003DA5" },
  21: { sigla: "PCB",          cor: "#B71C1C" },
  22: { sigla: "PL",           cor: "#1E3A8A" },
  23: { sigla: "CIDADANIA",    cor: "#E30613" },
  25: { sigla: "PRD",          cor: "#3B7FBF" },
  27: { sigla: "DC",           cor: "#005CB9" },
  28: { sigla: "PRTB",         cor: "#F58220" },
  29: { sigla: "PCO",          cor: "#EE1D23" },
  30: { sigla: "NOVO",         cor: "#FF7F00" },
  33: { sigla: "MOBILIZA",     cor: "#009E4D" },
  35: { sigla: "O DEMOCRATA",  cor: "#8B4513" },
  36: { sigla: "AGIR",         cor: "#001489" },
  40: { sigla: "PSB",          cor: "#FED700" },
  43: { sigla: "PV",           cor: "#008C46" },
  44: { sigla: "UNIÃO",        cor: "#FFB300" },
  45: { sigla: "PSDB",         cor: "#005CB9" },
  50: { sigla: "PSOL",         cor: "#E80D48" },
  55: { sigla: "PSD",          cor: "#00BFFF" },
  65: { sigla: "PCdoB",        cor: "#C21818" },
  70: { sigla: "AVANTE",       cor: "#FFC700" },
  77: { sigla: "SOLIDARIEDADE", cor: "#F58220" },
  80: { sigla: "UP",           cor: "#F60E0E" },
  // Extintos ou renumerados — mantidos pra dados históricos que possam
  // ainda aparecer na base:
  17: { sigla: "PSL",          cor: "#005EB8" },  // fundiu em UNIÃO 2022
  51: { sigla: "PATRIOTA",     cor: "#003399" },  // fundiu em PL 2023
  90: { sigla: "PROS",         cor: "#005CB9" },  // fundiu em SOLIDARIEDADE 2022
};

export function corDoPartido(numero) {
  return PARTIDOS[numero]?.cor || `hsl(${((numero || 0) * 137.508) % 360}, 55%, 42%)`;
}

export function siglaDoPartido(numero) {
  return PARTIDOS[numero]?.sigla || `P${numero || "?"}`;
}

// Extensão do logo por número de partido (baseado no que foi enviado).
// SVG quando possível (escala melhor), PNG quando é a versão disponível.
const EXT_LOGO = {
  10: "svg", 11: "png", 12: "png", 13: "svg", 14: "svg",
  15: "png", 16: "png", 18: "svg", 20: "png", 21: "svg",
  22: "svg", 23: "png", 25: "svg", 27: "png", 28: "png",
  29: "svg", 30: "svg", 33: "png", 35: "svg", 36: "png",
  40: "png", 43: "svg", 44: "svg", 45: "svg", 50: "png",
  55: "svg", 65: "svg", 70: "svg", 77: "png", 80: "png",
};

// Retorna HTML de badge do partido: tenta logo local, cai na pill colorida.
// Estrutura: <img> primeiro (some se falhar) + <span pill> escondido que
// aparece via onerror. Loading lazy pra não sobrecarregar a listagem.
export function badgePartidoHtml(numero) {
  const sig = siglaDoPartido(numero);
  const cor = corDoPartido(numero);
  const ext = EXT_LOGO[numero] || "svg";
  return `<span class="badge-part-wrap">
    <img class="badge-part-logo" src="/static/partidos/${numero}.${ext}" alt="${sig}"
         loading="lazy" decoding="async"
         onerror="this.classList.add('erro');this.nextElementSibling.style.display='inline-block'">
    <span class="pill-part" style="background:${cor};display:none">${sig}</span>
  </span>`;
}
