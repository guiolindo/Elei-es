// Wizard de verificação por seção. 4 passos:
//   1. UF (chips) → 2. Município (bottom-sheet) → 3. Zona + Seção (bottom-sheet) → 4. Cargo/Turno
// Troquei datalist por bottom-sheet com busca e lista clicável. Datalist nativo
// não aparecia direito em mobile e a seleção implícita por input confundia.

const $ = id => document.getElementById(id);
const fmt = new Intl.NumberFormat("pt-BR").format;

const UFS = ["AC","AL","AP","AM","BA","CE","DF","ES","GO","MA","MT","MS","MG","PA","PB","PR","PE","PI","RJ","RN","RS","RO","RR","SC","SP","SE","TO","ZZ"];

const state = {
  uf: null,
  municipio: null,  // { codigo, nome }
  zona: null,       // string
  secao: null,      // string
  cargo: "1",
  turno: "1",
  cidades: [],
  zonas: [],        // [{codigo, secoes:[...]}]
};

// ============ Steps ============
function marcarStep(n, status) {
  const s = $(`s${n}`);
  s.classList.remove("ativa", "pronta");
  if (status === "ativa") s.classList.add("ativa");
  if (status === "pronta") s.classList.add("pronta");
}

function setPickerLabel(btnId, texto, placeholder) {
  const b = $(btnId);
  if (texto) {
    b.innerHTML = `<span>${texto}</span><span class="pb-arrow">▾</span>`;
  } else {
    b.innerHTML = `<span class="pb-placeholder">${placeholder}</span><span class="pb-arrow">▾</span>`;
  }
}

function atualizarUI() {
  $("v-uf").textContent = state.uf || "";
  $("v-mu").textContent = state.municipio?.nome || "";
  $("v-zs").textContent = state.zona && state.secao ? `Zona ${state.zona} · Seção ${state.secao}` : "";
  $("v-ct").textContent = `${nomeCargo(state.cargo)} · ${state.turno}º turno`;

  // Labels dos pickers
  setPickerLabel("btn-municipio",
    state.municipio?.nome,
    state.uf ? "Toque para escolher a cidade" : "Selecione o estado primeiro");
  $("btn-municipio").disabled = !state.uf;

  setPickerLabel("btn-zona",
    state.zona ? `Zona ${state.zona}` : null,
    state.municipio ? "Toque para escolher a zona" : "Selecione o município");
  $("btn-zona").disabled = !state.municipio;

  setPickerLabel("btn-secao",
    state.secao ? `Seção ${state.secao}` : null,
    state.zona ? "Toque para escolher a seção" : "Selecione a zona");
  $("btn-secao").disabled = !state.zona;

  // Step ativo
  if (!state.uf)                         [1,2,3,4].forEach(n => marcarStep(n, n===1?"ativa":"inativa"));
  else if (!state.municipio)             { marcarStep(1,"pronta"); marcarStep(2,"ativa"); marcarStep(3,"inativa"); marcarStep(4,"inativa"); }
  else if (!state.zona || !state.secao)  { marcarStep(1,"pronta"); marcarStep(2,"pronta"); marcarStep(3,"ativa"); marcarStep(4,"inativa"); }
  else                                   { marcarStep(1,"pronta"); marcarStep(2,"pronta"); marcarStep(3,"pronta"); marcarStep(4,"ativa"); }

  $("btn-buscar").disabled = !(state.uf && state.municipio && state.zona && state.secao);
}

function nomeCargo(c) {
  return {1:"Presidente",3:"Governador",5:"Senador",6:"Dep. Federal",7:"Dep. Estadual"}[c] || "?";
}

// ============ Bottom-sheet picker ============
let _sheetOnPick = null;
let _sheetItems = [];
let _sheetFilter = (q, it) => it.label.toLocaleLowerCase("pt-BR").includes(q.toLocaleLowerCase("pt-BR"));

function abrirSheet({ titulo, items, onPick, placeholder = "Buscar...", filter }) {
  _sheetOnPick = onPick;
  _sheetItems = items;
  if (filter) _sheetFilter = filter;
  $("sheet-titulo").textContent = titulo;
  const b = $("sheet-busca");
  b.value = "";
  b.placeholder = placeholder;
  renderSheetLista("");
  $("sheet").classList.add("aberto");
  document.body.style.overflow = "hidden";
  setTimeout(() => b.focus(), 50);
}

function fecharSheet() {
  $("sheet").classList.remove("aberto");
  document.body.style.overflow = "";
  _sheetOnPick = null;
  _sheetItems = [];
}

