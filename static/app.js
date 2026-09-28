import { renderMapa } from "/static/mapa-br.js";
import { corDoPartido, siglaDoPartido, badgePartidoHtml } from "/static/partidos.js";

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
  filtro: { texto: "", partido: "", ordenar: "votos" },
  proporcional: null,  // { candidatos: [{sq_candidato, status}], qe, barreira, vagas }
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
  const cont = $("toasts");
  // Máximo 3 toasts visíveis; remove o mais antigo se estourar
  while (cont.children.length >= 3) cont.firstElementChild.remove();
  const div = document.createElement("div");
  div.className = "toast " + tipo;
  div.textContent = msg;
  cont.appendChild(div);
  setTimeout(() => { div.style.opacity = "0"; setTimeout(() => div.remove(), 300); }, 5000);
}

// ============ regras cargo × UF ============
function cargoRequerUF(cargo) {
  return cargo !== 1;  // 1 = Presidente é nacional
}

function ajustarUFParaCargo() {
  const selUF = $("sel-uf");
  selUF.disabled = false;
  if (state.cargo === 1) {
    // Presidente: nacional por padrão, mas pode filtrar por UF pra ver
    // como o candidato nacional está indo naquele estado.
    if (!state.abrangencia) { state.abrangencia = "BR"; selUF.value = "BR"; }
  } else {
    // Governador/Senador/Deputado precisam de UF. Se estava BR, cai em SP.
    if (state.abrangencia === "BR") {
      state.abrangencia = "SP";
      selUF.value = "SP";
    }
  }
}

// ============ lista de candidatos ============
async function carregarCandidatos() {
  renderSkeletons(6);
  const uf = state.abrangencia === "BR" ? "" : `&uf=${state.abrangencia}`;
  const cands = await get(`/api/candidatos?cargo=${state.cargo}${uf}`);
  atualizarSubtitulo();
  state.candidatos = cands;
  state.ficha = {};
  cands.forEach(c => (state.ficha[c.sq_candidato] = c));
  // filtra selecionados que não pertencem mais ao filtro atual
  state.selecionados = state.selecionados.filter(sq => state.ficha[sq]);
  atualizarFiltroPartidos();
  renderLista();
  atualizarChipCount();
}

function candidatosFiltrados() {
  const t = state.filtro.texto.trim().toLowerCase();
  const p = state.filtro.partido;
  const votosPorSq = new Map(
    (state.ultimoSnapshot?.candidatos || []).map(c => [c.sq_candidato, c.votos])
  );
  let arr = state.candidatos.filter(c => {
    if (p && String(c.partido) !== p) return false;
    if (!t) return true;
    return (
      (c.nome_urna || "").toLowerCase().includes(t) ||
      String(c.numero).includes(t) ||
      String(c.partido).includes(t)
    );
  });
  const ord = state.filtro.ordenar;
  arr.sort((a, b) => {
    if (ord === "nome") return (a.nome_urna || "").localeCompare(b.nome_urna || "");
    if (ord === "numero") return a.numero - b.numero;
    // votos (padrão)
    return (votosPorSq.get(b.sq_candidato) || 0) - (votosPorSq.get(a.sq_candidato) || 0);
  });
  return arr;
}

function atualizarFiltroPartidos() {
  const sel = $("filtro-partido");
  const partidos = [...new Set(state.candidatos.map(c => String(c.partido)))].sort((a, b) => +a - +b);
  const atual = sel.value;
  sel.innerHTML = `<option value="">Todos os partidos</option>` +
    partidos.map(p => `<option value="${p}">${siglaDoPartido(+p)} (${p})</option>`).join("");
  if (partidos.includes(atual)) sel.value = atual;
}

// Cor oficial do partido (fallback HSL pra desconhecidos)
const corPartido = corDoPartido;

// Iniciais do candidato (usa nome_urna, ex.: "TARCÍSIO DE FREITAS" → "TF")
function iniciais(nome) {
  if (!nome) return "?";
  const partes = nome.trim().split(/\s+/).filter(p => p.length > 1);
  if (partes.length === 0) return nome.slice(0, 2).toUpperCase();
  if (partes.length === 1) return partes[0].slice(0, 2).toUpperCase();
  return (partes[0][0] + partes[partes.length - 1][0]).toUpperCase();
}

