// Mapa do Brasil por UF — SVG simplificado (retângulos rotulados).
// Layout aproximado geograficamente, cada estado é um bloco clicável.
export const MAPA_UFS = [
  // sigla, x, y, w, h
  ["RR",  110, 30,  60, 60],
  ["AP",  200, 30,  60, 60],
  ["AM",  40,  95, 130, 90],
  ["PA",  180, 95, 110, 90],
  ["MA",  300, 95,  70, 65],
  ["CE",  375, 95,  55, 55],
  ["RN",  435, 95,  50, 40],
  ["PB",  435, 140, 50, 30],
  ["PE",  375, 155, 110, 30],
  ["AL",  445, 190, 40, 30],
  ["SE",  400, 190, 40, 30],
  ["PI",  300, 165,  70, 70],
  ["BA",  310, 240, 120, 100],
  ["AC",   0, 165,  70, 60],
  ["RO",   75, 190,  90, 60],
  ["TO",  225, 195,  75, 90],
  ["MT",  105, 255, 120, 90],
  ["MS",  170, 350, 100, 65],
  ["GO",  240, 290,  70, 70],
  ["DF",  280, 305,  22, 20],
  ["MG",  310, 345, 100, 80],
  ["ES",  415, 375,  40, 55],
  ["RJ",  380, 435,  70, 30],
  ["SP",  290, 425,  90, 55],
  ["PR",  245, 485,  90, 45],
  ["SC",  260, 535,  85, 35],
  ["RS",  205, 575, 130, 70],
];

export function renderMapaBrasil(container, corPorUF) {
  const w = 550, h = 680;
  let paths = "";
  for (const [sigla, x, y, ww, hh] of MAPA_UFS) {
    const cor = corPorUF[sigla] || "#1e2531";
    paths += `<g data-uf="${sigla}"><rect x="${x}" y="${y}" width="${ww}" height="${hh}" rx="6" ry="6" fill="${cor}" stroke="#0f1218" stroke-width="1.5"><title>${sigla}</title></rect><text x="${x+ww/2}" y="${y+hh/2+4}" text-anchor="middle" fill="#fff" font-size="12" font-weight="700" style="pointer-events:none;font-family:'JetBrains Mono',monospace">${sigla}</text></g>`;
  }
  container.innerHTML = `<svg viewBox="0 0 ${w} ${h}" xmlns="http://www.w3.org/2000/svg">${paths}</svg>`;
}