function renderSheetLista(q) {
  const lista = $("sheet-lista");
  const filtered = q ? _sheetItems.filter(it => _sheetFilter(q, it)) : _sheetItems;
  if (!filtered.length) {
    lista.innerHTML = `<div class="sheet-vazio">Nenhum resultado para "${q}"</div>`;
    return;
  }
  // Limita a 500 pra não travar scroll — usuário filtra se precisar
  const slice = filtered.slice(0, 500);
  lista.innerHTML = slice.map(it => `
    <button type="button" class="sheet-opt" data-value="${it.value}">
      <span>${it.label}</span>
      ${it.sub ? `<span class="sheet-opt-sub">${it.sub}</span>` : ""}
    </button>
  `).join("");
  if (filtered.length > 500) {
    lista.innerHTML += `<div class="sheet-vazio">+${filtered.length - 500} itens — refine a busca</div>`;
  }
  lista.querySelectorAll(".sheet-opt").forEach(btn => {
    btn.addEventListener("click", () => {
      const val = btn.dataset.value;
      const it = _sheetItems.find(x => String(x.value) === val);
      if (_sheetOnPick) _sheetOnPick(it);
      fecharSheet();
    });
  });
}

$("sheet-busca").addEventListener("input", e => renderSheetLista(e.target.value.trim()));
document.querySelectorAll("[data-sheet-close]").forEach(el =>
  el.addEventListener("click", fecharSheet));
document.addEventListener("keydown", e => {
  if (e.key === "Escape" && $("sheet").classList.contains("aberto")) fecharSheet();
});

// ============ Passo 1: UFs ============
function renderUFs() {
  const wrap = $("ufs");
  wrap.innerHTML = "";
  for (const uf of UFS) {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "urna-uf-btn" + (state.uf === uf ? " ativo" : "");
    b.textContent = uf;
    b.addEventListener("click", () => selecionarUF(uf));
    wrap.appendChild(b);
  }
}

async function selecionarUF(uf) {
  state.uf = uf;
  state.municipio = null;
  state.zona = null;
  state.secao = null;
  state.cidades = [];
  state.zonas = [];
  renderUFs();
  atualizarUI();
  $("s2").scrollIntoView({ behavior: "smooth", block: "center" });

  if (uf === "ZZ") {
    $("mu-hint").textContent = "Para o exterior, use o site oficial do TSE.";
    return;
  }
  $("mu-hint").textContent = "Carregando municípios...";
  try {
    const r = await fetch(`/api/municipios?uf=${uf}`);
    const j = await r.json();
    state.cidades = j.municipios || [];
    if (state.cidades.length) {
      $("mu-hint").textContent = `${state.cidades.length} municípios disponíveis em ${uf}.`;
    } else {
      $("mu-hint").textContent = j.erro || "TSE ainda não publicou a lista.";
    }
  } catch (e) {
    $("mu-hint").textContent = "Não foi possível carregar a lista.";
  }
}

// ============ Passo 2: Município ============
$("btn-municipio").addEventListener("click", () => {
  if (!state.uf) return;
  abrirSheet({
    titulo: `Cidades de ${state.uf}`,
    placeholder: `Buscar cidade em ${state.uf}...`,
    items: state.cidades.map(c => ({ value: c.codigo, label: c.nome, sub: `cód ${c.codigo}` })),
    onPick: (it) => {
      state.municipio = { codigo: String(it.value), nome: it.label };
      state.zona = null;
      state.secao = null;
      state.zonas = [];
      atualizarUI();
      carregarZonasMunicipio();
      $("s3").scrollIntoView({ behavior: "smooth", block: "center" });
    },
  });
});

// ============ Passo 3: Zona + Seção ============
async function carregarZonasMunicipio() {
  state.zonas = [];
  if (!state.uf || !state.municipio?.codigo) return;
  try {
    const r = await fetch(`/api/municipios/${state.municipio.codigo}/zonas?uf=${state.uf}`);
    const d = await r.json();
    state.zonas = d.zonas || [];
  } catch (e) {}
}

$("btn-zona").addEventListener("click", () => {
  if (!state.municipio) return;
  const items = (state.zonas || []).map(z => ({
    value: parseInt(z.codigo),
    label: `Zona ${parseInt(z.codigo)}`,
    sub: `${z.secoes.length} seção(ões)`,
  }));
  if (!items.length) {
    abrirSheet({
      titulo: "Nenhuma zona encontrada",
      items: [],
      onPick: () => {},
    });
    return;
  }
  abrirSheet({
    titulo: `Zonas de ${state.municipio.nome}`,
    placeholder: "Buscar número da zona...",
    items,
    filter: (q, it) => String(it.value).includes(q.replace(/\D/g, "")),
    onPick: (it) => {
      state.zona = String(it.value);
      state.secao = null;
      atualizarUI();
    },
  });
});

