import { renderMapaBrasil, onCliqueUF } from "/static/mapa-br.js";

const PALETA = ["#f0b429", "#3b82f6", "#ec4899", "#10b981", "#a855f7", "#f97316"];
const TZ = "America/Sao_Paulo";
const MAX_SEL = 4;

const state = {
  cargo: 1,
  abrangencia: "BR",
  candidatos: [],
  ficha: {},
  selecionados: [],
  ultimoSnapshot: null,
  graficos: {},
  ws: null,
};

// ============ helpers ============
const fmt = new Intl.NumberFormat("pt-BR");
const fmtNum = n => fmt.format(n ?? 0);
const fmtHora = iso => new Date(iso).toLocaleTimeString("pt-BR", { timeZone: TZ });
const $ = id => document.getElementById(id);

async function get(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  return r.json();
}

function toast(msg, tipo = "") {
  const div = document.createElement("div");
  div.className = "toast " + tipo;
  div.textContent = msg;
  $("toasts").appendChild(div);
  setTimeout(() => { div.style.opacity = "0"; setTimeout(() => div.remove(), 300); }, 5000);
}

// ============ regras cargo × UF ============
function cargoRequerUF(cargo) {
  return cargo !== 1;  // 1 = Presidente é nacional
}

function ajustarUFParaCargo() {
  const selUF = $("sel-uf");
  if (state.cargo === 1) {
    // Presidente → Brasil obrigatório
    state.abrangencia = "BR";
    selUF.value = "BR";
    selUF.disabled = true;
  } else {
    // Outros cargos → UF obrigatória. Se estava em BR, escolhe SP.
    selUF.disabled = false;
    if (state.abrangencia === "BR") {
      state.abrangencia = "SP";
      selUF.value = "SP";
    }
  }
}

// ============ lista de candidatos ============
async function carregarCandidatos() {
  const uf = state.abrangencia === "BR" ? "" : `&uf=${state.abrangencia}`;
  const cands = await get(`/api/candidatos?cargo=${state.cargo}${uf}`);
  state.candidatos = cands;
  state.ficha = {};
  cands.forEach(c => (state.ficha[c.sq_candidato] = c));
  // filtra selecionados que não pertencem mais ao filtro atual
  state.selecionados = state.selecionados.filter(sq => state.ficha[sq]);
  renderLista();
  atualizarChipCount();
}

function renderLista() {
  const el = $("lista-candidatos");
  el.innerHTML = "";
  if (state.candidatos.length === 0) {
    el.innerHTML = `<p style="grid-column:1/-1;color:var(--muted);text-align:center;padding:40px">
      Nenhum candidato encontrado para este cargo/UF.</p>`;
    return;
  }
  for (const c of state.candidatos) {
    const sel = state.selecionados.indexOf(c.sq_candidato);
    const div = document.createElement("div");
    div.className = "candidato" + (sel >= 0 ? " selecionado" : "");
    div.style.setProperty("--sel-cor", sel >= 0 ? PALETA[sel] : "");
    if (sel >= 0) {
      div.style.borderColor = PALETA[sel];
      div.style.boxShadow = `0 0 0 2px ${PALETA[sel]}55, 0 8px 24px rgba(0,0,0,.35)`;
    }
    div.innerHTML = `
      <img class="cand-foto" src="${c.foto}" onerror="this.src='/static/silhueta.svg'" alt="">
      <div class="cand-info">
        <div class="cand-nome">${c.nome_urna}</div>
        <div class="cand-meta">${c.numero} · P${c.partido}${c.uf ? " · " + c.uf : ""}</div>
        <div class="cand-votos" data-sq="${c.sq_candidato}">—</div>
        <div class="cand-pct" data-sq-pct="${c.sq_candidato}"></div>
        <div class="cand-barra"><div data-sq-barra="${c.sq_candidato}" style="width:0%"></div></div>
      </div>
      <button class="cand-detalhes" data-detalhes="${c.sq_candidato}">detalhes</button>`;
    div.addEventListener("click", (e) => {
      if (e.target.closest("[data-detalhes]")) return;
      toggleSelecionar(c.sq_candidato);
    });
    el.appendChild(div);
  }
  el.querySelectorAll("[data-detalhes]").forEach(b => {
    b.addEventListener("click", (e) => {
      e.stopPropagation();
      abrirModal(b.dataset.detalhes);
    });
  });
}

