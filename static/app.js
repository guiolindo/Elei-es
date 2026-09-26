const COR_A = "#E69F00";
const COR_B = "#56B4E9";
const TZ = "America/Sao_Paulo";

const state = {
  cargo: 1,
  abrangencia: "BR",
  candidatos: [],
  selecionados: [], // [sq_a, sq_b]
  ficha: {},        // sq -> obj
  ws: null,
  graficos: {},
};

function fmtNum(n) {
  return (n ?? 0).toLocaleString("pt-BR");
}
function fmtHora(iso) {
  return new Date(iso).toLocaleTimeString("pt-BR", { timeZone: TZ });
}

async function get(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

function toast(msg, cls = "") {
  const div = document.createElement("div");
  div.className = "toast " + cls;
  div.textContent = msg;
  document.getElementById("toasts").appendChild(div);
  setTimeout(() => div.remove(), 6000);
}

async function carregarCandidatos() {
  const uf = state.abrangencia === "BR" ? "" : `&uf=${state.abrangencia}`;
  const cands = await get(`/api/candidatos?cargo=${state.cargo}${uf}`);
  state.candidatos = cands;
  cands.forEach(c => (state.ficha[c.sq_candidato] = c));
  renderLista();
}

function renderLista() {
  const el = document.getElementById("lista-candidatos");
  el.innerHTML = "";
  state.candidatos.forEach(c => {
    const div = document.createElement("div");
    div.className = "candidato";
    if (state.selecionados[0] === c.sq_candidato) div.classList.add("sel-a");
    if (state.selecionados[1] === c.sq_candidato) div.classList.add("sel-b");
    div.innerHTML = `
      <img src="${c.foto}" onerror="this.src='/static/silhueta.svg'" alt="">
      <div class="info">
        <div class="nome">${c.nome_urna}</div>
        <div class="meta">${c.numero} · ${c.partido}${c.uf ? " · " + c.uf : ""}</div>
        <div class="votos" data-sq="${c.sq_candidato}">—</div>
        <div class="barra"><div data-sq-barra="${c.sq_candidato}" style="width:0%"></div></div>
      </div>`;
    div.addEventListener("click", () => selecionar(c.sq_candidato));
    el.appendChild(div);
  });
}

function selecionar(sq) {
  const idx = state.selecionados.indexOf(sq);
  if (idx >= 0) {
    state.selecionados.splice(idx, 1);
  } else if (state.selecionados.length < 2) {
    state.selecionados.push(sq);
  } else {
    state.selecionados = [state.selecionados[1], sq];
  }
  renderLista();
  if (state.selecionados.length === 2) abrirComparacao();
  else fecharComparacao();
}

function fecharComparacao() {
  document.getElementById("comparacao").classList.add("oculto");
}

async function abrirComparacao() {
  document.getElementById("comparacao").classList.remove("oculto");
  const [a, b] = state.selecionados.map(sq => state.ficha[sq]);
  document.getElementById("card-a").innerHTML = cardHtml(a);
  document.getElementById("card-b").innerHTML = cardHtml(b);
  await atualizarComparacao();
  await inicializarGraficos();
}

function cardHtml(c) {
  return `
    <img src="${c.foto}" onerror="this.src='/static/silhueta.svg'" alt="">
    <div class="nome">${c.nome_urna}</div>
    <div class="meta">${c.numero} · Partido ${c.partido}${c.uf ? " · " + c.uf : ""}</div>
    <div class="votos" data-cardvotos="${c.sq_candidato}">—</div>
    <div class="pct" data-cardpct="${c.sq_candidato}">—</div>`;
}

async function atualizarPainelTotais(dados) {
  if (!dados.disponivel) return;
  const t = dados.totais;
  document.getElementById("pct-apurado").textContent = t.pct_apurado.toFixed(2) + "%";
  document.getElementById("secoes").textContent = `${fmtNum(t.secoes_totalizadas)} / ${fmtNum(t.secoes_total)}`;
  document.getElementById("comparecimento").textContent = fmtNum(t.comparecimento);
  document.getElementById("brancos-nulos").textContent = `${fmtNum(t.votos_brancos)} / ${fmtNum(t.votos_nulos)}`;
  document.getElementById("ultimo").textContent = fmtHora(dados.coletado_em);
  const maxVotos = Math.max(1, ...dados.candidatos.map(c => c.votos));
  dados.candidatos.forEach(c => {
    const votos = document.querySelector(`[data-sq="${c.sq_candidato}"]`);
    const barra = document.querySelector(`[data-sq-barra="${c.sq_candidato}"]`);
    if (votos) votos.textContent = `${fmtNum(c.votos)}  (${c.pct_validos.toFixed(2)}%)`;
    if (barra) barra.style.width = (c.votos / maxVotos * 100) + "%";
  });
}

async function atualizarComparacao() {
  if (state.selecionados.length !== 2) return;
  const dados = await get(`/api/apuracao/atual?cargo=${state.cargo}&abrangencia=${state.abrangencia}`);
  await atualizarPainelTotais(dados);
  if (!dados.disponivel) return;
  const map = new Map(dados.candidatos.map(c => [c.sq_candidato, c]));
  const [a, b] = state.selecionados.map(sq => map.get(sq));
  if (!a || !b) return;
  document.querySelector(`[data-cardvotos="${a.sq_candidato}"]`).textContent = fmtNum(a.votos);
  document.querySelector(`[data-cardvotos="${b.sq_candidato}"]`).textContent = fmtNum(b.votos);
  document.querySelector(`[data-cardpct="${a.sq_candidato}"]`).textContent = a.pct_validos.toFixed(2) + "%";
  document.querySelector(`[data-cardpct="${b.sq_candidato}"]`).textContent = b.pct_validos.toFixed(2) + "%";
  document.getElementById("dif-abs").textContent = fmtNum(Math.abs(a.votos - b.votos));
  document.getElementById("dif-pct").textContent = (a.pct_validos - b.pct_validos).toFixed(2) + " pp";
}

async function inicializarGraficos() {
  const [sqA, sqB] = state.selecionados;
  const hist = await get(`/api/apuracao/historico?cargo=${state.cargo}&abrangencia=${state.abrangencia}&candidatos=${sqA},${sqB}`);
  const nomeA = state.ficha[sqA].nome_urna;
  const nomeB = state.ficha[sqB].nome_urna;
  desenharVotos(hist, nomeA, nomeB);
  desenharPct(hist, nomeA, nomeB);
  desenharDif(hist, nomeA, nomeB);
  desenharBanda(hist, nomeA, nomeB);
}

function pega(hist, sq) {
  return (hist.series[sq] || []).map(p => [p.t, p.votos, p.pct, p.restantes_max]);
}

function baseOpts(title) {
  return {
    backgroundColor: "transparent",
    title: { text: title, textStyle: { color: "#e6edf3", fontSize: 13 } },
    tooltip: { trigger: "axis" },
    legend: { textStyle: { color: "#e6edf3" }, top: 0, right: 10 },
    grid: { left: 60, right: 30, top: 40, bottom: 30 },
    xAxis: { type: "time", axisLabel: { color: "#9aa4b2" } },
    yAxis: { type: "value", axisLabel: { color: "#9aa4b2" }, splitLine: { lineStyle: { color: "#262c38" } } },
  };
}

function chart(id) {
  if (state.graficos[id]) state.graficos[id].dispose();
  const c = echarts.init(document.getElementById(id), null, { renderer: "canvas" });
  state.graficos[id] = c;
  return c;
}

function desenharVotos(hist, a, b) {
  const [sqA, sqB] = state.selecionados;
  chart("graf-votos").setOption({
    ...baseOpts("Votos absolutos"),
    series: [
      { name: a, type: "line", showSymbol: false, data: pega(hist, sqA).map(p => [p[0], p[1]]), color: COR_A, smooth: true },
      { name: b, type: "line", showSymbol: false, data: pega(hist, sqB).map(p => [p[0], p[1]]), color: COR_B, smooth: true },
    ],
  });
}

function desenharPct(hist, a, b) {
  const [sqA, sqB] = state.selecionados;
  chart("graf-pct").setOption({
    ...baseOpts("% dos válidos"),
    yAxis: { ...baseOpts("").yAxis, max: 100, axisLabel: { color: "#9aa4b2", formatter: "{value}%" } },
    series: [
      { name: a, type: "line", showSymbol: false, data: pega(hist, sqA).map(p => [p[0], p[2]]), color: COR_A, smooth: true },
      { name: b, type: "line", showSymbol: false, data: pega(hist, sqB).map(p => [p[0], p[2]]), color: COR_B, smooth: true },
    ],
  });
}

function desenharDif(hist, a, b) {
  const [sqA, sqB] = state.selecionados;
  const A = new Map(pega(hist, sqA).map(p => [p[0], p[1]]));
  const B = new Map(pega(hist, sqB).map(p => [p[0], p[1]]));
  const dif = [];
  for (const t of A.keys()) if (B.has(t)) dif.push([t, A.get(t) - B.get(t)]);
  chart("graf-dif").setOption({
    ...baseOpts(`Diferença ${a} − ${b}`),
    series: [{
      type: "line", showSymbol: false, data: dif, smooth: true,
      areaStyle: {}, color: "#009E73",
      markLine: { symbol: "none", data: [{ yAxis: 0 }], lineStyle: { color: "#9aa4b2", type: "dashed" } },
    }],
  });
}

function desenharBanda(hist, a, b) {
  const [sqA, sqB] = state.selecionados;
  const sA = pega(hist, sqA), sB = pega(hist, sqB);
  const serie = (dados, nome, cor) => ({
    name: nome, type: "line", showSymbol: false, color: cor, smooth: true,
    data: dados.map(p => [p[0], p[1]]),
    markArea: {
      itemStyle: { color: cor, opacity: 0.15 },
      data: dados.map(p => [{ xAxis: p[0], yAxis: p[1] }, { xAxis: p[0], yAxis: p[1] + p[3] }]),
    },
  });
  chart("graf-banda").setOption({
    ...baseOpts("Faixa de vitória matemática (votos atuais → teto)"),
    series: [serie(sA, a, COR_A), serie(sB, b, COR_B)],
  });
}

async function carregarEventos() {
  const evs = await get(`/api/eventos?cargo=${state.cargo}&abrangencia=${state.abrangencia}`);
  const ul = document.getElementById("lista-eventos");
  ul.innerHTML = "";
  for (const ev of evs) {
    const li = document.createElement("li");
    const nome = state.ficha[ev.sq_candidato_a]?.nome_urna || ev.sq_candidato_a;
    let texto = "";
    if (ev.tipo === "ELEITO_1T") texto = `${nome} eleito(a) no 1º turno`;
    else if (ev.tipo === "SEGUNDO_TURNO_DEFINIDO") {
      const b = state.ficha[ev.sq_candidato_b]?.nome_urna || ev.sq_candidato_b;
      texto = `2º turno definido: ${nome} × ${b}`;
    } else if (ev.tipo === "ELEITO_MAJORITARIO") {
      texto = `${nome} eleito(a)`;
    } else texto = ev.tipo;
    li.innerHTML = `<time>${fmtHora(ev.ocorrido_em)}</time>${texto}`;
    ul.appendChild(li);
  }
}

function conectarWS() {
  if (state.ws) state.ws.close();
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  const ws = new WebSocket(`${proto}//${location.host}/ws/apuracao?cargo=${state.cargo}&abrangencia=${state.abrangencia}`);
  ws.onmessage = async (m) => {
    const msg = JSON.parse(m.data);
    if (msg.type === "snapshot") {
      const dados = await get(`/api/apuracao/atual?cargo=${state.cargo}&abrangencia=${state.abrangencia}`);
      await atualizarPainelTotais(dados);
      if (state.selecionados.length === 2) {
        await atualizarComparacao();
        await inicializarGraficos();
      }
      for (const ev of msg.eventos || []) {
        const nome = state.ficha[ev.sq_candidato_a]?.nome_urna || ev.sq_candidato_a;
        toast(ev.tipo === "ELEITO_1T" ? `${nome} eleito(a) no 1º turno!`
            : ev.tipo === "SEGUNDO_TURNO_DEFINIDO" ? `2º turno matematicamente definido`
            : `${nome} eleito(a)`);
      }
      await carregarEventos();
    }
  };
  state.ws = ws;
}

async function pedirNotificacoes() {
  if (!("Notification" in window)) return;
  const perm = await Notification.requestPermission();
  toast(perm === "granted" ? "Notificações ativadas" : "Notificações negadas", "warn");
}

async function boot() {
  document.getElementById("sel-cargo").addEventListener("change", async (e) => {
    state.cargo = +e.target.value; state.selecionados = [];
    fecharComparacao();
    await carregarCandidatos();
    await atualizarComparacao();
    await carregarEventos();
    conectarWS();
  });
  document.getElementById("sel-uf").addEventListener("change", async (e) => {
    state.abrangencia = e.target.value; state.selecionados = [];
    fecharComparacao();
    await carregarCandidatos();
    await atualizarComparacao();
    await carregarEventos();
    conectarWS();
  });
  document.getElementById("btn-fechar").addEventListener("click", () => {
    state.selecionados = []; fecharComparacao(); renderLista();
  });
  document.getElementById("btn-notif").addEventListener("click", pedirNotificacoes);

  try {
    const ufs = await get("/api/ufs");
    const selUF = document.getElementById("sel-uf");
    for (const u of ufs) {
      const opt = document.createElement("option");
      opt.value = u.sigla; opt.textContent = u.sigla;
      selUF.appendChild(opt);
    }
  } catch (e) { /* sem ufs ainda */ }

  await carregarCandidatos();
  const dados = await get(`/api/apuracao/atual?cargo=${state.cargo}&abrangencia=${state.abrangencia}`).catch(() => ({disponivel:false}));
  await atualizarPainelTotais(dados);
  await carregarEventos();
  conectarWS();
}

boot().catch(e => { console.error(e); toast("Erro ao carregar: " + e.message, "warn"); });
