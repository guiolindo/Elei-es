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
  // NÃO forçamos pixel height — o flex do pai decide. Se vier 0 no boot
  // inicial, usamos fallback mínimo pra ECharts ter algo pra desenhar;
  // ResizeObserver abaixo corrige quando o layout estabilizar.
  if (isTV) {
    const hCell = container.clientHeight || container.parentElement?.clientHeight || 0;
    if (hCell < 80) container.style.height = "260px";
    else container.style.removeProperty("height");
  } else {
    container.style.height = Math.min(640, Math.max(340, w * aspect)) + "px";
  }
  _chart = echarts.init(container, null, { renderer: "canvas" });
  // Altura acompanha a largura real. Com a aba escondida o container mede 0
  // no boot (cai no fallback de 800 px) e ficava 640 px de altura num
  // celular de 366 px de largura: o mapa sobrava espremido no meio.
  const ajustarAltura = () => {
    if (document.body.classList.contains("is-tv")) { container.style.removeProperty("height"); return; }
    const w2 = container.clientWidth;
    if (!w2) return;
    const asp2 = abrangencia === "BR" ? (w2 < 500 ? 1.0 : 0.88) : 1.0;
    const h2 = Math.min(640, Math.max(340, w2 * asp2)) + "px";
    if (container.style.height !== h2) container.style.height = h2;
  };
  init._ajustar = ajustarAltura;
  if (!init._resize) {
    window.addEventListener("resize", () => {
      if (_chart) { init._ajustar(); _chart.resize(); }
    });
    init._resize = true;
  }
  // ResizeObserver dedicado pro container: pega mudanças de layout
  // (toggle TV, troca de aba, etc.) sem depender de window resize.
  if (!init._obs && window.ResizeObserver) {
    init._obs = new ResizeObserver(() => { if (_chart) { init._ajustar(); _chart.resize(); } });
    init._obs.observe(container);
  }
  return _chart;
}

// Siglas dos estados: 11 px no site; no quadro da TV acompanham a escala
// da tela (15 px a 1920 de largura), senão somem numa TV 4K.
function tamanhoRotulo() {
  if (!document.body.classList.contains("tv-quadro")) return 11;
  const larg = document.getElementById("tv-quadro")?.firstElementChild?.offsetWidth || 1920;
  return Math.max(10, Math.round(15 * larg / 1920));
}

/**
 * @param {HTMLElement} container
 * @param {string} abrangencia "BR" para país, "SP"/"RJ"/... para estado
 * @param {Object} dadosPorArea { "SP" ou nome do município: { valor, cor, nome_lider, votos } }
 * @param {Object} opts { onClickArea?: (name) => void, rotuloPartido?: false = só a sigla da UF }
 */
export async function renderMapa(container, abrangencia, dadosPorArea = {}, opts = {}) {
  if (typeof echarts === "undefined") {
    container.innerHTML = '<p class="home-graf-msg">Não foi possível carregar o mapa. Verifique a conexão e recarregue a página.</p>';
    return;
  }
  await init(container, abrangencia);

  let mapKey, url, nameProperty, labelFormatter, roam, zoom;
  if (abrangencia === "BR") {
    mapKey = "brasil";
    url = "/static/br-ufs.geojson";
    nameProperty = "sigla";
    // Rotulamos cada UF com "SIGLA\nPARTIDO" quando houver líder — assim
    // dois UFs ganhos por partidos diferentes com cores parecidas (PT ×
    // PDT, PL × PSDB, etc.) ficam distinguíveis a olho nu, sem precisar
    // só do tooltip.
    // No 2º turno são só dois candidatos e a cor já diz quem lidera: só a
    // sigla da UF, que também não embola no Nordeste.
    labelFormatter = (p) => {
      const sig = opts.rotuloPartido === false ? "" : p.data?._extra?.partido_sigla;
      return sig ? `${p.name}\n${sig}` : p.name;
    };
    roam = false;
    zoom = 1;   // 1.2 cortava AC/AM, RR e RS quando o espaço é estreito
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

  // ECharts map series usa `areaColor` pra fill da UF/município, NÃO
  // `color`. Com `color` o item só colore marker/line, mas o polígono
  // continua com o areaColor default da série (#2a3242 cinza). Bug só
  // notado no dia D (05/10/2026): labels "SP\nPL" apareciam corretos
  // mas todos os UFs ficavam cinza como se não tivessem dado.
  const seriesData = Object.entries(dadosPorArea).map(([nome, d]) => ({
    name: nome,
    value: d.valor ?? 0,
    itemStyle: d.cor ? { areaColor: d.cor } : undefined,
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
      layoutSize: "97%",
      // Quadro da TV: siglas que se encostam (DF/GO, RN/PB/PE/AL/SE) somem
      // em vez de virar "GODF"; a cor do estado continua dizendo quem lidera.
      labelLayout: document.body.classList.contains("tv-quadro") ? { hideOverlap: true } : undefined,
      label: {
        show: abrangencia === "BR",
        color: "#ffffff", fontSize: tamanhoRotulo(), fontWeight: 700,
        lineHeight: 13,
        formatter: labelFormatter,
        textShadowColor: "#000",           // legibilidade em cima de qualquer cor
        textShadowBlur: 3,
        // Partido vem em fonte menor e levemente mais clara pra
        // hierarquia visual (sigla UF em cima, partido em baixo).
        rich: {},
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
