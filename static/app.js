import { renderMapa } from "/static/mapa-br.js";
import { corDoPartido, siglaDoPartido, badgePartidoHtml } from "/static/partidos.js";

const PALETA = ["#f0b429", "#3b82f6", "#ec4899", "#10b981", "#a855f7", "#f97316"];
const TZ = "America/Sao_Paulo";
const MAX_SEL = 4;
// Início oficial da apuração 2026: domingo, 4/10/2026 às 17h de Brasília.
// Eleições Gerais 2026 — primeiro domingo de outubro, art. 1º da Lei 9.504/97.
// 17h BRT = fechamento das urnas e início da apuração.
const DIA_D = new Date("2026-10-04T17:00:00-03:00");
const TITULO_BASE = "Apuração 2026 · Brasil";

const state = {
  cargo: 1,
  abrangencia: "BR",
  candidatos: [],
  ficha: {},
  selecionados: [],
  ultimoSnapshot: null,
  snapshotAnterior: null,   // pra calcular delta/tendência
  graficos: {},
  ws: null,
  filtro: { texto: "", partido: "", ordenar: "votos" },
  proporcional: null,
  // Candidatos matematicamente eliminados — sem chance aritmética de
  // vencer/ir ao 2º turno mesmo somando todos os votos restantes. Poputa
  // via /api/eventos + eventos que chegam pelo WS.
  eliminados: new Set(),
  // Candidatos eleitos matematicamente (majoritário ou proporcional).
  eleitos: new Set(),
};

// ============ persistência de preferências ============
// Salva cargo/UF/filtros no localStorage pro usuário reencontrar
// tudo do jeito que deixou na última visita. Falha silenciosamente
// (modo anônimo, storage cheio, etc).
const PREFS_KEY = "elei-es:prefs:v1";
function salvarPrefs() {
  try {
    localStorage.setItem(PREFS_KEY, JSON.stringify({
      cargo: state.cargo,
      abrangencia: state.abrangencia,
      filtro: state.filtro,
    }));
  } catch(e) {}
}
function carregarPrefs() {
  try {
    const raw = localStorage.getItem(PREFS_KEY);
    if (!raw) return;
    const p = JSON.parse(raw);
    if (typeof p.cargo === "number") state.cargo = p.cargo;
    if (typeof p.abrangencia === "string") state.abrangencia = p.abrangencia;
    if (p.filtro && typeof p.filtro === "object") state.filtro = {
      texto: p.filtro.texto || "",
      partido: p.filtro.partido || "",
      ordenar: p.filtro.ordenar || "votos",
    };
  } catch(e) {}
}

// ============ Motion helpers (performance-safe) ============
// Só usa transform/opacity, honra prefers-reduced-motion, aplica
// will-change só durante o movimento.

const REDUCED_MOTION = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

/**
 * Ripple visual no ponto de clique. Container precisa ter
 * `class="ripple-container"` (position:relative + overflow:hidden).
 */
function addRipple(el) {
  if (!el || el.__hasRipple) return;
  el.__hasRipple = true;
  el.classList.add("ripple-container");
  // pointerdown cobre mouse, touch e pen (Material spec)
  el.addEventListener("pointerdown", (ev) => {
    if (REDUCED_MOTION) return;
    // Se clicar em elemento filho interativo (não é o botão em si),
    // ainda mostra o ripple no ponto do clique
    const r = el.getBoundingClientRect();
    const size = Math.max(r.width, r.height) * 1.2;
    const x = (ev.clientX ?? r.left + r.width/2) - r.left - size / 2;
    const y = (ev.clientY ?? r.top + r.height/2) - r.top - size / 2;
    const span = document.createElement("span");
    span.className = "ripple";
    span.style.width = span.style.height = size + "px";
    span.style.left = x + "px"; span.style.top = y + "px";
    el.appendChild(span);
    setTimeout(() => span.remove(), 560);
  });
}

/**
 * Staggered entry: aplica classe .anim-in-up com delay incremental.
 * IntersectionObserver evita animar quando o card não está visível.
 */
function anexarEntradaCascata(elementos, base = 30, max = 350) {
  if (REDUCED_MOTION) return;
  elementos.forEach((el, i) => {
    el.style.animationDelay = Math.min(i * base, max) + "ms";
    el.classList.add("anim-in-up");
  });
}

/**
 * FLIP animation pra reordenação da lista de candidatos.
 * 1) Antes: mede posições atuais (positions Map).
 * 2) DOM: JS reordena os elementos.
 * 3) Depois: mede novas posições, calcula delta, aplica transform
 *    inicial invertido, deixa CSS transition levar de volta a zero.
 */
function flipReorder(container, itemsSelector = ".candidato") {
  if (REDUCED_MOTION) return { commit: () => {} };
  const items = Array.from(container.querySelectorAll(itemsSelector));
  const before = new Map();
  items.forEach(el => {
    const sq = el.dataset.sqCard;
    if (sq) before.set(sq, el.getBoundingClientRect());
  });
  return {
    commit() {
      const novos = Array.from(container.querySelectorAll(itemsSelector));
      novos.forEach(el => {
        const sq = el.dataset.sqCard;
        if (!sq || !before.has(sq)) return;
        const antes = before.get(sq);
        const agora = el.getBoundingClientRect();
        const dx = antes.left - agora.left;
        const dy = antes.top - agora.top;
        if (Math.abs(dx) < 2 && Math.abs(dy) < 2) return;
        el.classList.add("moving");
        el.style.transform = `translate3d(${dx}px, ${dy}px, 0)`;
        el.style.transition = "transform 0s";
        // Force reflow, then unset — CSS transition assume
        void el.offsetWidth;
        el.style.transition = "";
        el.style.transform = "";
        setTimeout(() => { el.classList.remove("moving"); el.style.willChange = ""; }, 550);
      });
    }
  };
}

// ============ helpers ============
const fmt = new Intl.NumberFormat("pt-BR");
const fmtNum = n => fmt.format(n ?? 0);
const fmtHora = iso => new Date(iso).toLocaleTimeString("pt-BR", { timeZone: TZ });
const $ = id => document.getElementById(id);

// Anima transição entre valores numéricos (efeito ao vivo)
function animarNumero(el, novoValor, duracao = 500) {
  if (!el) return;
  const anterior = parseInt((el.dataset.valor || el.textContent).replace(/\D/g, ""), 10) || 0;
  if (anterior === novoValor) { el.textContent = fmtNum(novoValor); return; }
  el.dataset.valor = novoValor;
  // Flash: destaque visual sutil pra sinalizar mudança
  if (anterior > 0) {
    el.classList.remove("flash");
    void el.offsetWidth;      // força reflow pra permitir re-animar
    el.classList.add("flash");
    setTimeout(() => el.classList.remove("flash"), 900);
  }
  const inicio = performance.now();
  function tick(t) {
    const p = Math.min(1, (t - inicio) / duracao);
    const eased = 1 - Math.pow(1 - p, 3);
    const atual = Math.round(anterior + (novoValor - anterior) * eased);
    el.textContent = fmtNum(atual);
    if (p < 1) requestAnimationFrame(tick);
    else el.textContent = fmtNum(novoValor);
  }
  requestAnimationFrame(tick);
}