// Substitui a img por um div com iniciais + cor do partido
function fallbackFoto(imgEl, nome, partido) {
  const div = document.createElement("div");
  div.className = imgEl.className + " cand-foto-fallback";
  div.style.background = corPartido(partido || 0);
  div.textContent = iniciais(nome);
  imgEl.replaceWith(div);
}

// Retry: se a foto falhar (Akamai rate-limit costuma bloquear em picos),
// espera um tempo aleatório e tenta 1 vez mais antes de cair no fallback.
function anexarFotoComRetry(img, nome, partido) {
  let tentativas = 0;
  img.addEventListener("error", () => {
    tentativas++;
    if (tentativas === 1) {
      // Espera 500-2500ms (jitter) e tenta de novo com cache-bust
      const delay = 500 + Math.random() * 2000;
      setTimeout(() => {
        img.src = img.src.split("?")[0] + "?r=" + Date.now();
      }, delay);
    } else {
      fallbackFoto(img, nome, partido);
    }
  });
}

function renderSkeletons(n = 6) {
  const el = $("lista-candidatos");
  el.innerHTML = "";
  for (let i = 0; i < n; i++) {
    const div = document.createElement("div");
    div.className = "candidato loading";
    div.innerHTML = `
      <div class="cand-foto"></div>
      <div class="cand-info">
        <div class="cand-nome"></div>
        <div class="cand-meta"></div>
        <div class="cand-votos"></div>
      </div>`;
    el.appendChild(div);
  }
}