function toggleSelecionar(sq) {
  const idx = state.selecionados.indexOf(sq);
  if (idx >= 0) {
    state.selecionados.splice(idx, 1);
  } else if (state.selecionados.length < MAX_SEL) {
    state.selecionados.push(sq);
  } else {
    toast(`Máximo ${MAX_SEL} candidatos.`, "warn");
    return;
  }
  renderLista();
  atualizarChipCount();
}

function atualizarChipCount() {
  const n = state.selecionados.length;
  $("chip-count").textContent = `${n} selecionado(s)`;
  $("btn-comparar").disabled = n < 2;
}

// ============ modal de detalhes ============
async function abrirModal(sq) {
  try {
    const c = await get(`/api/candidato/${sq}`);
    const votos = state.ultimoSnapshot?.candidatos?.find(x => x.sq_candidato === sq);
    $("modal-card").innerHTML = `
      <button class="modal-close" aria-label="Fechar">✕</button>
      <div class="modal-hero">
        <img src="${c.foto}" onerror="this.src='/static/silhueta.svg'">
        <div>
          <div class="modal-nome">${c.nome}</div>
          <div class="modal-urna">Nome urna: ${c.nome_urna}</div>
          <div class="modal-urna">${c.numero} · Partido ${c.partido}${c.uf ? " · " + c.uf : ""}</div>
        </div>
      </div>
      <div class="modal-grid">
        <div class="modal-field"><div class="k">Votos</div><div class="v">${votos ? fmtNum(votos.votos) : "—"}</div></div>
        <div class="modal-field"><div class="k">% Válidos</div><div class="v">${votos ? votos.pct_validos.toFixed(2) + "%" : "—"}</div></div>
        <div class="modal-field"><div class="k">Posição</div><div class="v">${votos ? votos.posicao + "º" : "—"}</div></div>
        <div class="modal-field"><div class="k">Coligação</div><div class="v" style="font-size:13px">${c.coligacao || "—"}</div></div>
      </div>
      <div class="modal-acoes">
        <button class="btn-primary" id="modal-selecionar">
          ${state.selecionados.includes(sq) ? "Remover da comparação" : "Adicionar à comparação"}
        </button>
      </div>
    `;
    $("modal-cand").classList.remove("oculto");
    $("modal-card").querySelector(".modal-close").onclick = fecharModal;
    $("modal-cand").querySelector(".modal-back").onclick = fecharModal;
    $("modal-selecionar").onclick = () => { toggleSelecionar(sq); fecharModal(); };
  } catch (e) { toast("Erro ao abrir: " + e.message, "danger"); }
}
function fecharModal() { $("modal-cand").classList.add("oculto"); }

// ============ comparação ============
function abrirComparacao() {
  if (state.selecionados.length < 2) return;
  $("comparacao").classList.remove("oculto");
  renderCardsComp();
  atualizarComparacao();
  inicializarGraficos();
  $("comparacao").scrollIntoView({ behavior: "smooth", block: "start" });
}

function fecharComparacao() {
  state.selecionados = [];
  $("comparacao").classList.add("oculto");
  renderLista();
  atualizarChipCount();
}

function renderCardsComp() {
  const el = $("cards-comp");
  el.innerHTML = "";
  state.selecionados.forEach((sq, i) => {
    const c = state.ficha[sq];
    if (!c) return;
    const div = document.createElement("div");
    div.className = "card-comp";
    div.style.borderTopColor = PALETA[i];
    div.innerHTML = `
      <div class="badge-pos" data-pos="${sq}">—</div>
      <img src="${c.foto}" onerror="this.src='/static/silhueta.svg'">
      <div class="nome">${c.nome_urna}</div>
      <div class="meta">${c.numero} · P${c.partido}${c.uf ? " · " + c.uf : ""}</div>
      <div class="votos" data-votos="${sq}">—</div>
      <div class="pct" data-pct="${sq}">—</div>`;
    el.appendChild(div);
  });
}