async function get(url, opts = {}) {
  const tentativas = opts.retries ?? 2;
  let ultimoErro;
  for (let i = 0; i <= tentativas; i++) {
    try {
      const r = await fetch(url);
      if (!r.ok) throw new Error(`${r.status} ${await r.text().catch(() => "")}`);
      return await r.json();
    } catch (e) {
      ultimoErro = e;
      if (i < tentativas) await new Promise(res => setTimeout(res, 400 * (i + 1)));
    }
  }
  throw ultimoErro;
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
  // Exterior ("ZZ") só vota em Presidente (CF art. 14 §1º + LC 44/82).
  // A opção é adicionada em preencherUFs() uma vez e aqui só escondemos
  // (hidden + disabled) quando cargo != 1 — mais robusto contra timing
  // issues que add/remove dinâmico.
  const optZZ = Array.from(selUF.options).find(o => o.value === "ZZ");
  if (state.cargo === 1) {
    if (optZZ) { optZZ.hidden = false; optZZ.disabled = false; }
    if (!state.abrangencia) { state.abrangencia = "BR"; selUF.value = "BR"; }
  } else {
    if (optZZ) { optZZ.hidden = true; optZZ.disabled = true; }
    if (state.abrangencia === "BR" || state.abrangencia === "ZZ") {
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
  // Skeleton bate 1:1 com o layout do card real: topo com foto+info+check,
  // métricas, rodapé com 2 botões. Assim a transição pro estado carregado
  // é suave (sem "salto" de layout).
  for (let i = 0; i < n; i++) {
    const div = document.createElement("div");
    div.className = "candidato loading";
    div.innerHTML = `
      <div class="cand-topo">
        <div class="cand-foto skel"></div>
        <div class="cand-info">
          <div class="cand-nome skel"></div>
          <div class="cand-meta skel"></div>
        </div>
        <div class="cand-check-vazio skel"></div>
      </div>
      <div class="cand-metricas">
        <div class="cand-votos skel"></div>
        <div class="cand-linha-inf"><span class="skel-inline"></span></div>
        <div class="cand-barra skel"></div>
      </div>
      <div class="cand-rodape">
        <div class="cand-acao skel"></div>
        <div class="cand-acao skel"></div>
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
      <svg class="empty-ico" width="48" height="48"><use href="#i-clock"/></svg>
      <h3>Aguardando o TSE liberar os dados</h3>
      <p>Os primeiros resultados começam a sair a partir das 17h de domingo, quando as urnas fecham. O placar preenche sozinho assim que os primeiros votos chegarem.</p>
    </div>`;
    return;
  }
  if (filtrados.length === 0) {
    el.innerHTML = `<div class="empty-state">
      <h3>Nada com esse filtro</h3>
      <p>Tente escrever outra parte do nome, mudar o partido ou limpar a busca.</p>
    </div>`;
    return;
  }
  // FLIP: mede posições antes de re-renderizar pra animar reordenação
  const flip = flipReorder(el);

  const primeiraVez = !el.dataset.jaRenderizou;
  for (const c of filtrados) {
    const sel = state.selecionados.indexOf(c.sq_candidato);
    const div = document.createElement("div");
    const eliminado = state.eliminados.has(c.sq_candidato);
    const eleito = state.eleitos.has(c.sq_candidato);
    // Situação jurídica — se o candidato renunciou/foi cassado, votos
    // são nulos por lei (Lei 9.504/97 art. 175 §3º). Prioridade visual
    // acima de eleito/eliminado matemático.
    const ficha = state.ficha[c.sq_candidato];
    const retirado = ficha?.situacao && ficha.situacao !== "ativo";
    div.className = "candidato"
      + (sel >= 0 ? " selecionado" : "")
      + (retirado ? " retirado" : "")
      + (eliminado ? " eliminado" : "")
      + (eleito ? " eleito" : "");
    div.dataset.sqCard = c.sq_candidato;
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
    // Tarja de status matemático (eleito/eliminado). Cargo majoritário
    // (presidente/governador): "Sem chance de ir ao 2º turno" pega bem.
    // Proporcional (senador/dep): "Sem chance de eleição" é claro sem
    // ser cruel. O aviso é sobrio — dignidade importa em resultado
    // eleitoral, mesmo pra quem perdeu.
    const cargoMaj = [1, 3].includes(state.cargo);
    let tarja = "";
    if (retirado) {
      // Prioridade máxima: candidato não concorre mais. Lei 9.504 §3º.
      const motivo = {
        renunciou: "Candidatura retirada",
        cancelado: "Registro cancelado",
        cassado: "Candidatura cassada",
        indeferido_sem_recurso: "Registro indeferido",
      }[ficha.situacao] || "Fora da disputa";
      tarja = `<div class="cand-tarja tarja-retirado">
        <svg width="14" height="14" aria-hidden="true"><use href="#i-x"/></svg>
        <span>${motivo} — votos nulos por lei</span>
      </div>`;
    } else if (eleito) {
      tarja = `<div class="cand-tarja tarja-eleito">
        <svg width="14" height="14" aria-hidden="true"><use href="#i-trophy"/></svg>
        <span>Eleito(a) matematicamente</span>
      </div>`;
    } else if (eliminado) {
      const frase = cargoMaj
        ? "Sem chance matemática de ir ao 2º turno"
        : "Sem chance matemática de eleição";
      tarja = `<div class="cand-tarja tarja-eliminado">
        <svg width="14" height="14" aria-hidden="true"><use href="#i-x"/></svg>
        <span>${frase}</span>
      </div>`;
    }
    // Layout redesenhado: header (foto + nome/partido) → métricas
    // (votos + %/delta + barra) → footer (botão "ver ficha" integrado).
    // Zero position:absolute nos elementos principais.
    div.innerHTML = `
      <div class="cand-topo">
        <img class="cand-foto" src="${c.foto}" alt="" loading="lazy" decoding="async">
        <div class="cand-info">
          <div class="cand-nome">${c.nome_urna}</div>
          <div class="cand-meta">
            <span class="cand-numero-tag">${c.numero}</span>
            ${pillPart}
            ${c.uf ? `<span class="cand-uf-tag">${c.uf}</span>` : ""}
          </div>
          ${badgeProp}
        </div>
        <div class="cand-check-vazio" aria-hidden="true"></div>
      </div>
      <div class="cand-metricas">
        <div class="cand-votos" data-sq="${c.sq_candidato}">—</div>
        <div class="cand-linha-inf">
          <span class="cand-pct" data-sq-pct="${c.sq_candidato}"></span>
          <span class="cand-delta" data-sq-delta="${c.sq_candidato}"></span>
        </div>
        <div class="cand-barra"><div data-sq-barra="${c.sq_candidato}" style="width:0%"></div></div>
      </div>
      ${tarja}
      <div class="cand-rodape">
        <button class="cand-acao cand-comparar" data-comparar="${c.sq_candidato}" aria-label="Selecionar para comparar">
          ${sel >= 0 ? '<svg width="14" height="14"><use href="#i-x"/></svg> remover' : '＋ comparar'}
        </button>
        <button class="cand-acao cand-ver" data-detalhes="${c.sq_candidato}" aria-label="Ver ficha completa">
          ver ficha →
        </button>
      </div>`;
    anexarFotoComRetry(div.querySelector("img.cand-foto"), c.nome_urna, c.partido);
    // Ação primária do card = ver ficha (mais discoverable).
    // Botões explícitos no rodapé pra ambas ações — sem ambiguidade.
    div.addEventListener("click", (e) => {
      if (e.target.closest("[data-comparar]") || e.target.closest("[data-detalhes]"))
        return;
      abrirModal(c.sq_candidato);
    });
    el.appendChild(div);
  }
  el.querySelectorAll("[data-detalhes]").forEach(b => {
    b.addEventListener("click", (e) => {
      e.stopPropagation();
      abrirModal(b.dataset.detalhes);
    });
  });
  el.querySelectorAll("[data-comparar]").forEach(b => {
    b.addEventListener("click", (e) => {
      e.stopPropagation();
      toggleSelecionar(b.dataset.comparar);
    });
  });
  // Motion: cada renderização (primeira ou por troca de filtro) entra
  // em cascata; se for atualização de mesmo conjunto (rank mudou), FLIP.
  const cards = el.querySelectorAll(".candidato");
  // Detecta se o conjunto de SQs mudou desde a última renderização —
  // se sim, é uma nova lista e vale a cascata; senão, só FLIP.
  const sqsNovos = Array.from(cards).map(c => c.dataset.sqCard).sort().join(",");
  const sqsAntes = el.dataset.sqsRenderizados || "";
  const conjuntoMudou = sqsNovos !== sqsAntes;
  if (primeiraVez || conjuntoMudou) {
    anexarEntradaCascata(cards);
    el.dataset.jaRenderizou = "1";
    el.dataset.sqsRenderizados = sqsNovos;
  } else {
    flip.commit();
  }
  // Ripple em ambos os botões do rodapé (funciona em mouse + touch)
  el.querySelectorAll(".cand-acao").forEach(addRipple);
  // Card inteiro também tem ripple (ação primária = ver ficha)
  cards.forEach(addRipple);
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
  atualizarFabMobile();
}

// ============ modal de detalhes ============
async function abrirModal(sq) {
  try {
    const c = await get(`/api/candidato/${sq}`);
    const votos = state.ultimoSnapshot?.candidatos?.find(x => x.sq_candidato === sq);
    const corP = corPartido(c.partido);
    const opcional = (v) => v || "—";
    const dataNasc = c.data_nascimento
      ? c.data_nascimento.split("T")[0].split("-").reverse().join("/")
      : null;
    const fields = [
      ["Votos",           votos ? fmtNum(votos.votos) : "—", "num"],
      ["% Válidos",       votos ? votos.pct_validos.toFixed(2) + "%" : "—", "num"],
      ["Posição",         votos ? votos.posicao + "º" : "—", "num"],
      ["Situação",        opcional({
                            ativo: "Ativo",
                            renunciou: "Renunciou",
                            cancelado: "Registro cancelado",
                            cassado: "Cassado",
                            indeferido_sem_recurso: "Inapto / indeferido",
                          }[c.situacao] || c.situacao_tse || c.situacao)],
      ["Coligação",       opcional(c.coligacao), "wide"],
      ["Partido",         c.partido_nome ? `${c.partido_nome} (${c.partido})` : `${c.partido}`, "wide"],
      ["Data de nasc.",   opcional(dataNasc)],
      ["Sexo",            opcional(c.sexo)],
      ["Cor/Raça",        opcional(c.cor_raca)],
      ["Estado civil",    opcional(c.estado_civil)],
      ["Grau de instr.",  opcional(c.grau_instrucao), "wide"],
      ["Ocupação",        opcional(c.ocupacao), "wide"],
      ["Naturalidade",    (c.municipio_nascimento && c.uf_nascimento)
                          ? `${c.municipio_nascimento}/${c.uf_nascimento}` : "—", "wide"],
      ["Vice",            c.vice_nome
                          ? `${c.vice_nome}${c.vice_partido_sigla ? " (" + c.vice_partido_sigla + ")" : ""}`
                          : null, "wide"],
      ["Gasto de camp.",  c.gasto_campanha ? `R$ ${fmtNum(c.gasto_campanha)}` : null],
      ["CNPJ da camp.",   c.cnpj_campanha, "wide"],
    ].filter(([_, v]) => v !== null);

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
        ${fields.map(([k, v, cls]) =>
          `<div class="modal-field ${cls || ""}"><div class="k">${k}</div><div class="v">${v}</div></div>`
        ).join("")}
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
    animarNumero($("dif-abs"), dif);
    $("dif-pct").textContent = (ordenados[0].pct_validos - ordenados[1].pct_validos).toFixed(2) + " pp";
    // Margem de segurança = quanto o líder pode perder e ainda vencer
    const restantes = Math.max(0, (dados.totais.eleitorado_apto || 0) - (dados.totais.eleitorado_apto_totalizadas || 0));
    const margem = ordenados[0].votos > 0
      ? Math.max(-100, Math.min(100, (ordenados[0].votos - (ordenados[1].votos + restantes)) / ordenados[0].votos * 100))
      : 0;
    const pctApurado = dados.totais.pct_apurado || 0;
    if (pctApurado < 20) {
      $("dif-prob").textContent = "EM DISPUTA";
      $("dif-prob-hint").textContent = `Motor matemático silenciado (< 20% apurado)`;
    } else if (margem <= 0) {
      $("dif-prob").textContent = "NO FIO";
      $("dif-prob-hint").textContent = `Diferença menor que os votos que faltam`;
    } else if (margem > 50) {
      $("dif-prob").textContent = "DEFINIDO";
      $("dif-prob-hint").textContent = `Líder folgado — margem ${margem.toFixed(1)}%`;
    } else {
      $("dif-prob").textContent = `~${margem.toFixed(0)}%`;
      $("dif-prob-hint").textContent = `Margem de segurança sobre 2º`;
    }
  }
}

// ============ gráficos ============
// Formatador do tooltip: mostra data + horário BRT do snapshot com
// as séries de cada candidato ao passar o mouse sobre a linha.
function tooltipHoraBRT(params) {
  if (!Array.isArray(params) || !params.length) return "";
  // Todos os params têm o mesmo x (timestamp). Pega do primeiro.
  const ts = params[0].axisValue ?? params[0].value?.[0];
  const d = new Date(ts);
  const hora = d.toLocaleString("pt-BR", {
    timeZone: TZ, day: "2-digit", month: "2-digit",
    hour: "2-digit", minute: "2-digit", second: "2-digit"
  });
  const linhas = [`<div style="color:#94a1b8;font-size:11px;margin-bottom:4px">${hora} BRT</div>`];
  for (const p of params) {
    const v = Array.isArray(p.value) ? p.value[1] : p.value;
    const num = typeof v === "number" ? fmtNum(Math.round(v)) : v;
    linhas.push(
      `<div style="display:flex;justify-content:space-between;gap:12px">
        <span>${p.marker} ${p.seriesName}</span>
        <b style="font-variant-numeric:tabular-nums">${num}</b>
      </div>`
    );
  }
  return linhas.join("");
}

function baseOpts(title) {
  return {
    backgroundColor: "transparent",
    tooltip: {
      trigger: "axis",
      backgroundColor: "#161b24",
      borderColor: "#303a4d",
      textStyle: { color: "#ecf0f7", fontSize: 12 },
      formatter: tooltipHoraBRT,
      axisPointer: { type: "cross", label: { backgroundColor: "#1e2531" } },
    },
    legend: { textStyle: { color: "#b6c0d4" }, top: 0, right: 10, icon: "roundRect" },
    grid: { left: 60, right: 20, top: 30, bottom: 30 },
    xAxis: {
      type: "time",
      axisLine: { lineStyle: { color: "#303a4d" } },
      axisLabel: {
        color: "#7d8899",
        // Rótulos do eixo X em BRT (HH:mm quando cabe, dd/mm HH:mm no zoom)
        formatter: (val) => {
          const d = new Date(val);
          return d.toLocaleTimeString("pt-BR", { timeZone: TZ, hour: "2-digit", minute: "2-digit" });
        },
      },
    },
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
    // Limpa TODOS os campos — bug antigo só limpava metade e os subs
    // (secoes-sub, pct-comparecimento, etc.) ficavam com dados do
    // cargo anterior ("de 52.000 seções" mesmo depois de trocar
    // pra um cargo sem dados).
    $("pct-apurado").textContent = "—";
    $("pct-apurado").classList.remove("pulse-live");
    const prog = $("prog-apurado");
    prog.style.width = "0%";
    prog.classList.remove("rodando");
    $("secoes").textContent = "—";
    // Zera o dataset.valor pro animarNumero começar do 0 quando voltar
    $("secoes").dataset.valor = "0";
    $("secoes-sub").textContent = "aguardando dados do TSE";
    $("comparecimento").textContent = "—";
    $("comparecimento").dataset.valor = "0";
    $("pct-comparecimento").textContent = "";
    $("abstencoes").textContent = "—";
    $("abstencoes").dataset.valor = "0";
    $("pct-abstencoes").textContent = "";
    $("brancos-nulos").textContent = "—";
    $("ultimo").textContent = "—";
    delete $("ultimo").dataset.iso;
    return;
  }
  const t = dados.totais;
  $("pct-apurado").textContent = t.pct_apurado.toFixed(2) + "%";
  const prog = $("prog-apurado");
  prog.style.width = t.pct_apurado + "%";
  // Shimmer só enquanto a apuração está viva (entre 0 e 100%)
  prog.classList.toggle("rodando", t.pct_apurado > 0 && t.pct_apurado < 100);
  // Big number pulsa suavemente durante a apuração ao vivo
  $("pct-apurado").classList.toggle("pulse-live", t.pct_apurado > 0 && t.pct_apurado < 100);
  animarNumero($("secoes"), t.secoes_totalizadas);
  $("secoes-sub").textContent = `de ${fmtNum(t.secoes_total)}`;
  animarNumero($("comparecimento"), t.comparecimento);
  animarNumero($("abstencoes"), t.abstencoes);
  const totalAptos = t.eleitorado_apto || 1;
  const pctCompar = (t.comparecimento / totalAptos * 100).toFixed(1);
  const pctAbst = (t.abstencoes / totalAptos * 100).toFixed(1);
  $("pct-comparecimento").textContent = `${pctCompar}% dos aptos`;
  $("pct-abstencoes").textContent = `${pctAbst}% dos aptos`;
  $("brancos-nulos").textContent = `${fmtNum(t.votos_brancos)} · ${fmtNum(t.votos_nulos)}`;
  // "Último dado" mostra a hora em que o TSE GEROU o arquivo (fonte da
  // verdade pro cross-check), caindo pra "coletado_em" (quando a gente
  // baixou) quando o TSE não envia gerado_em_tse. Tooltip explica
  // divergência entre níveis (BR × UF × município têm timestamps
  // distintos — é operação normal do TSE).
  const ts = dados.gerado_em_tse || dados.coletado_em;
  const el = $("ultimo");
  el.textContent = fmtHora(ts);
  el.dataset.iso = ts;
  el.title = dados.gerado_em_tse
    ? `Gerado pelo TSE às ${fmtHora(dados.gerado_em_tse)} · Coletado por nós às ${fmtHora(dados.coletado_em)}`
    : `Coletado às ${fmtHora(dados.coletado_em)} (TSE não informou hora de geração)`;

  // atualiza cards da lista
  const maxV = Math.max(1, ...dados.candidatos.map(c => c.votos));
  // Mapa do snapshot anterior pra calcular delta
  const antMap = new Map((state.snapshotAnterior?.candidatos || [])
    .map(c => [c.sq_candidato, c]));
  dados.candidatos.forEach(c => {
    const votos = document.querySelector(`[data-sq="${c.sq_candidato}"]`);
    const pct = document.querySelector(`[data-sq-pct="${c.sq_candidato}"]`);
    const barra = document.querySelector(`[data-sq-barra="${c.sq_candidato}"]`);
    const delta = document.querySelector(`[data-sq-delta="${c.sq_candidato}"]`);
    if (votos) animarNumero(votos, c.votos, 400);
    if (pct) {
      const proj = c.projecao_linear;
      const pctApur = dados.totais?.pct_apurado || 0;
      // Só mostra projeção depois de 30% apurado (antes é ruído)
      const projTxt = (proj && pctApur >= 30)
        ? ` · proj. ${fmtNum(proj)}`
        : "";
      pct.textContent = c.pct_validos.toFixed(2) + "% dos válidos" + projTxt;
    }
    if (barra) barra.style.width = (c.votos / maxV * 100) + "%";
    if (delta) {
      const ant = antMap.get(c.sq_candidato);
      if (ant && ant.votos !== c.votos) {
        const diff = c.votos - ant.votos;
        const cls = diff > 0 ? "up" : "down";
        const sym = diff > 0 ? "▲" : "▼";
        delta.className = `cand-delta ${cls}`;
        delta.textContent = `${sym} ${fmtNum(Math.abs(diff))}`;
      } else {
        delta.textContent = "";
        delta.className = "cand-delta";
      }
    }
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
// Ícones referenciam o sprite SVG em index.html (#i-trophy, #i-bolt, etc).
// Nada de emoji — cor + tipografia carregam a hierarquia.
const TIPOS_EVENTO = {
  ELEITO_1T:                 { label: "Eleito 1T", classe: "ok",     ico: "trophy" },
  ELEITO_MAJORITARIO:        { label: "Eleito",    classe: "ok",     ico: "trophy" },
  SEGUNDO_TURNO_DEFINIDO:    { label: "2º Turno",  classe: "warn",   ico: "bolt" },
  VIRADA:                    { label: "Virada",    classe: "warn",   ico: "arrow-up" },
  MATEMATICAMENTE_ELIMINADO: { label: "Eliminado", classe: "danger", ico: "x" },
};

function _absorverEventoNoState(ev) {
  // Popula state.eliminados / state.eleitos a partir de um evento.
  // Chamado no carregamento inicial e em cada evento novo via WS —
  // fonte única de verdade pro visual dos cards.
  if (ev.tipo === "MATEMATICAMENTE_ELIMINADO" && ev.sq_candidato_a) {
    state.eliminados.add(ev.sq_candidato_a);
  } else if ((ev.tipo === "ELEITO_1T" || ev.tipo === "ELEITO_MAJORITARIO")
             && ev.sq_candidato_a) {
    state.eleitos.add(ev.sq_candidato_a);
  }
}

async function carregarEventos() {
  let evs = [];
  try { evs = await get(`/api/eventos?cargo=${state.cargo}&abrangencia=${state.abrangencia}`); } catch (e) {}
  // Reseta os sets — cargo/UF podem ter mudado e temos que zerar
  state.eliminados.clear();
  state.eleitos.clear();
  evs.forEach(_absorverEventoNoState);
  const ul = $("lista-eventos");
  if (evs.length === 0) {
    ul.innerHTML = `<li class="vazio">Nenhum evento ainda. Aguardando apuração começar.</li>`;
    return;
  }
  ul.innerHTML = "";
  for (const ev of evs.slice().reverse()) {
    const nome = state.ficha[ev.sq_candidato_a]?.nome_urna || ev.sq_candidato_a;
    const meta = TIPOS_EVENTO[ev.tipo] || { label: ev.tipo, classe: "", ico: null };
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
      <span class="ev-tipo ${meta.classe}">${meta.ico ? `<svg width="12" height="12" aria-hidden="true"><use href="#i-${meta.ico}"/></svg>` : ""} ${meta.label}</span>
      <span class="ev-texto">${texto}</span>`;
    ul.appendChild(li);
  }
}

// ============ ciclo ============
async function refreshApuracao() {
  try {
    const novo = await get(`/api/apuracao/atual?cargo=${state.cargo}&abrangencia=${state.abrangencia}`);
    // Guarda snapshot anterior pra calcular tendência (só se realmente mudou)
    if (state.ultimoSnapshot?.disponivel &&
        state.ultimoSnapshot.coletado_em !== novo.coletado_em) {
      state.snapshotAnterior = state.ultimoSnapshot;
    }
    state.ultimoSnapshot = novo;
    // PROTEÇÃO CONTRA MISMATCH: se o backend reporta sq_candidato
    // órfão (TSE devolveu alguém que nossa /api/candidatos não tem,
    // ex.: candidato acabou de ser importado via Termux), refetcha a
    // ficha pra evitar mostrar 'sq_candidato: 2800...' como nome.
    // Também loga pra diagnóstico.
    if (novo?.disponivel && novo.orfaos?.length) {
      console.warn("snapshot tem sq_candidato órfão(s):", novo.orfaos,
                   "— refetchando /api/candidatos");
      try {
        await carregarCandidatos();
      } catch (e) { /* se falhar, seguimos com a ficha que tem */ }
    }
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
  atualizarTituloAba(state.ultimoSnapshot);
  // Countdown só aparece enquanto TSE não publica dados de verdade
  if (!state.ultimoSnapshot?.disponivel) atualizarContagemRegressiva();
  else { const c = $("countdown"); if (c) c.classList.add("oculto"); }
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
  if (state.ws) {
    // Marca como "fechado intencional" pro handler onclose ignorar e
    // NÃO agendar reconnect. Senão fica agendando reconexão do WS
    // antigo enquanto o novo já está sendo criado — cria duas cadeias
    // paralelas e o backoff (wsRetry) acumula.
    state.ws.__intencional = true;
    try { state.ws.close(); } catch(e){}
  }
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  const ws = new WebSocket(`${proto}//${location.host}/ws/apuracao?cargo=${state.cargo}&abrangencia=${state.abrangencia}`);
  ws.onopen = () => {
    $("conexao").querySelector(".dot").classList.add("on");
    $("conexao-label").textContent = "ao vivo";
    state.wsRetry = 0;
    // Puxa snapshot fresco assim que reconecta (evita "buraco" de eventos)
    refreshApuracao().catch(() => {});
  };
  const reconectar = () => {
    // Se o WS foi fechado intencionalmente (troca de cargo/UF),
    // NÃO reconecta — outro conectarWS já está em andamento.
    if (ws.__intencional) return;
    $("conexao").querySelector(".dot").classList.remove("on");
    $("conexao-label").textContent = "reconectando…";
    // Backoff exponencial com jitter: 1s, 2s, 4s, 8s, 15s teto
    state.wsRetry = (state.wsRetry || 0) + 1;
    const base = Math.min(15000, 1000 * Math.pow(2, state.wsRetry - 1));
    const jitter = Math.floor(Math.random() * 500);
    setTimeout(conectarWS, base + jitter);
  };
  ws.onclose = reconectar;
  ws.onerror = () => { try { ws.close(); } catch(e){} };
  ws.onmessage = async (m) => {
    const msg = JSON.parse(m.data);
    if (msg.type === "snapshot") {
      await refreshApuracao();
      atualizarMapa();  // sem await — não bloqueia os toasts de evento
      if (state.selecionados.length >= 2) await inicializarGraficos();
      for (const ev of msg.eventos || []) {
        _absorverEventoNoState(ev);
        const nome = state.ficha[ev.sq_candidato_a]?.nome_urna || ev.sq_candidato_a;
        const num = state.ficha[ev.sq_candidato_a]?.partido;
        const cor = num ? corDoPartido(num) : "#f0b429";
        if (ev.tipo === "ELEITO_1T" || ev.tipo === "ELEITO_MAJORITARIO") {
          comemorar(nome, cor);
          toast(`${nome} eleito(a)!`, "ok");
        } else if (ev.tipo === "SEGUNDO_TURNO_DEFINIDO") {
          toast(`2º turno matematicamente definido`, "ok");
        } else {
          toast(`✓ ${nome} eleito(a)`, "ok");
        }
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
  // Limpa IMEDIATAMENTE state e UI — sem esperar o fetch retornar.
  // Bug antigo: durante o network delay (centenas de ms), UI continuava
  // mostrando totais/candidatos do cargo anterior. Se o novo cargo não
  // tinha dados (Governador/Senador antes da apuração), os dados velhos
  // ficavam grudados até um F5.
  state.ultimoSnapshot = null;
  state.snapshotAnterior = null;
  state.proporcional = null;
  state.wsRetry = 0;
  atualizarPainelTotais();
  await carregarCandidatos();
  await refreshApuracao();
  await carregarEventos();
  atualizarMapa();
  conectarWS();
}

// ============ UX: contagem regressiva pro dia D ============
function atualizarContagemRegressiva() {
  const el = $("countdown");
  if (!el) return;
  const diff = DIA_D.getTime() - Date.now();
  if (diff <= 0) { el.classList.add("oculto"); return; }
  const dias = Math.floor(diff / 86_400_000);
  const horas = Math.floor((diff % 86_400_000) / 3_600_000);
  const min = Math.floor((diff % 3_600_000) / 60_000);
  const seg = Math.floor((diff % 60_000) / 1000);
  el.classList.remove("oculto");
  el.innerHTML = `
    <svg class="cd-icone" width="14" height="14"><use href="#i-hourglass"/></svg>
    <span class="cd-titulo">Apuração começa em</span>
    <span class="cd-nums">
      <b>${String(dias).padStart(2,"0")}</b>d
      <b>${String(horas).padStart(2,"0")}</b>h
      <b>${String(min).padStart(2,"0")}</b>m
      <b>${String(seg).padStart(2,"0")}</b>s
    </span>
    <span class="cd-sub">· 4/10 17h BRT</span>
  `;
}

// Esconde o CTA "Montar minha cola eleitoral" (e variantes no header)
// depois do fechamento das urnas — não faz sentido fazer cola depois que
// votou. Chamado no boot e também pelo tick da contagem regressiva.
function esconderColaSeFechado() {
  if (Date.now() < DIA_D.getTime()) return;
  document.querySelectorAll(
    ".cta-brand, .m-icon-cta, .d-topnav-cta, #btn-cola-cta"
  ).forEach(el => el.classList.add("oculto"));
}

// ============ UX: título dinâmico da aba ============
function atualizarTituloAba(dados) {
  // Título só mostra nome do líder quando a apuração está de fato em
  // andamento (>0% apurado E líder com >0 votos). Antes o check era
  // só "tem candidatos na lista" — mas o snapshot pré-apuração já tem
  // candidatos com 0 votos, então a aba mostrava algo tipo
  // "FULANO 0% · 0% apurado" com o primeiro nome da lista (que era o
  // primeiro por ordem de numero/nome, não por votos). Bug reportado
  // pelo usuário: todos os cargos exceto presidente mostravam nome
  // de político no título mesmo sem apuração.
  const t = dados?.totais;
  const cands = dados?.candidatos;
  if (!dados?.disponivel || !cands?.length ||
      !t?.pct_apurado || t.pct_apurado <= 0) {
    document.title = TITULO_BASE;
    return;
  }
  // Líder = primeiro candidato ATIVO em votação. Retirados/cassados têm
  // votos nulos por lei (9.504 §3º), não podem ser 'líder' no título.
  const lider = cands.find(c => {
    const f = state.ficha[c.sq_candidato];
    return !f?.situacao || f.situacao === "ativo";
  });
  if (!lider?.votos || lider.votos <= 0) {
    document.title = TITULO_BASE;
    return;
  }
  const nome = state.ficha[lider.sq_candidato]?.nome_urna || "Líder";
  const pct = lider.pct_validos.toFixed(0);
  const apurado = t.pct_apurado.toFixed(0);
  document.title = `${nome} ${pct}% · ${apurado}% apurado · ${TITULO_BASE}`;
}

// ============ UX: confete + celebração ao eleger ============
function comemorar(nome, cor = "#f0b429") {
  // Confete simples via canvas (leve, sem dependência externa)
  const canvas = document.createElement("canvas");
  canvas.className = "confete";
  canvas.width = window.innerWidth;
  canvas.height = window.innerHeight;
  document.body.appendChild(canvas);
  const ctx = canvas.getContext("2d");
  const cores = [cor, "#fff", "#f0b429", "#3b82f6", "#10b981", "#ec4899"];
  const N = 180;
  const parts = Array.from({length: N}, () => ({
    x: Math.random() * canvas.width,
    y: -20 - Math.random() * 200,
    vx: (Math.random() - 0.5) * 6,
    vy: 2 + Math.random() * 5,
    rot: Math.random() * Math.PI,
    vr: (Math.random() - 0.5) * 0.2,
    cor: cores[Math.floor(Math.random() * cores.length)],
    tam: 6 + Math.random() * 8,
  }));
  let inicio = performance.now();
  function tick(t) {
    if (t - inicio > 5000) { canvas.remove(); return; }
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    for (const p of parts) {
      p.x += p.vx; p.y += p.vy; p.rot += p.vr; p.vy += 0.08;
      ctx.save();
      ctx.translate(p.x, p.y);
      ctx.rotate(p.rot);
      ctx.fillStyle = p.cor;
      ctx.fillRect(-p.tam/2, -p.tam/2, p.tam, p.tam * 0.5);
      ctx.restore();
    }
    requestAnimationFrame(tick);
  }
  requestAnimationFrame(tick);

  // Banner grande com o nome
  const banner = document.createElement("div");
  banner.className = "banner-eleito";
  banner.innerHTML = `<div class="be-ico" aria-hidden="true"><svg width="32" height="32"><use href="#i-trophy"/></svg></div><div class="be-nome">${nome}</div><div class="be-sub">Matematicamente eleito(a)</div>`;
  document.body.appendChild(banner);
  setTimeout(() => banner.classList.add("saindo"), 3500);
  setTimeout(() => banner.remove(), 4200);

  // Beep discreto (só se navegador permitir e usuário já interagiu)
  try {
    const ac = new (window.AudioContext || window.webkitAudioContext)();
    const osc = ac.createOscillator(); const g = ac.createGain();
    osc.frequency.value = 660; g.gain.value = 0.05;
    osc.connect(g); g.connect(ac.destination);
    osc.start(); osc.stop(ac.currentTime + 0.25);
    setTimeout(() => { const o2 = ac.createOscillator(); o2.frequency.value = 880;
      o2.connect(g); o2.start(); o2.stop(ac.currentTime + 0.25); }, 200);
  } catch(e) {}
}

// ============ UX: compartilhar estado atual ============
async function compartilhar() {
  const params = new URLSearchParams({
    cargo: state.cargo,
    uf: state.abrangencia,
    sqs: state.selecionados.join(","),
  });
  const url = `${location.origin}${location.pathname}?${params}`;
  const dados = state.ultimoSnapshot;
  const lider = dados?.candidatos?.[0];
  const nome = lider ? (state.ficha[lider.sq_candidato]?.nome_urna || "líder") : null;
  const texto = nome
    ? `${nome} lidera com ${lider.pct_validos.toFixed(1)}% dos votos válidos · ${dados.totais.pct_apurado.toFixed(1)}% apurado`
    : "Acompanhe a apuração 2026 ao vivo";
  if (navigator.share) {
    try { await navigator.share({ title: TITULO_BASE, text: texto, url }); return; }
    catch(e) { /* usuário cancelou — cai no fallback */ }
  }
  try { await navigator.clipboard.writeText(url); toast("🔗 Link copiado", "ok"); }
  catch(e) { prompt("Copie o link:", url); }
}

// ============ UX: aplicar estado vindo da URL ============
function aplicarEstadoDaURL() {
  const p = new URLSearchParams(location.search);
  if (p.has("cargo")) state.cargo = +p.get("cargo") || 1;
  if (p.has("uf")) state.abrangencia = p.get("uf");
  if (p.has("sqs")) state.selecionados = p.get("sqs").split(",").filter(Boolean).slice(0, MAX_SEL);
  const selCargo = $("sel-cargo"); if (selCargo) selCargo.value = state.cargo;
}

// ============ UX: modal de atalhos ============
function abrirAjuda() {
  const html = `
    <div class="ajuda-card">
      <h3>Atalhos</h3>
      <table class="ajuda">
        <tr><td><kbd>/</kbd></td><td>Focar busca</td></tr>
        <tr><td><kbd>c</kbd></td><td>Comparar selecionados</td></tr>
        <tr><td><kbd>n</kbd></td><td>Ativar notificações</td></tr>
        <tr><td><kbd>s</kbd></td><td>Compartilhar</td></tr>
        <tr><td><kbd>f</kbd></td><td>Modo TV (foco no líder)</td></tr>
        <tr><td><kbd>?</kbd></td><td>Esta ajuda</td></tr>
        <tr><td><kbd>Esc</kbd></td><td>Fechar</td></tr>
      </table>
      <p class="ajuda-sub">Todos os cálculos usam desigualdades estritas — só chamamos eleição quando é matematicamente impossível reverter.</p>
    </div>`;
  const modal = $("modal-cand");
  const card = $("modal-card");
  if (!modal || !card) return;
  card.innerHTML = html;
  modal.classList.remove("oculto");
}

// ============ UX: modo TV (foco no líder) ============
function toggleModoTV() {
  document.body.classList.toggle("modo-tv");
  const isTV = document.body.classList.contains("modo-tv");
  if (isTV && document.documentElement.requestFullscreen) {
    document.documentElement.requestFullscreen().catch(() => {});
  } else if (!isTV && document.fullscreenElement) {
    document.exitFullscreen().catch(() => {});
  }
}

// ============ MOBILE APP CHROME ============
// Só ativa em <=768px. Bottom-nav com tabs, chips clicáveis de cargo/UF,
// bottom sheet pra escolher, FAB de comparar. Sincroniza com os selects
// desktop pra qualquer mudança se refletir dos dois lados.

const NOMES_CARGO = { 1: "Presidente", 3: "Governador", 5: "Senador",
                      6: "Dep. Federal", 7: "Dep. Estadual" };
const NOMES_UF_LONG = { BR: "Brasil" };
// Preenchido dinamicamente quando /api/ufs chega
function sincronizarChipsMobile() {
  const cargoEl = $("m-chip-cargo-val");
  const ufEl = $("m-chip-uf-val");
  if (cargoEl) cargoEl.textContent = NOMES_CARGO[state.cargo] || "—";
  if (ufEl) ufEl.textContent = NOMES_UF_LONG[state.abrangencia] || state.abrangencia;
  // Também sincroniza indicador de conexão mobile
  const dotDesk = document.querySelector("#conexao .dot");
  const dotMob = $("m-dot");
  if (dotDesk && dotMob) dotMob.classList.toggle("on", dotDesk.classList.contains("on"));
  // Copia últ. snapshot e apurado
  const p = $("pct-apurado")?.textContent;
  if (p) { const m = $("m-pct"); if (m) m.textContent = p; }
  const u = $("ultimo")?.textContent;
  if (u) { const m = $("m-ultimo"); if (m) m.textContent = u; }
  const prog = $("prog-apurado")?.style.width;
  if (prog) { const m = $("m-prog"); if (m) m.style.width = prog; }
  // Sincroniza texto de "ao vivo"/"reconectando"
  const lab = $("conexao-label")?.textContent;
  if (lab) { const m = $("m-live-label"); if (m) m.textContent = lab; }
}

function abrirBottomSheet(titulo, opcoes, aoEscolher, layoutGrid = false) {
  const sheet = $("m-sheet");
  const lista = $("m-sheet-lista");
  const t = $("m-sheet-titulo");
  if (!sheet || !lista) return;
  t.textContent = titulo;
  lista.innerHTML = "";
  const grupo = layoutGrid ? document.createElement("div") : lista;
  if (layoutGrid) { grupo.className = "m-sheet-opt-grupo"; lista.appendChild(grupo); }
  for (const opt of opcoes) {
    const btn = document.createElement("button");
    btn.className = "m-sheet-opt" + (opt.ativo ? " ativo" : "");
    btn.textContent = opt.label;
    btn.addEventListener("click", () => {
      sheet.classList.add("oculto");
      aoEscolher(opt.value);
    });
    grupo.appendChild(btn);
  }
  sheet.classList.remove("oculto");
}

function fecharBottomSheet() {
  $("m-sheet")?.classList.add("oculto");
}

const TITULOS_TAB = {
  placar: "Placar ao vivo",
  mapa: "Mapa por região",
  comparar: "Comparar candidatos",
  eventos: "Linha do tempo",
  mais: "Sobre e opções",
};

function trocarTabMobile(tab) {
  const page = document.querySelector("main.page");
  if (!page) return;
  // Se for compare mas nada selecionado, avisa e mantém no placar
  if (tab === "comparar" && state.selecionados.length < 2) {
    toast("Escolha pelo menos 2 candidatos no placar antes.", "warn");
    return;
  }
  // Transição visual: fade+slide na section entrando
  page.classList.add("m-tab-trocando");
  setTimeout(() => {
    ["placar","mapa","comparar","eventos","mais"].forEach(t => {
      page.classList.remove(`m-tab-${t}`);
      document.body.classList.remove(`m-tab-${t}`);
    });
    page.classList.add(`m-tab-${tab}`);
    document.body.classList.add(`m-tab-${tab}`);
    page.classList.remove("m-tab-trocando");
    // Título grande da tab
    const t = $("m-tab-titulo");
    if (t) t.textContent = TITULOS_TAB[tab] || tab;
    // Ao entrar em "comparar", abre a comparação sem esperar clique
    if (tab === "comparar") abrirComparacao();
  }, 120);
  document.querySelectorAll(".m-nav-item").forEach(b => {
    const on = b.dataset.tab === tab;
    b.classList.toggle("ativo", on);
    b.setAttribute("aria-selected", on ? "true" : "false");
  });
  window.scrollTo({ top: 0, behavior: "smooth" });
  try { localStorage.setItem("elei-es:m-tab", tab); } catch(e) {}
}

function atualizarFabMobile() {
  const fab = $("m-fab-comparar");
  if (!fab) return;
  const n = state.selecionados.length;
  $("m-fab-count").textContent = n;
  fab.classList.toggle("oculto", n < 2);
}

function bootMobile() {
  // Sync inicial dos chips
  sincronizarChipsMobile();
  // Ripple nos elementos touch (bottom nav, FAB, chips, ícones do topo)
  document.querySelectorAll(".m-nav-item, .m-fab, .m-chip, .m-icon-btn, .btn-ghost")
    .forEach(addRipple);

  // Chip Cargo → bottom sheet
  $("m-chip-cargo")?.addEventListener("click", () => {
    abrirBottomSheet("Escolher cargo",
      Object.entries(NOMES_CARGO).map(([k, v]) => ({
        label: v, value: +k, ativo: +k === state.cargo,
      })),
      (v) => {
        state.cargo = v;
        $("sel-cargo").value = v;
        salvarPrefs();
        onFiltroChange();
        sincronizarChipsMobile();
      });
  });

  // Chip UF → bottom sheet em grade 3 colunas
  $("m-chip-uf")?.addEventListener("click", () => {
    const opts = Array.from($("sel-uf").options)
      .filter(o => !o.hidden && !o.disabled)
      .map(o => ({
        label: o.value, value: o.value, ativo: o.value === state.abrangencia,
      }));
    abrirBottomSheet("Escolher local", opts, (v) => {
      state.abrangencia = v;
      $("sel-uf").value = v;
      salvarPrefs();
      onFiltroChange();
      sincronizarChipsMobile();
    }, true);
  });

  // Fecha sheet ao clicar no fundo
  $("m-sheet")?.querySelector(".m-sheet-back")?.addEventListener("click", fecharBottomSheet);

  // Bottom nav
  document.querySelectorAll(".m-nav-item").forEach(b => {
    b.addEventListener("click", () => trocarTabMobile(b.dataset.tab));
  });
  // Restaura última tab (default: placar)
  let tabInicial = "placar";
  try { tabInicial = localStorage.getItem("elei-es:m-tab") || "placar"; } catch(e) {}
  trocarTabMobile(tabInicial);

  // FAB de comparar
  $("m-fab-comparar")?.addEventListener("click", () => {
    trocarTabMobile("comparar");
    abrirComparacao();
  });

  // Botão notif mobile → mesma função do desktop
  $("m-btn-notif")?.addEventListener("click", pedirNotificacoes);

  // Sincroniza a cada 2s (barato — só lê DOM)
  setInterval(sincronizarChipsMobile, 2000);
}

async function pedirNotificacoes() {
  if (!("Notification" in window)) return toast("Navegador sem suporte a notificações.", "warn");
  const p = await Notification.requestPermission();
  toast(p === "granted" ? "Notificações ativadas" : "Notificações não permitidas pelo navegador",
        p === "granted" ? "ok" : "warn");
}

// ============ boot ============
async function boot() {
  $("sel-cargo").addEventListener("change", (e) => { state.cargo = +e.target.value; salvarPrefs(); onFiltroChange(); });
  $("sel-uf").addEventListener("change", (e) => { state.abrangencia = e.target.value; salvarPrefs(); onFiltroChange(); });
  $("btn-fechar").addEventListener("click", fecharComparacao);
  $("btn-comparar").addEventListener("click", abrirComparacao);
  $("btn-notif").addEventListener("click", pedirNotificacoes);
  // Atalhos de teclado
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") { fecharModal(); return; }
    // Ignora quando digitando
    const t = e.target.tagName;
    if (t === "INPUT" || t === "SELECT" || t === "TEXTAREA") return;
    if (e.key === "/") { e.preventDefault(); $("busca-nome")?.focus(); }
    else if (e.key === "c" && state.selecionados.length >= 2) $("btn-comparar")?.click();
    else if (e.key === "n") $("btn-notif")?.click();
    else if (e.key === "s") compartilhar();
    else if (e.key === "f") toggleModoTV();
    else if (e.key === "?") abrirAjuda();
  });

  // Botões de compartilhar / ajuda (se existirem no HTML)
  $("btn-compartilhar")?.addEventListener("click", compartilhar);
  $("btn-ajuda")?.addEventListener("click", abrirAjuda);

  // Countdown regressivo enquanto TSE não abre a apuração
  setInterval(() => { atualizarContagemRegressiva(); esconderColaSeFechado(); }, 1000);
  atualizarContagemRegressiva();
  esconderColaSeFechado();

  // Atualiza "há X segundos" no elemento #ultimo a cada 5s
  setInterval(() => {
    const el = $("ultimo");
    const iso = el?.dataset.iso;
    if (!iso) return;
    const diff = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
    let rotulo;
    if (diff < 5) rotulo = "agora";
    else if (diff < 60) rotulo = `há ${diff}s`;
    else if (diff < 3600) rotulo = `há ${Math.floor(diff / 60)}min`;
    else rotulo = fmtHora(iso);
    el.textContent = rotulo;
  }, 5000);

  // Header ganha sombra ao rolar + botão voltar ao topo + scroll-spy do topnav
  const hero = document.querySelector(".hero");
  const btnTopo = $("btn-topo");
  const topnavLinks = document.querySelectorAll(".d-topnav-link[data-anchor]");
  const secoes = {
    lista: $("lista-candidatos"),
    mapa: document.querySelector(".mapa-secao"),
    timeline: document.querySelector(".timeline-secao"),
  };
  const onScroll = () => {
    const y = window.scrollY;
    hero.classList.toggle("scrolled", y > 8);
    document.body.classList.toggle("scrolled", y > 8);  // mobile: encolhe .m-stats
    btnTopo.classList.toggle("visible", y > 400);
    // scroll-spy: qual section está mais visível
    let ativa = "lista";
    const meio = y + window.innerHeight / 3;
    for (const [nome, el] of Object.entries(secoes)) {
      if (el && el.offsetTop <= meio) ativa = nome;
    }
    topnavLinks.forEach(l => l.classList.toggle("ativo", l.dataset.anchor === ativa));
  };
  window.addEventListener("scroll", onScroll, { passive: true });
  onScroll();
  btnTopo.addEventListener("click", () => window.scrollTo({ top: 0, behavior: "smooth" }));

  // filtros da lista
  let buscaTimer;
  $("busca-nome").addEventListener("input", (e) => {
    clearTimeout(buscaTimer);
    buscaTimer = setTimeout(() => {
      state.filtro.texto = e.target.value;
      salvarPrefs();
      renderLista();
    }, 150);
  });
  $("filtro-partido").addEventListener("change", (e) => {
    state.filtro.partido = e.target.value;
    salvarPrefs();
    renderLista();
  });
  $("ordenar").addEventListener("change", (e) => {
    state.filtro.ordenar = e.target.value;
    salvarPrefs();
    renderLista();
  });

  // Link do bot do Telegram — só aparece quando backend confirma que
  // TELEGRAM_BOT_TOKEN está setado.
  try {
    const cfg = await get("/api/config-publica");
    if (cfg?.telegram_bot) {
      const a = $("btn-telegram");
      if (a) {
        a.href = `https://t.me/${cfg.telegram_bot}`;
        a.classList.remove("oculto");
      }
    }
  } catch(e) { /* ok */ }

  try {
    const ufs = await get("/api/ufs");
    const selUF = $("sel-uf");
    for (const u of ufs) {
      const opt = document.createElement("option");
      opt.value = u.sigla; opt.textContent = `${u.sigla} — ${u.nome}`;
      selUF.appendChild(opt);
    }
    // Opção fixa: voto do exterior (ZZ). Só vota presidente — a função
    // ajustarUFParaCargo() esconde/mostra conforme o cargo escolhido.
    if (!Array.from(selUF.options).some(o => o.value === "ZZ")) {
      const optZZ = document.createElement("option");
      optZZ.value = "ZZ"; optZZ.textContent = "ZZ — Exterior (brasileiros no exterior)";
      selUF.appendChild(optZZ);
    }
  } catch (e) { /* ok */ }

  // Ordem: 1) prefs salvas 2) URL da share (sobrescreve) 3) ajusta UF ↔ cargo
  carregarPrefs();
  // Ripple em botões desktop também (não só mobile — QA reclamou de
  // "não vi animação"). Aplica em botões que já existem no DOM inicial.
  document.querySelectorAll(".btn-ghost, .btn-primary, .d-topnav-link").forEach(addRipple);

  aplicarEstadoDaURL();
  // Reflete no <select> antes do primeiro carregamento
  const selCargo = $("sel-cargo"); if (selCargo) selCargo.value = state.cargo;
  ajustarUFParaCargo();
  // Restaura filtros nos inputs (localStorage → UI)
  const bn = $("busca-nome"); if (bn && state.filtro.texto) bn.value = state.filtro.texto;
  const fp = $("filtro-partido"); if (fp && state.filtro.partido) fp.value = state.filtro.partido;
  const ord = $("ordenar"); if (ord && state.filtro.ordenar) ord.value = state.filtro.ordenar;

  // Rola pro topo ao abrir — o browser às vezes restaura scroll velho
  // e a página aparece "no meio" ou "no fim" pro usuário
  if ("scrollRestoration" in history) history.scrollRestoration = "manual";
  window.scrollTo(0, 0);

  await carregarCandidatos();
  await refreshApuracao();
  await carregarEventos();
  atualizarMapa();
  conectarWS();
  bootMobile();
}

boot().catch(e => { console.error(e); toast("Erro: " + e.message, "danger"); });
