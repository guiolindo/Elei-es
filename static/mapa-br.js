// Mapa real do Brasil por UF usando ECharts + GeoJSON dos 27 estados.
// Registra o mapa uma vez, depois qualquer render é só passar novos dados.

let _mapaChart = null;
let _registrado = false;

async function registrarMapa() {
  if (_registrado) return;
  const r = await fetch("/static/br-ufs.geojson");
  const geo = await r.json();
  echarts.registerMap("brasil", geo);
  _registrado = true;
}

/**
 * @param {HTMLElement} container elemento onde o mapa será desenhado
 * @param {Object} dadosPorUF   { "SP": { valor: number, cor?: string, nome_lider?: string, votos?: number }, ... }
 * @param {Object} opts         { titulo?: string, corPadrao?: string }
 */
export async function renderMapaBrasil(container, dadosPorUF = {}, opts = {}) {
  await registrarMapa();

  if (_mapaChart) _mapaChart.dispose();
  _mapaChart = echarts.init(container, null, { renderer: "canvas" });
  window.addEventListener("resize", () => _mapaChart && _mapaChart.resize());

  const seriesData = Object.entries(dadosPorUF).map(([sigla, d]) => ({
    name: sigla,
    value: d.valor ?? 0,
    itemStyle: d.cor ? { color: d.cor } : undefined,
    _extra: d,
  }));

  _mapaChart.setOption({
    backgroundColor: "transparent",
    tooltip: {
      trigger: "item",
      backgroundColor: "#161b24",
      borderColor: "#303a4d",
      textStyle: { color: "#ecf0f7" },
      formatter: (p) => {
        const d = p.data?._extra || {};
        if (!d.nome_lider) return `<b>${p.name}</b><br>Sem dados`;
        return `<b>${p.name}</b><br>Líder: <b>${d.nome_lider}</b><br>Votos: ${(d.votos || 0).toLocaleString("pt-BR")}`;
      },
    },
    visualMap: seriesData.length && seriesData[0].itemStyle
      ? undefined  // já usamos cores fixas por candidato
      : {
          show: false,
          min: 0, max: 100,
          inRange: { color: ["#1e2531", "#f0b429"] },
        },
    series: [{
      type: "map",
      map: "brasil",
      nameProperty: "sigla",
      roam: false,
      zoom: 1.2,
      label: {
        show: true, color: "#ecf0f7", fontSize: 10, fontWeight: 700,
        formatter: (p) => p.name,
      },
      itemStyle: {
        areaColor: opts.corPadrao || "#1e2531",
        borderColor: "#0f1218",
        borderWidth: 1,
      },
      emphasis: {
        itemStyle: { areaColor: "#f0b429", borderColor: "#f0b429" },
        label: { color: "#000" },
      },
      select: {
        itemStyle: { areaColor: "#f97316" },
        label: { color: "#000" },
      },
      data: seriesData,
    }],
  });

  return _mapaChart;
}

/** Handler de clique em UF. cb(sigla) é chamado a cada clique. */
export function onCliqueUF(cb) {
  if (!_mapaChart) return;
  _mapaChart.off("click");
  _mapaChart.on("click", (p) => { if (p.name) cb(p.name); });
}