async function atualizarComparacao() {
  if (state.selecionados.length < 2) return;
  const dados = state.ultimoSnapshot;
  if (!dados?.disponivel) {
    $("dif-abs").textContent = "—";
    $("dif-pct").textContent = "—";
    $("dif-prob").textContent = "Sem dados";
    $("dif-prob-hint").textContent = "Aguardando primeiro snapshot.";
    return;
  }
  const map = new Map(dados.candidatos.map(c => [c.sq_candidato, c]));
  state.selecionados.forEach(sq => {
    const c = map.get(sq);
    const votosEl = document.querySelector(`[data-votos="${sq}"]`);
    const pctEl = document.querySelector(`[data-pct="${sq}"]`);
    const posEl = document.querySelector(`[data-pos="${sq}"]`);
    if (c && votosEl) {
      votosEl.textContent = fmtNum(c.votos);
      pctEl.textContent = c.pct_validos.toFixed(2) + "%";
      posEl.textContent = c.posicao + "º";
    }
  });
  const ordenados = state.selecionados
    .map(sq => map.get(sq))
    .filter(Boolean)
    .sort((x, y) => y.votos - x.votos);
  if (ordenados.length >= 2) {
    const dif = ordenados[0].votos - ordenados[1].votos;
    $("dif-abs").textContent = fmtNum(dif);
    $("dif-pct").textContent = (ordenados[0].pct_validos - ordenados[1].pct_validos).toFixed(2) + " pp";
    // probabilidade estimada — dif / restantes_max
    const restantesMax = Math.max(0, (dados.totais.eleitorado_apto || 0) - (ordenados[0].votos + ordenados[1].votos) * 0);
    const pctApurado = dados.totais.pct_apurado || 0;
    if (pctApurado < 20) {
      $("dif-prob").textContent = "EM DISPUTA";
      $("dif-prob-hint").textContent = `Motor matemático silenciado (< 20% apurado)`;
    } else {
      $("dif-prob").textContent = pctApurado >= 99 ? "DEFINIDO" : `~${pctApurado.toFixed(0)}%`;
      $("dif-prob-hint").textContent = `Baseado em ${pctApurado.toFixed(1)}% apurado`;
    }
  }
}

// ============ gráficos ============
function baseOpts(title) {
  return {
    backgroundColor: "transparent",
    tooltip: { trigger: "axis", backgroundColor: "#161b24", borderColor: "#303a4d", textStyle: { color: "#ecf0f7" } },
    legend: { textStyle: { color: "#b6c0d4" }, top: 0, right: 10, icon: "roundRect" },
    grid: { left: 60, right: 20, top: 30, bottom: 30 },
    xAxis: { type: "time", axisLine: { lineStyle: { color: "#303a4d" } }, axisLabel: { color: "#7d8899" } },
    yAxis: { type: "value", axisLine: { lineStyle: { color: "#303a4d" } }, axisLabel: { color: "#7d8899" }, splitLine: { lineStyle: { color: "#1e2531" } } },
    textStyle: { fontFamily: "Inter" },
  };
}

function graf(id) {
  if (state.graficos[id]) state.graficos[id].dispose();
  const c = echarts.init($(id), null, { renderer: "canvas" });
  state.graficos[id] = c;
  window.addEventListener("resize", () => c.resize());
  return c;
}

