// Wizard de verificação por seção. 4 passos:
//   1. UF (chips) → 2. Município (autocomplete) → 3. Zona/Seção → 4. Cargo/Turno
// A ideia é guiar o usuário em vez de pedir 6 campos de uma vez.

const $ = id => document.getElementById(id);
const fmt = new Intl.NumberFormat("pt-BR").format;

const UFS = ["AC","AL","AP","AM","BA","CE","DF","ES","GO","MA","MT","MS","MG","PA","PB","PR","PE","PI","RJ","RN","RS","RO","RR","SC","SP","SE","TO","ZZ"];

const state = {
  uf: null,
  municipio: null,  // { codigo, nome }
  zona: null,
  secao: null,
  cargo: "1",
  turno: "1",
  cidades: [],  // lista completa da UF selecionada
};

// ============ Steps ============
function marcarStep(n, status /* 'ativa' | 'pronta' | 'inativa' */) {
  const s = $(`s${n}`);
  s.classList.remove("ativa", "pronta");
  if (status === "ativa") s.classList.add("ativa");
  if (status === "pronta") s.classList.add("pronta");
}

function atualizarUI() {
  // Valores resumo nos cabeçalhos
  $("v-uf").textContent = state.uf || "";
  $("v-mu").textContent = state.municipio?.nome || "";
  $("v-zs").textContent = state.zona && state.secao ? `Zona ${state.zona} · Seção ${state.secao}` : "";
  $("v-ct").textContent = `${nomeCargo(state.cargo)} · ${state.turno}º turno`;

  // Qual é o próximo step a abrir
  if (!state.uf) {
    [1,2,3,4].forEach(n => marcarStep(n, n === 1 ? "ativa" : "inativa"));
  } else if (!state.municipio) {
    marcarStep(1, "pronta"); marcarStep(2, "ativa"); marcarStep(3, "inativa"); marcarStep(4, "inativa");
  } else if (!state.zona || !state.secao) {
    marcarStep(1, "pronta"); marcarStep(2, "pronta"); marcarStep(3, "ativa"); marcarStep(4, "inativa");
  } else {
    marcarStep(1, "pronta"); marcarStep(2, "pronta"); marcarStep(3, "pronta"); marcarStep(4, "ativa");
  }
  $("btn-buscar").disabled = !(state.uf && state.municipio && state.zona && state.secao);
}

function nomeCargo(c) {
  return {1:"Presidente",3:"Governador",5:"Senador",6:"Dep. Federal",7:"Dep. Estadual"}[c] || "?";
}

// ============ Passo 1: UFs como chips ============
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
  state.cidades = [];
  $("municipio").value = "";
  renderUFs();
  atualizarUI();
  // Scroll suave pro próximo step
  $("s2").scrollIntoView({ behavior: "smooth", block: "center" });
  // Carrega lista de municípios da UF
  if (uf === "ZZ") {
    // Exterior: TSE agrupa por zona consular, não há município — campo
    // vira input manual simples.
    $("mu-hint").textContent = "Para o exterior, informe o nome do consulado onde votou.";
    return;
  }
  $("mu-hint").textContent = "Carregando municípios...";
  try {
    const r = await fetch(`/api/municipios?uf=${uf}`);
    const j = await r.json();
    state.cidades = j.municipios || [];
    const dl = $("mu-opts");
    dl.innerHTML = "";
    state.cidades.forEach(c => {
      const opt = document.createElement("option");
      opt.value = c.nome;
      opt.dataset.codigo = c.codigo;
      dl.appendChild(opt);
    });
    if (state.cidades.length) {
      $("mu-hint").textContent = `${state.cidades.length} municípios disponíveis em ${uf}. Comece a digitar.`;
    } else {
      // Mensagem rica quando TSE ainda não publicou (comum pré-apuração)
      const erro = j.erro || "TSE ainda não publicou a lista.";
      $("mu-hint").innerHTML = erro.replace(
        /tse\.jus\.br\/eleitor\/onde-votar/,
        '<a href="https://www.tse.jus.br/eleitor/onde-votar" target="_blank" rel="noopener">tse.jus.br/eleitor/onde-votar</a>'
      );
    }
  } catch (e) {
    $("mu-hint").textContent = "Não foi possível carregar a lista. Digite o código TSE manualmente.";
  }
}