$("btn-secao").addEventListener("click", () => {
  if (!state.zona) return;
  const z = state.zonas.find(x => parseInt(x.codigo) === parseInt(state.zona));
  const secoes = z ? z.secoes : [];
  const items = secoes.map(s => ({
    value: parseInt(s),
    label: `Seção ${parseInt(s)}`,
  }));
  if (!items.length) {
    abrirSheet({
      titulo: `Zona ${state.zona}`,
      items: [{ value: 0, label: "Nenhuma seção disponível" }],
      onPick: () => {},
    });
    return;
  }
  abrirSheet({
    titulo: `Seções da zona ${state.zona}`,
    placeholder: "Buscar número da seção...",
    items,
    filter: (q, it) => String(it.value).includes(q.replace(/\D/g, "")),
    onPick: (it) => {
      state.secao = String(it.value);
      atualizarUI();
      $("s4").scrollIntoView({ behavior: "smooth", block: "center" });
    },
  });
});

// ============ Passo 4: Cargo + Turno ============
$("cargo").addEventListener("change", (e) => { state.cargo = e.target.value; atualizarUI(); });
$("turno").addEventListener("change", (e) => { state.turno = e.target.value; atualizarUI(); });

// ============ Submit ============
$("form-urna").addEventListener("submit", async (e) => {
  e.preventDefault();
  const btn = $("btn-buscar");
  const resp = $("resp");
  btn.disabled = true;
  btn.textContent = "Buscando no TSE...";
  resp.classList.remove("visivel");
  try {
    const url = `/api/apuracao/bu?uf=${state.uf}&municipio=${state.municipio.codigo}&zona=${state.zona}&secao=${state.secao}&cargo=${state.cargo}&turno=${state.turno}`;
    const r = await fetch(url);
    const d = await r.json();
    render(d);
    resp.classList.add("visivel");
    resp.scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (err) {
    resp.innerHTML = `<div class="urna-erro"><strong>Erro</strong>${err.message}</div>`;
    resp.classList.add("visivel");
  } finally {
    btn.disabled = false;
    btn.textContent = "Buscar boletim";
  }
});

function render(d) {
  const resp = $("resp");
  if (!d.disponivel) {
    resp.innerHTML = `<div class="urna-resp-head">
      <div>
        <h2>Seção ${d.secao} · Zona ${d.zona}</h2>
        <div class="urna-resp-sub">${state.municipio.nome} — ${d.uf} · ${nomeCargo(d.cargo)}</div>
      </div>
    </div>
    <a class="urna-img-link urna-btn-primario-link" href="${d.url_tse_spa}" target="_blank" rel="noopener">
      Ver boletim da minha seção no TSE →
    </a>`;
    return;
  }
  const t = d.totais || {};
  const stats = [
    ["Eleitorado apto", t.eleitorado_apto],
    ["Comparecimento", t.comparecimento],
    ["Abstenções", t.abstencoes],
    ["Válidos", t.votos_validos],
    ["Brancos", t.votos_brancos],
    ["Nulos", t.votos_nulos],
  ].map(([lab, val]) =>
    `<div class="urna-stat"><div class="urna-stat-lab">${lab}</div><div class="urna-stat-val">${fmt(val || 0)}</div></div>`
  ).join("");
  const cands = (d.candidatos || []).slice(0, 20).map(c =>
    `<div class="urna-cand">
      <span class="urna-cand-sq">${c.sq_candidato}</span>
      <span class="urna-cand-votos">${fmt(c.votos)} · ${c.pct_validos.toFixed(1)}%</span>
    </div>`
  ).join("");
  resp.innerHTML = `
    <div class="urna-resp-head">
      <div>
        <h2>Seção ${d.secao} · Zona ${d.zona}</h2>
        <div class="urna-resp-sub">${state.municipio.nome} — ${d.uf} · ${nomeCargo(d.cargo)}</div>
      </div>
    </div>
    <div class="urna-stats">${stats}</div>
    ${cands ? `<div class="urna-cands"><h3>Votos por candidato</h3>${cands}</div>` : ""}
    ${d.url_tse_spa ? `<a class="urna-img-link urna-btn-primario-link" href="${d.url_tse_spa}" target="_blank" rel="noopener">
      Ver boletim oficial no TSE →
    </a>` : ""}
  `;
}

// ============ Boot ============
renderUFs();
atualizarUI();