async function inicializarGraficos() {
  if (state.selecionados.length < 2) return;
  const sqs = state.selecionados.join(",");
  let hist;
  try {
    hist = await get(`/api/apuracao/historico?cargo=${state.cargo}&abrangencia=${state.abrangencia}&candidatos=${sqs}`);
  } catch (e) {
    hist = { series: {} };
  }
  const nomes = state.selecionados.map(sq => state.ficha[sq]?.nome_urna || sq);
  const dadosPor = (idx, campo) => (hist.series[state.selecionados[idx]] || []).map(p => [p.t, p[campo]]);

  graf("graf-votos").setOption({
    ...baseOpts(),
    series: state.selecionados.map((sq, i) => ({
      name: nomes[i], type: "line", smooth: true, showSymbol: false,
      data: dadosPor(i, "votos"), color: PALETA[i], lineStyle: { width: 2.5 },
    })),
  });

  graf("graf-pct").setOption({
    ...baseOpts(),
    yAxis: { ...baseOpts().yAxis, max: 100, axisLabel: { color: "#7d8899", formatter: "{value}%" } },
    series: state.selecionados.map((sq, i) => ({
      name: nomes[i], type: "line", smooth: true, showSymbol: false,
      data: dadosPor(i, "pct"), color: PALETA[i], lineStyle: { width: 2.5 },
      areaStyle: { opacity: 0.08, color: PALETA[i] },
    })),
  });

  // diferença: líder − 2º selecionado
  const seriesDif = [];
  if (state.selecionados.length >= 2) {
    const [A, B] = state.selecionados;
    const mA = new Map((hist.series[A] || []).map(p => [p.t, p.votos]));
    const mB = new Map((hist.series[B] || []).map(p => [p.t, p.votos]));
    for (const t of mA.keys()) if (mB.has(t)) seriesDif.push([t, mA.get(t) - mB.get(t)]);
  }
  graf("graf-dif").setOption({
    ...baseOpts(),
    series: [{
      type: "line", smooth: true, showSymbol: false, data: seriesDif,
      color: "#22c55e", lineStyle: { width: 2.5 },
      areaStyle: { opacity: 0.25, color: "#22c55e" },
      markLine: { symbol: "none", data: [{ yAxis: 0 }], lineStyle: { color: "#7d8899", type: "dashed" } },
    }],
  });

  // faixa de vitória
  const serie = (idx) => {
    const s = hist.series[state.selecionados[idx]] || [];
    return {
      name: nomes[idx], type: "line", smooth: true, showSymbol: false,
      color: PALETA[idx], lineStyle: { width: 2 },
      data: s.map(p => [p.t, p.votos]),
      markArea: {
        itemStyle: { color: PALETA[idx], opacity: 0.12 },
        data: s.map(p => [{ xAxis: p.t, yAxis: p.votos }, { xAxis: p.t, yAxis: p.votos + (p.restantes_max || 0) }]),
      },
    };
  };
  graf("graf-banda").setOption({
    ...baseOpts(),
    series: state.selecionados.map((_, i) => serie(i)),
  });
}

// ============ painel superior ============
async function atualizarPainelTotais() {
  const dados = state.ultimoSnapshot;
  if (!dados?.disponivel) {
    $("pct-apurado").textContent = "0%";
    $("secoes").textContent = "0 / 0";
    $("comparecimento").textContent = "0";
    $("brancos-nulos").textContent = "0 / 0";
    $("ultimo").textContent = "—";
    $("prog-apurado").style.width = "0%";
    return;
  }
  const t = dados.totais;
  $("pct-apurado").textContent = t.pct_apurado.toFixed(2) + "%";
  $("prog-apurado").style.width = t.pct_apurado + "%";
  $("secoes").textContent = fmtNum(t.secoes_totalizadas);
  $("secoes-sub").textContent = `de ${fmtNum(t.secoes_total)}`;
  $("comparecimento").textContent = fmtNum(t.comparecimento);
  $("brancos-nulos").textContent = `${fmtNum(t.votos_brancos)} · ${fmtNum(t.votos_nulos)}`;
  $("ultimo").textContent = fmtHora(dados.coletado_em);

  // atualiza cards da lista
  const maxV = Math.max(1, ...dados.candidatos.map(c => c.votos));
  dados.candidatos.forEach(c => {
    const votos = document.querySelector(`[data-sq="${c.sq_candidato}"]`);
    const pct = document.querySelector(`[data-sq-pct="${c.sq_candidato}"]`);
    const barra = document.querySelector(`[data-sq-barra="${c.sq_candidato}"]`);
    if (votos) votos.textContent = fmtNum(c.votos);
    if (pct) pct.textContent = c.pct_validos.toFixed(2) + "% dos válidos";
    if (barra) barra.style.width = (c.votos / maxV * 100) + "%";
  });
}