// ============ Passo 2: município com datalist ============
$("municipio").addEventListener("input", (e) => {
  const texto = e.target.value.trim();
  // Procura pelo nome exato na lista
  const bate = state.cidades.find(c =>
    c.nome.toLocaleLowerCase("pt-BR") === texto.toLocaleLowerCase("pt-BR"));
  if (bate) {
    state.municipio = bate;
  } else if (/^\d+$/.test(texto)) {
    // Usuário digitou código TSE direto (fallback)
    state.municipio = { codigo: texto, nome: `Código ${texto}` };
  } else {
    state.municipio = null;
  }
  atualizarUI();
});

$("municipio").addEventListener("change", () => {
  if (state.municipio) {
    carregarZonasMunicipio();
    $("s3").scrollIntoView({ behavior: "smooth", block: "center" });
  }
});

// ============ Passo 3: zona + seção ============
["zona", "secao"].forEach(id => {
  $(id).addEventListener("input", (e) => {
    const v = e.target.value.replace(/\D/g, "");
    e.target.value = v;
    state[id] = v || null;
    atualizarUI();
    if (id === "zona" && v) carregarSecoesDaZona(v);
  });
});

// Quando usuário escolhe município, baixa zonas pra autocompletar
let _zonas = [];  // [{codigo, secoes: [...]}]
async function carregarZonasMunicipio() {
  _zonas = [];
  if (!state.uf || !state.municipio?.codigo) return;
  try {
    const r = await fetch(`/api/municipios/${state.municipio.codigo}/zonas?uf=${state.uf}`);
    const d = await r.json();
    _zonas = d.zonas || [];
    // Popula datalist de zonas se há mais de 1
    const dl = document.getElementById("zona-opts") || (() => {
      const d = document.createElement("datalist");
      d.id = "zona-opts";
      document.body.appendChild(d);
      $("zona").setAttribute("list", "zona-opts");
      return d;
    })();
    dl.innerHTML = "";
    _zonas.forEach(z => {
      const opt = document.createElement("option");
      opt.value = String(parseInt(z.codigo));
      opt.label = `${z.secoes.length} seções`;
      dl.appendChild(opt);
    });
  } catch (e) {}
}

function carregarSecoesDaZona(zona) {
  const z = _zonas.find(x => parseInt(x.codigo) === parseInt(zona));
  if (!z) return;
  const dl = document.getElementById("secao-opts") || (() => {
    const d = document.createElement("datalist");
    d.id = "secao-opts";
    document.body.appendChild(d);
    $("secao").setAttribute("list", "secao-opts");
    return d;
  })();
  dl.innerHTML = "";
  z.secoes.forEach(s => {
    const opt = document.createElement("option");
    opt.value = String(parseInt(s));
    dl.appendChild(opt);
  });
}

// ============ Passo 4: cargo + turno ============
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
    resp.innerHTML = `<div class="urna-erro">
      <strong>Não encontrado</strong>
      ${d.motivo || "A seção pode não ter sido totalizada ainda, ou os códigos estão incorretos."}
      ${d.url_imagem_bu ? `<br><br><a class="urna-img-link" href="${d.url_imagem_bu}" target="_blank" rel="noopener">Tentar a imagem direto no TSE →</a>` : ""}
    </div>`;
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
    <a class="urna-img-link" href="${d.url_imagem_bu}" target="_blank" rel="noopener">
      Ver a imagem assinada do BU original (JPEG do TSE) →
    </a>
  `;
}

// ============ Boot ============
renderUFs();
atualizarUI();