function renderLista() {
  const el = $("lista-candidatos");
  el.innerHTML = "";
  const filtrados = candidatosFiltrados();
  $("chip-total").textContent =
    filtrados.length === state.candidatos.length
      ? `${state.candidatos.length} candidatos`
      : `${filtrados.length} de ${state.candidatos.length}`;
  if (state.candidatos.length === 0) {
    el.innerHTML = `<div class="empty-state">
      <div class="clock">🕔</div>
      <h3>Aguardando dados</h3>
      <p>O TSE publica os resultados quando as urnas fecham (domingo, 17h).
         Enquanto isso, você pode navegar pelo mapa e explorar os candidatos.</p>
    </div>`;
    return;
  }
  if (filtrados.length === 0) {
    el.innerHTML = `<div class="empty-state">
      <h3>Nada encontrado</h3>
      <p>Ajuste o filtro ou a busca para ver candidatos.</p>
    </div>`;
    return;
  }
  for (const c of filtrados) {
    const sel = state.selecionados.indexOf(c.sq_candidato);
    const div = document.createElement("div");
    div.className = "candidato" + (sel >= 0 ? " selecionado" : "");
    div.style.setProperty("--sel-cor", sel >= 0 ? PALETA[sel] : "");
    if (sel >= 0) {
      div.style.borderColor = PALETA[sel];
      div.style.boxShadow = `0 0 0 2px ${PALETA[sel]}55, 0 8px 24px rgba(0,0,0,.35)`;
    }
    const prop = statusProporcionalDe(c.sq_candidato);
    let badgeProp = "";
    if (prop) {
      const cls = {
        eleito: "badge-eleito",
        suplente: "badge-suplente",
        nao_atingiu_barreira: "badge-barreira",
        partido_sem_vaga: "badge-sem-vaga",
      }[prop.status] || "";
      const label = {
        eleito: "✓ ELEITO",
        suplente: "SUPLENTE",
        nao_atingiu_barreira: "S/ BARREIRA",
        partido_sem_vaga: "PARTIDO S/ VAGA",
      }[prop.status] || "";
      const fed = prop.federacao ? ` · Fed.` : "";
      badgeProp = `<div class="badge-prop ${cls}" title="${prop.status}">${label}${fed}</div>`;
    }
    const pillPart = badgePartidoHtml(c.partido);
    div.innerHTML = `
      <img class="cand-foto" src="${c.foto}" alt="" loading="lazy" decoding="async">
      <div class="cand-info">
        <div class="cand-nome">${c.nome_urna}</div>
        <div class="cand-meta">${c.numero} · ${pillPart}${c.uf ? " · " + c.uf : ""}</div>
        ${badgeProp}
        <div class="cand-votos" data-sq="${c.sq_candidato}">—</div>
        <div class="cand-pct" data-sq-pct="${c.sq_candidato}"></div>
        <div class="cand-barra"><div data-sq-barra="${c.sq_candidato}" style="width:0%"></div></div>
      </div>
      <button class="cand-detalhes" data-detalhes="${c.sq_candidato}">detalhes</button>`;
    anexarFotoComRetry(div.querySelector("img.cand-foto"), c.nome_urna, c.partido);
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

function atualizarSubtitulo() {
  const cargoNome = { 1: "Presidente", 3: "Governador", 5: "Senador", 6: "Deputado Federal", 7: "Deputado Estadual" }[state.cargo] || "";
  const abr = state.abrangencia === "BR" ? "Brasil" : state.abrangencia;
  $("titulo-lista").textContent = `${cargoNome} · ${abr}`;
  if (state.cargo === 1 && state.abrangencia !== "BR") {
    $("sub-lista").innerHTML = `Votos dos candidatos presidenciais <strong>no estado ${abr}</strong>. Selecione até <strong>4</strong> para comparar.`;
  } else {
    $("sub-lista").innerHTML = `Selecione até <strong>4 candidatos</strong> para comparar lado a lado.`;
  }
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
    const corP = corPartido(c.partido);
    $("modal-card").innerHTML = `
      <button class="modal-close" aria-label="Fechar">✕</button>
      <div class="modal-acento" style="background:linear-gradient(90deg, ${corP}, transparent 70%)"></div>
      <div class="modal-hero">
        <img src="${c.foto}">
        <div>
          <div class="modal-nome">${c.nome}</div>
          <div class="modal-urna">Nome urna: ${c.nome_urna}</div>
          <div class="modal-urna">${c.numero} · ${badgePartidoHtml(c.partido)}${c.uf ? " · " + c.uf : ""}</div>
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
    const img = $("modal-card").querySelector(".modal-hero img");
    if (img) anexarFotoComRetry(img, c.nome_urna, c.partido);
  } catch (e) { toast("Erro ao abrir: " + e.message, "danger"); }
}
function fecharModal() { $("modal-cand").classList.add("oculto"); }

async function abrirModalMunicipio(codIbge, nomeMun) {
  const nome = nomeMun || `Município ${codIbge}`;
  try {
    const dados = await get(`/api/apuracao/municipio?cargo=${state.cargo}&uf=${state.abrangencia}&cod_ibge=${codIbge}`);
    const cands = dados.candidatos || [];
    if (!cands.length) {
      toast(`${nome}: sem dados ainda`, "warn");
      return;
    }
    $("modal-card").innerHTML = `
      <button class="modal-close" aria-label="Fechar">✕</button>
      <div class="modal-hero" style="flex-direction:column;align-items:flex-start">
        <div class="modal-nome">${nome}</div>
        <div class="modal-urna">Ranking em ${state.abrangencia} · ${cands.length} candidatos</div>
      </div>
      <div style="max-height:400px;overflow-y:auto">
        ${cands.slice(0, 20).map((c, i) => `
          <div style="display:flex;gap:10px;padding:8px 4px;border-bottom:1px solid var(--line);align-items:center">
            <div style="min-width:24px;font-weight:700;color:var(--muted)">${i+1}</div>
            <div style="flex:1">
              <div style="font-weight:600">${c.nome_urna}</div>
              <div style="font-size:11px;color:var(--muted);font-family:'JetBrains Mono',monospace">${c.numero} · P${c.partido}</div>
            </div>
            <div style="text-align:right;min-width:120px">
              <div style="font-weight:700;font-variant-numeric:tabular-nums">${fmtNum(c.votos)}</div>
              <div style="font-size:11px;color:var(--muted)">${c.pct_validos.toFixed(1)}%</div>
            </div>
          </div>
        `).join("")}
      </div>
      ${cands.length > 20 ? `<div style="color:var(--muted);font-size:12px;padding:8px 0;text-align:center">+ ${cands.length - 20} outros candidatos</div>` : ""}
    `;
    $("modal-cand").classList.remove("oculto");
    $("modal-card").querySelector(".modal-close").onclick = fecharModal;
    $("modal-cand").querySelector(".modal-back").onclick = fecharModal;
  } catch (e) {
    toast("Erro: " + e.message, "danger");
  }
}

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
      <img src="${c.foto}" loading="lazy" decoding="async">
      <div class="nome">${c.nome_urna}</div>
      <div class="meta">${c.numero} · ${badgePartidoHtml(c.partido)}${c.uf ? " · " + c.uf : ""}</div>
      <div class="votos" data-votos="${sq}">—</div>
      <div class="pct" data-pct="${sq}">—</div>`;
    anexarFotoComRetry(div.querySelector("img"), c.nome_urna, c.partido);
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
  $("abstencoes").textContent = fmtNum(t.abstencoes);
  const totalAptos = t.eleitorado_apto || 1;
  const pctCompar = (t.comparecimento / totalAptos * 100).toFixed(1);
  const pctAbst = (t.abstencoes / totalAptos * 100).toFixed(1);
  $("pct-comparecimento").textContent = `${pctCompar}% dos aptos`;
  $("pct-abstencoes").textContent = `${pctAbst}% dos aptos`;
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
  const container = $("mapa-brasil");
  const leg = $("mapa-legenda");

  // Modo Brasil: mapa dos 27 estados
  if (state.abrangencia === "BR") {
    const dadosPorUF = {};
    try {
      const r = await fetch(`/api/apuracao/lideres-por-uf?cargo=${state.cargo}`);
      if (r.ok) {
        const j = await r.json();
        for (const [uf, d] of Object.entries(j.ufs || {})) {
          dadosPorUF[uf] = {
            valor: d.votos || 0,
            cor: PALETA[d.cor_idx % PALETA.length] || "#f0b429",
            nome_lider: d.nome_lider,
            votos: d.votos,
          };
        }
      }
    } catch (e) {}
    await renderMapa(container, "BR", dadosPorUF, {
      onClickArea: (sigla) => {
        state.abrangencia = sigla;
        $("sel-uf").value = sigla;
        onFiltroChange();
      },
    });
    renderLegenda(leg, dadosPorUF, {
      tituloVazio: "Mapa por UF",
      tituloCheio: "Líderes por UF",
      dica: "Cada UF colorida pelo candidato líder daquele estado. Clique para ver o mapa do município.",
    });
    return;
  }

  // Modo UF: mapa dos municípios daquela UF
  const dadosPorMun = {};
  try {
    const r = await fetch(`/api/apuracao/lideres-por-municipio?cargo=${state.cargo}&uf=${state.abrangencia}`);
    if (r.ok) {
      const j = await r.json();
      for (const [mun, d] of Object.entries(j.municipios || {})) {
        dadosPorMun[mun] = {
          valor: d.votos || 0,
          cor: PALETA[(d.cor_idx || 0) % PALETA.length],
          nome_lider: d.nome_lider,
          votos: d.votos,
        };
      }
    }
  } catch (e) {}
  await renderMapa(container, state.abrangencia, dadosPorMun, {
    onClickArea: (codIbge, nomeMun) => abrirModalMunicipio(codIbge, nomeMun),
  });
  renderLegenda(leg, dadosPorMun, {
    tituloVazio: `Municípios de ${state.abrangencia}`,
    tituloCheio: `Líderes por município (${state.abrangencia})`,
    dica: "Cada município colorido pelo candidato líder. Volte para 'Brasil' para ver o mapa nacional.",
  });
}

function renderLegenda(leg, dados, texto) {
  const nomes = new Map();
  for (const d of Object.values(dados)) {
    if (d.nome_lider) nomes.set(d.nome_lider, d.cor);
  }
  if (nomes.size) {
    leg.innerHTML = `<h3>${texto.tituloCheio}</h3>` +
      Array.from(nomes.entries()).map(([n, c]) =>
        `<div class="leg-item"><span class="leg-cor" style="background:${c}"></span>${n}</div>`
      ).join("") +
      `<div class="leg-item"><span class="leg-cor" style="background:#1e2531"></span>Sem dados</div>`;
  } else {
    leg.innerHTML = `<h3>${texto.tituloVazio}</h3>
      <div class="leg-item"><span class="leg-cor" style="background:#1e2531"></span>Sem dados</div>
      <p style="color:var(--muted);font-size:12px;margin-top:12px">${texto.dica}</p>`;
  }
}

// ============ eventos ============
const TIPOS_EVENTO = {
  ELEITO_1T:                 { label: "Eleito 1T", classe: "ok",     emoji: "🎉" },
  ELEITO_MAJORITARIO:        { label: "Eleito",    classe: "ok",     emoji: "🎉" },
  SEGUNDO_TURNO_DEFINIDO:    { label: "2º Turno",  classe: "warn",   emoji: "⚡" },
  VIRADA:                    { label: "Virada",    classe: "warn",   emoji: "🔄" },
  MATEMATICAMENTE_ELIMINADO: { label: "Eliminado", classe: "danger", emoji: "❌" },
};

async function carregarEventos() {
  let evs = [];
  try { evs = await get(`/api/eventos?cargo=${state.cargo}&abrangencia=${state.abrangencia}`); } catch (e) {}
  const ul = $("lista-eventos");
  if (evs.length === 0) {
    ul.innerHTML = `<li class="vazio">Nenhum evento ainda. Aguardando apuração começar.</li>`;
    return;
  }
  ul.innerHTML = "";
  for (const ev of evs.slice().reverse()) {
    const nome = state.ficha[ev.sq_candidato_a]?.nome_urna || ev.sq_candidato_a;
    const meta = TIPOS_EVENTO[ev.tipo] || { label: ev.tipo, classe: "", emoji: "•" };
    let texto = "";
    if (ev.tipo === "SEGUNDO_TURNO_DEFINIDO") {
      const b = state.ficha[ev.sq_candidato_b]?.nome_urna || ev.sq_candidato_b;
      texto = `2º turno definido: <strong>${nome}</strong> × <strong>${b}</strong>`;
    } else if (ev.tipo === "VIRADA") {
      const b = state.ficha[ev.sq_candidato_b]?.nome_urna || ev.sq_candidato_b;
      texto = `<strong>${nome}</strong> passou <strong>${b}</strong>`;
    } else if (ev.tipo === "MATEMATICAMENTE_ELIMINADO") {
      texto = `<strong>${nome}</strong> matematicamente eliminado`;
    } else if (ev.tipo === "ELEITO_1T") {
      texto = `<strong>${nome}</strong> eleito(a) no 1º turno`;
    } else {
      texto = `<strong>${nome}</strong> eleito(a)`;
    }
    const li = document.createElement("li");
    li.innerHTML = `
      <time>${fmtHora(ev.ocorrido_em)}</time>
      <span class="ev-tipo ${meta.classe}">${meta.emoji} ${meta.label}</span>
      <span class="ev-texto">${texto}</span>`;
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
  // Se for cargo proporcional (Deputado Fed/Est) e temos UF, busca cálculo
  state.proporcional = null;
  if ((state.cargo === 6 || state.cargo === 7) && state.abrangencia !== "BR") {
    try {
      const p = await get(`/api/apuracao/proporcional?cargo=${state.cargo}&uf=${state.abrangencia}`);
      if (p.disponivel) state.proporcional = p;
    } catch (e) { /* sem dados ainda */ }
  }
  atualizarPainelTotais();
  atualizarPainelProporcional();
  if (state.selecionados.length >= 2 && !$("comparacao").classList.contains("oculto")) {
    atualizarComparacao();
  }
  renderLista();  // re-renderiza para pintar badges de eleito
}

function atualizarPainelProporcional() {
  let el = $("prop-info");
  if (!el) return;
  if (!state.proporcional) {
    el.classList.add("oculto");
    return;
  }
  const p = state.proporcional;
  el.classList.remove("oculto");
  el.innerHTML = `
    <div><span class="rot">Vagas</span><span class="val">${p.vagas}</span></div>
    <div><span class="rot">Quociente Eleitoral</span><span class="val">${p.quociente_eleitoral.toLocaleString('pt-BR')}</span></div>
    <div><span class="rot">Barreira (10% QE)</span><span class="val">${p.barreira_10pct.toLocaleString('pt-BR')}</span></div>
    <div><span class="rot">Válidos</span><span class="val">${p.votos_validos.toLocaleString('pt-BR')}</span></div>
  `;
}

function statusProporcionalDe(sq) {
  if (!state.proporcional) return null;
  return state.proporcional.candidatos.find(c => c.sq_candidato === sq);
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

  // Header ganha sombra ao rolar
  const hero = document.querySelector(".hero");
  const onScroll = () => hero.classList.toggle("scrolled", window.scrollY > 8);
  window.addEventListener("scroll", onScroll, { passive: true });
  onScroll();

  // filtros da lista
  let buscaTimer;
  $("busca-nome").addEventListener("input", (e) => {
    clearTimeout(buscaTimer);
    buscaTimer = setTimeout(() => {
      state.filtro.texto = e.target.value;
      renderLista();
    }, 150);
  });
  $("filtro-partido").addEventListener("change", (e) => {
    state.filtro.partido = e.target.value;
    renderLista();
  });
  $("ordenar").addEventListener("change", (e) => {
    state.filtro.ordenar = e.target.value;
    renderLista();
  });

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