// ============ mapa ============
async function atualizarMapa() {
  // Busca líder por UF no backend. Enquanto não há endpoint dedicado,
  // usa dados agregados do snapshot atual quando o cargo for nacional,
  // ou destaca apenas a UF ativa quando estadual.
  let dadosPorUF = {};
  try {
    const r = await fetch(`/api/apuracao/lideres-por-uf?cargo=${state.cargo}`);
    if (r.ok) {
      const j = await r.json();
      // j.ufs = { "SP": { sq_candidato, nome_lider, votos, cor_idx }, ... }
      for (const [uf, d] of Object.entries(j.ufs || {})) {
        dadosPorUF[uf] = {
          valor: d.votos || 0,
          cor: PALETA[d.cor_idx % PALETA.length] || "#f0b429",
          nome_lider: d.nome_lider,
          votos: d.votos,
        };
      }
    }
  } catch (e) { /* backend ainda sem dados; segue com destaque simples */ }

  if (Object.keys(dadosPorUF).length === 0 && state.abrangencia !== "BR") {
    dadosPorUF[state.abrangencia] = { valor: 1, cor: "#f0b429", nome_lider: "UF selecionada" };
  }

  await renderMapaBrasil($("mapa-brasil"), dadosPorUF);
  onCliqueUF((sigla) => {
    if (state.cargo === 1) {
      toast("Presidente é nacional. Troque para outro cargo para filtrar por UF.", "warn");
      return;
    }
    state.abrangencia = sigla;
    $("sel-uf").value = sigla;
    onFiltroChange();
  });

  // Legenda dinâmica: se há líderes por UF, mostra por candidato
  const leg = $("mapa-legenda");
  const nomes = new Map();
  for (const [uf, d] of Object.entries(dadosPorUF)) {
    if (d.nome_lider && d.nome_lider !== "UF selecionada") {
      nomes.set(d.nome_lider, d.cor);
    }
  }
  if (nomes.size) {
    leg.innerHTML = `<h3>Líderes por UF</h3>` +
      Array.from(nomes.entries()).map(([n, c]) =>
        `<div class="leg-item"><span class="leg-cor" style="background:${c}"></span>${n}</div>`
      ).join("") +
      `<div class="leg-item"><span class="leg-cor" style="background:#1e2531"></span>Sem dados</div>`;
  } else {
    leg.innerHTML = `
      <h3>Mapa por UF</h3>
      <div class="leg-item"><span class="leg-cor" style="background:#f0b429"></span> UF ativa</div>
      <div class="leg-item"><span class="leg-cor" style="background:#1e2531"></span> Sem dados</div>
      <p style="color:var(--muted);font-size:12px;margin-top:12px">
        No dia da apuração, cada UF será colorida pelo candidato líder.
        Clique numa UF para filtrar (cargo estadual).
      </p>`;
  }
}

// ============ eventos ============
async function carregarEventos() {
  let evs = [];
  try { evs = await get(`/api/eventos?cargo=${state.cargo}&abrangencia=${state.abrangencia}`); } catch (e) {}
  const ul = $("lista-eventos");
  if (evs.length === 0) {
    ul.innerHTML = `<li class="vazio">Nenhum evento ainda. Aguardando apuração começar.</li>`;
    return;
  }
  ul.innerHTML = "";
  for (const ev of evs.reverse()) {
    const nome = state.ficha[ev.sq_candidato_a]?.nome_urna || ev.sq_candidato_a;
    let tipoBadge = "ev-tipo", texto = "";
    if (ev.tipo === "ELEITO_1T") { tipoBadge += " ok"; texto = `<strong>${nome}</strong> eleito(a) no 1º turno.`; }
    else if (ev.tipo === "SEGUNDO_TURNO_DEFINIDO") {
      tipoBadge += " warn";
      const b = state.ficha[ev.sq_candidato_b]?.nome_urna || ev.sq_candidato_b;
      texto = `2º turno definido: <strong>${nome}</strong> × <strong>${b}</strong>`;
    } else { tipoBadge += " ok"; texto = `<strong>${nome}</strong> eleito(a).`; }
    const li = document.createElement("li");
    li.innerHTML = `<time>${fmtHora(ev.ocorrido_em)}</time><span class="${tipoBadge}">${ev.tipo}</span><span class="ev-texto">${texto}</span>`;
    ul.appendChild(li);
  }
}

