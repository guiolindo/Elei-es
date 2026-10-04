// Renderiza mapa geográfico com ECharts. Dois modos:
//   - "BR"  → 27 UFs coloridas pelo candidato líder de cada estado
//   - "<UF>" → municípios daquela UF coloridos pelo candidato líder de cada cidade

let _chart = null;
const _mapasRegistrados = new Set();
// Mapa auxiliar: chave_ECharts → nome amigável (pra tooltip).
// Ex: no mapa de SP, "3550308" → "São Paulo".
const _nomesPorArea = {};   // { mapKey: { "3550308": "São Paulo", ... } }

async function registrarMapa(chave, url, nameProperty) {
  if (_mapasRegistrados.has(chave)) return true;
  try {
    const r = await fetch(url);
    if (!r.ok) return false;
    const geo = await r.json();
    echarts.registerMap(chave, geo, { nameProperty });
    _mapasRegistrados.add(chave);
    // Constrói o dicionário id → nome_amigavel pra usar na tooltip
    const dic = {};
    for (const f of geo.features || []) {
      const p = f.properties || {};
      const chaveArea = String(p[nameProperty]);
      const nome = p.nome || p.name || p.description || chaveArea;
      dic[chaveArea] = nome;
    }
    _nomesPorArea[chave] = dic;
    return true;
  } catch (e) {
    console.warn("mapa não carregou:", chave, e);
    return false;
  }
}

async function init(container, abrangencia) {
  if (_chart) _chart.dispose();
  // Bounding box real do Brasil: ~40° largura × ~39° altura (5°N a -34°S,
  // -74°W a -34°W). Como usaremos aspectScale=1 pra não distorcer o
  // desenho, o container precisa de proporção próxima da real (≈0.9).
  // No mobile o mapa fica em coluna estreita, então cai pra 1.0 (quadrado)
  // pra ainda mostrar o país inteiro.
  const w = container.clientWidth || 800;
  const isMobile = w < 500;
  const isTV = document.body.classList.contains("is-tv");
  const aspect = abrangencia === "BR"
    ? (isMobile ? 1.0 : 0.88)
    : 1.0;  // UF: bounding box varia, quadrado é razoável
  // Em TV o container tem altura imposta pelo grid (viewport fixo).
  // Respeita essa altura; só força pixel quando o pai não constrange.
  if (isTV) {
    const hCell = container.clientHeight || container.parentElement?.clientHeight || 0;
    const h = hCell > 100 ? hCell : Math.min(640, Math.max(340, w * aspect));
    container.style.height = h + "px";
  } else {
    container.style.height = Math.min(640, Math.max(340, w * aspect)) + "px";
  }
  _chart = echarts.init(container, null, { renderer: "canvas" });
  if (!init._resize) {
    window.addEventListener("resize", () => {
      if (_chart) {
        const w2 = container.clientWidth || 800;
        const isMob2 = w2 < 500;
        const asp2 = abrangencia === "BR" ? (isMob2 ? 1.0 : 0.88) : 1.0;
        container.style.height = Math.min(640, Math.max(340, w2 * asp2)) + "px";
        _chart.resize();
      }
    });
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
  await init(container, abrangencia);

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
    nameProperty = "id";        // usa código IBGE como chave (7 dígitos)
    labelFormatter = () => "";  // sem label (centenas de municípios)
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
        // No mapa municipal, p.name é o código IBGE — pegamos o nome amigável
        // do dicionário construído a partir das properties do GeoJSON.
        const nomeAmigavel = _nomesPorArea[mapKey]?.[p.name] || d.nome_local || p.name;
        if (!d.nome_lider) return `<b>${nomeAmigavel}</b><br>Sem dados`;
        return `<b>${nomeAmigavel}</b><br>Líder: <b>${d.nome_lider}</b><br>Votos: ${(d.votos || 0).toLocaleString("pt-BR")}`;
      },
    },
    series: [{
      type: "map",
      map: mapKey,
      nameProperty,
      roam,
      zoom,
      scaleLimit: { min: 0.8, max: 8 },
      // aspectScale=1 preserva a proporção real do GeoJSON (não achata
      // verticalmente como o default 0.75 do ECharts, que era o que
      // fazia o Brasil parecer "esticado" pra cima).
      aspectScale: 1,
      layoutCenter: ["50%", "52%"],
      layoutSize: "94%",
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
    _chart.on("click", (p) => {
      if (!p.name) return;
      const nome = _nomesPorArea[mapKey]?.[p.name] || p.name;
      opts.onClickArea(p.name, nome);
    });
  }
  return _chart;
}

/** Nome amigável de uma área (UF sigla ou município cod_ibge). */
export function nomeArea(chaveMapa, area) {
  return _nomesPorArea[chaveMapa]?.[area] || area;
}
