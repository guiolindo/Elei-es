// Renderiza mapa geográfico com ECharts. Dois modos:
//   - "BR"  → 27 UFs coloridas pelo candidato líder de cada estado
//   - "<UF>" → municípios daquela UF coloridos pelo candidato líder de cada cidade

let _chart = null;
const _mapasRegistrados = new Set();

async function registrarMapa(chave, url, nameProperty) {
  if (_mapasRegistrados.has(chave)) return true;
  try {
    const r = await fetch(url);
    if (!r.ok) return false;
    const geo = await r.json();
    echarts.registerMap(chave, geo, { nameProperty });
    _mapasRegistrados.add(chave);
    return true;
  } catch (e) {
    console.warn("mapa não carregou:", chave, e);
    return false;
  }
}

async function init(container) {
  if (_chart) _chart.dispose();
  _chart = echarts.init(container, null, { renderer: "canvas" });
  if (!init._resize) {
    window.addEventListener("resize", () => _chart && _chart.resize());
    init._resize = true;
  }
  return _chart;
}

/**
 * @param {HTMLElement} container
 * @param {string} abrangencia "BR" para país, "SP"/"RJ"/... para estado
 * @param {Object} dadosPorArea { "SP" ou nome do município: { valor, cor, nome_lider, votos } }
 * @param {Object} opts { onClickArea?: (name) => void }
 */
export async function renderMapa(container, abrangencia, dadosPorArea = {}, opts = {}) {
  await init(container);

  let mapKey, url, nameProperty, labelFormatter, roam, zoom;
  if (abrangencia === "BR") {
    mapKey = "brasil";
    url = "/static/br-ufs.geojson";
    nameProperty = "sigla";
    labelFormatter = (p) => p.name;
    roam = false;
    zoom = 1.2;
  } else {
    mapKey = `uf-${abrangencia.toLowerCase()}`;
    url = `/static/municipios/${abrangencia.toLowerCase()}.geojson`;
    nameProperty = "nome";
    labelFormatter = () => "";  // muitos municípios: sem label
    roam = true;                // arrasta e dá zoom
    zoom = 1.05;
  }

  const ok = await registrarMapa(mapKey, url, nameProperty);
  if (!ok) {
    container.innerHTML = `<div style="padding:40px;text-align:center;color:var(--muted)">
      Mapa de municípios de ${abrangencia} não disponível ainda.
    </div>`;
    return;
  }

  const seriesData = Object.entries(dadosPorArea).map(([nome, d]) => ({
    name: nome,
    value: d.valor ?? 0,
    itemStyle: d.cor ? { color: d.cor } : undefined,
    _extra: d,
  }));

  _chart.setOption({
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
    series: [{
      type: "map",
      map: mapKey,
      nameProperty,
      roam,
      zoom,
      scaleLimit: { min: 0.8, max: 8 },
      label: {
        show: abrangencia === "BR",
        color: "#ffffff", fontSize: 11, fontWeight: 700,
        formatter: labelFormatter,
        textShadowColor: "#000",           // legibilidade em cima de qualquer cor
        textShadowBlur: 3,
      },
      itemStyle: {
        areaColor: "#2a3242",           // 3.1:1 vs fundo — visível
        borderColor: "#5a6478",         // borda clara pra separar estados
        borderWidth: 0.8,
      },
      emphasis: {
        itemStyle: { areaColor: "#f0b429", borderColor: "#fff", borderWidth: 1.5 },
        label: { show: true, color: "#000", fontWeight: 700, fontSize: 14 },
      },
      select: {
        itemStyle: { areaColor: "#f97316", borderColor: "#fff" },
        label: { color: "#000", fontWeight: 700 },
      },
      data: seriesData,
    }],
  });

  _chart.off("click");
  if (opts.onClickArea) {
    _chart.on("click", (p) => { if (p.name) opts.onClickArea(p.name); });
  }
  return _chart;
}