// ============ ciclo ============
async function refreshApuracao() {
  try {
    state.ultimoSnapshot = await get(`/api/apuracao/atual?cargo=${state.cargo}&abrangencia=${state.abrangencia}`);
  } catch (e) {
    state.ultimoSnapshot = { disponivel: false };
  }
  atualizarPainelTotais();
  if (state.selecionados.length >= 2 && !$("comparacao").classList.contains("oculto")) {
    atualizarComparacao();
  }
}

function conectarWS() {
  if (state.ws) state.ws.close();
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  const ws = new WebSocket(`${proto}//${location.host}/ws/apuracao?cargo=${state.cargo}&abrangencia=${state.abrangencia}`);
  ws.onopen = () => {
    $("conexao").querySelector(".dot").classList.add("on");
    $("conexao-label").textContent = "ao vivo";
  };
  ws.onclose = () => {
    $("conexao").querySelector(".dot").classList.remove("on");
    $("conexao-label").textContent = "reconectando…";
    setTimeout(conectarWS, 3000);
  };
  ws.onmessage = async (m) => {
    const msg = JSON.parse(m.data);
    if (msg.type === "snapshot") {
      await refreshApuracao();
      if (state.selecionados.length >= 2) await inicializarGraficos();
      for (const ev of msg.eventos || []) {
        const nome = state.ficha[ev.sq_candidato_a]?.nome_urna || ev.sq_candidato_a;
        toast(ev.tipo === "ELEITO_1T" ? `🎉 ${nome} eleito(a) no 1º turno!`
            : ev.tipo === "SEGUNDO_TURNO_DEFINIDO" ? `⚡ 2º turno matematicamente definido`
            : `✓ ${nome} eleito(a)`);
      }
      await carregarEventos();
    }
  };
  state.ws = ws;
}

async function onFiltroChange() {
  ajustarUFParaCargo();
  state.selecionados = [];
  $("comparacao").classList.add("oculto");
  await carregarCandidatos();
  await refreshApuracao();
  await carregarEventos();
  atualizarMapa();
  conectarWS();
}

async function pedirNotificacoes() {
  if (!("Notification" in window)) return toast("Navegador sem suporte a notificações.", "warn");
  const p = await Notification.requestPermission();
  toast(p === "granted" ? "🔔 Notificações ativadas" : "Notificações negadas", p === "granted" ? "" : "warn");
}

// ============ boot ============
async function boot() {
  $("sel-cargo").addEventListener("change", (e) => { state.cargo = +e.target.value; onFiltroChange(); });
  $("sel-uf").addEventListener("change", (e) => { state.abrangencia = e.target.value; onFiltroChange(); });
  $("btn-fechar").addEventListener("click", fecharComparacao);
  $("btn-comparar").addEventListener("click", abrirComparacao);
  $("btn-notif").addEventListener("click", pedirNotificacoes);
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") fecharModal(); });

  try {
    const ufs = await get("/api/ufs");
    const selUF = $("sel-uf");
    for (const u of ufs) {
      const opt = document.createElement("option");
      opt.value = u.sigla; opt.textContent = `${u.sigla} — ${u.nome}`;
      selUF.appendChild(opt);
    }
  } catch (e) { /* ok */ }

  ajustarUFParaCargo();
  await carregarCandidatos();
  await refreshApuracao();
  await carregarEventos();
  atualizarMapa();
  conectarWS();
}

boot().catch(e => { console.error(e); toast("Erro: " + e.message, "danger"); });
