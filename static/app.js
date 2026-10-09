import { renderMapa } from "/static/mapa-br.js?v=20261009a";
import { corDoPartido, siglaDoPartido, badgePartidoHtml } from "/static/partidos.js?v=20261009a";

// Resolve a cor "oficial" de um candidato = cor do seu partido.
// Usada no mapa (pintar UF/município pelo líder) e no card (barra de
// votos + accent da esquerda). Fallback pra paleta genérica quando o
// candidato ainda não foi importado (ficha ausente).
function corDoCandidato(sq_candidato, fallbackIdx = 0) {
  const f = state.ficha?.[sq_candidato];
  const partidoNumero = f?.partido;
  if (partidoNumero) return corDoPartido(partidoNumero);
  return PALETA[fallbackIdx % PALETA.length] || "#f0b429";
}

const PALETA = ["#f0b429", "#3b82f6", "#ec4899", "#10b981", "#a855f7", "#f97316"];
const TZ = "America/Sao_Paulo";
const MAX_SEL = 4;
// Início oficial da apuração 2026: domingo, 4/10/2026 às 17h de Brasília.
// Eleições Gerais 2026 — primeiro domingo de outubro, art. 1º da Lei 9.504/97.
// 17h BRT = fechamento das urnas e início da apuração.
const DIA_D = new Date("2026-10-04T17:00:00-03:00");
// 2º turno 2026: 26/10/2026 (último domingo de outubro), 17h BRT.
const DIA_D_2T = new Date("2026-10-26T17:00:00-03:00");
const TITULO_BASE = "Apuração 2026 · Brasil";

// Default do turno: depois do fechamento do 1T (04/10 17h BRT), o site
// vira a cara pro 2T automaticamente. Antes de 04/10 = 1T (pré-apuração);
// a partir de 05/10 = 2T (foco principal do site). User pode trocar
// manualmente via toggle no header.
function _turnoPadrao() {
  // Depois de 05/10/2026 00h BRT (dia seguinte ao 1T), default = 2
  const CORTE = new Date("2026-10-05T00:00:00-03:00");
  return Date.now() >= CORTE.getTime() ? 2 : 1;
}

const state = {
  cargo: 1,
  abrangencia: "BR",
  turno: _turnoPadrao(),
  candidatos: [],
  ficha: {},
  selecionados: [],
  ultimoSnapshot: null,
  snapshotAnterior: null,   // pra calcular delta/tendência
  graficos: {},
  ws: null,
  filtro: { texto: "", partido: "", ordenar: "votos" },
  // Paginação da lista — ativa só pra cargos com muitos candidatos
  // (Dep Est tem 100+ por UF, matou dispositivos mais lentos). Reseta
  // pra 1 em cada mudança de cargo/UF/filtro.
  paginaAtual: 1,
  proporcional: null,
  // Candidatos matematicamente eliminados — sem chance aritmética de
  // vencer/ir ao 2º turno mesmo somando todos os votos restantes. Poputa
  // via /api/eventos + eventos que chegam pelo WS.
  eliminados: new Set(),
  // Candidatos eleitos matematicamente (majoritário ou proporcional).
  eleitos: new Set(),
  // Dupla do 2º turno em majoritários — populado via SEGUNDO_TURNO_DEFINIDO.
  // Visual claro no card ("Vai pro 2º turno") quando esse estado existe.
  segundoTurno: new Set(),
};

// ============ persistência de preferências ============
// Salva cargo/UF/filtros no localStorage pro usuário reencontrar
// tudo do jeito que deixou na última visita. Falha silenciosamente
// (modo anônimo, storage cheio, etc).
const PREFS_KEY = "elei-es:prefs:v1";
function salvarPrefs() {
  try {
    // texto da busca NÃO é salvo entre sessões — é consulta de momento
    // ("fulano") que não faz sentido manter quando o user volta mais tarde.
    // partido/ordenar são preferências estáveis, essas sim ficam.
    localStorage.setItem(PREFS_KEY, JSON.stringify({
      cargo: state.cargo,
      abrangencia: state.abrangencia,
      turno: state.turno,
      filtro: {
        partido: state.filtro.partido || "",
        ordenar: state.filtro.ordenar || "votos",
      },
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
    if (p.turno === 1 || p.turno === 2) state.turno = p.turno;
    if (p.filtro && typeof p.filtro === "object") state.filtro = {
      texto: "",  // sempre reseta — não restaura busca velha
      partido: p.filtro.partido || "",
      ordenar: p.filtro.ordenar || "votos",
    };
  } catch(e) {}
}

// ============ Motion helpers (performance-safe) ============
// Só usa transform/opacity, honra prefers-reduced-motion, aplica
// will-change só durante o movimento.

const REDUCED_MOTION = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

// ============ Detecção de TV (SmartTV, consoles, Chromecast etc) ============
// Ativa layout "10-foot UI" quando o visitante abre o site pela TV. A UI
// nessa modo é dashboard (lista + mapa + gráfico + eventos visíveis ao
// mesmo tempo), fontes maiores, sem elementos que exigem touch/mouse.
// Pode ser forçado via ?tv=1 pra teste no desktop.
const TV_KEY = "elei-es:tv";
function detectarTV() {
  try {
    const forcado = new URLSearchParams(location.search).get("tv");
    if (forcado === "1") return true;
    if (forcado === "0") return false;
    // Preferência manual salva (botão no rodapé). Precede detecção de UA
    // — útil quando o navegador da TV se identifica como mobile (caso
    // comum em Android TV com browsers de terceiros).
    const salvo = localStorage.getItem(TV_KEY);
    if (salvo === "1") return true;
    if (salvo === "0") return false;
  } catch(e) {}
  const ua = navigator.userAgent || "";
  // UAs comuns: Samsung Tizen, LG WebOS, Android TV, Google TV, Apple TV,
  // Roku, HbbTV genérico, PlayStation, Xbox, Chromecast, Vidaa, Vewd
  return /SmartTV|SMART-TV|GoogleTV|AppleTV|LGSmartTV|LGE WebOS|Tizen|Web0?OS|WebOS|Roku|PlayStation|Xbox|HbbTV|NetCast|BRAVIA|SmartHub|CrKey|Vidaa|VIDAA|Vewd|Opera TV/i.test(ua);
}
if (detectarTV()) document.body.classList.add("is-tv");
// Classe adicional pra layouts específicos de turno (TV 2T usa layout
// head-to-head com 2 cards gigantes em vez de lista com scroll).
function _sincronizarClasseTurno() {
  document.body.classList.toggle("turno-1", state.turno === 1);
  document.body.classList.toggle("turno-2", state.turno === 2);
}

// Toggle manual do modo TV (botão no rodapé).
function alternarModoTV() {
  const ativar = !document.body.classList.contains("is-tv");
  document.body.classList.toggle("is-tv", ativar);
  try { localStorage.setItem(TV_KEY, ativar ? "1" : "0"); } catch(e) {}
  atualizarBotaoTV();
  // CSS do grid demora alguns ms pra aplicar; re-renderiza ECharts
  // depois pra pegarem os novos tamanhos dos containers. 2 passes:
  // primeiro force resize dos existentes, depois re-render completo.
  requestAnimationFrame(() => {
    window.dispatchEvent(new Event("resize"));
    setTimeout(() => {
      try { atualizarMapa(); } catch(e) {}
      try { atualizarGrafHome(); } catch(e) {}
      window.dispatchEvent(new Event("resize"));
    }, 120);
  });
  // Em modo TV, aplica tabindex nos cards já renderizados pra receber foco
  if (ativar) {
    document.querySelectorAll(".grid-candidatos .candidato").forEach(c => c.tabIndex = 0);
    navTVPorSetas();
    // Foca o primeiro card pra feedback imediato
    const primeiro = document.querySelector(".grid-candidatos .candidato");
    primeiro?.focus();
  } else {
    document.querySelectorAll(".grid-candidatos .candidato").forEach(c => c.removeAttribute("tabindex"));
  }
}
function atualizarBotaoTV() {
  const b = document.getElementById("btn-tv");
  if (!b) return;
  const ativo = document.body.classList.contains("is-tv");
  b.setAttribute("aria-pressed", ativo ? "true" : "false");
  b.textContent = ativo ? "📺 Sair do modo TV" : "📺 Modo TV";
}

// Relógio BRT no topo — formata sempre em America/Sao_Paulo, independente
// do fuso do navegador do usuário (um brasileiro acessando de Londres
// ainda vê a hora de Brasília, que é a referência da apuração do TSE).
// Atualiza a cada segundo. Pausa quando a aba está em background pra
// economizar bateria em mobile/TV.
const _fmtRelogio = new Intl.DateTimeFormat("pt-BR", {
  timeZone: "America/Sao_Paulo",
  hour: "2-digit", minute: "2-digit", second: "2-digit",
  hour12: false,
});
function tickRelogio() {
  const el = document.getElementById("relogio-brt");
  if (!el) return;
  el.textContent = _fmtRelogio.format(new Date());
  el.setAttribute("datetime", new Date().toISOString());
}
function iniciarRelogio() {
  tickRelogio();
  // Alinha pra começar no próximo segundo cheio pra o relógio não
  // flutuar com drift de hundreds-of-ms. Depois intervalo fixo de 1s.
  const msAteProximoSegundo = 1000 - (Date.now() % 1000);
  setTimeout(() => {
    tickRelogio();
    setInterval(tickRelogio, 1000);
  }, msAteProximoSegundo);
}

// Navegação por setas do controle remoto em modo TV. Os cards de
// candidato ganham tabindex=0; setas movem o foco visível pro próximo/
// anterior card da lista. Enter abre a ficha (reaproveita o click handler
// existente). Esc fecha modais abertos (ESC existe no controle como "back"
// na maioria das SmartTVs).
let _navTVInstalado = false;
function navTVPorSetas() {
  if (!document.body.classList.contains("is-tv") || _navTVInstalado) return;
  _navTVInstalado = true;
  document.addEventListener("keydown", (e) => {
    const alvo = document.activeElement;
    const cards = Array.from(document.querySelectorAll(".grid-candidatos .candidato"));
    if (!cards.length) return;
    const idx = cards.indexOf(alvo);
    let proximo = null;
    if (e.key === "ArrowDown" || e.key === "ArrowRight") proximo = cards[Math.min(cards.length - 1, (idx < 0 ? 0 : idx + 1))];
    else if (e.key === "ArrowUp" || e.key === "ArrowLeft") proximo = cards[Math.max(0, (idx < 0 ? 0 : idx - 1))];
    else if (e.key === "Home") proximo = cards[0];
    else if (e.key === "End") proximo = cards[cards.length - 1];
    else return;
    e.preventDefault();
    if (proximo) {
      proximo.focus();
      proximo.scrollIntoView({ block: "center", behavior: "smooth" });
    }
  });
}

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
function animarNumero(el, novoValor, duracao = 500, sufixo = "") {
  if (!el) return;
  const anterior = parseInt((el.dataset.valor || el.textContent).replace(/\D/g, ""), 10) || 0;
  if (anterior === novoValor) { el.textContent = fmtNum(novoValor) + sufixo; return; }
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
    el.textContent = fmtNum(atual) + sufixo;
    if (p < 1) requestAnimationFrame(tick);
    else el.textContent = fmtNum(novoValor) + sufixo;
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

// Quais cargos existem em cada turno. Lei 9.504/97 + CF:
//   1º turno: Presidente, Governador, Senador, Dep. Federal, Dep. Estadual
//   2º turno: SÓ Presidente e Governador (nos lugares que não tiveram
//             maioria absoluta no 1T). Senador e Deputados nunca têm 2T.
const CARGOS_POR_TURNO = { 1: [1, 3, 5, 6, 7], 2: [1, 3] };

function ajustarCargosPorTurno() {
  const sel = document.getElementById("sel-cargo");
  if (!sel) return;
  const permitidos = new Set(CARGOS_POR_TURNO[state.turno] || CARGOS_POR_TURNO[1]);
  Array.from(sel.options).forEach(o => {
    const num = Number(o.value);
    const permitido = permitidos.has(num);
    o.hidden = !permitido;
    o.disabled = !permitido;
  });
  // Se o cargo atual não existe nesse turno, cai pro Presidente
  if (!permitidos.has(state.cargo)) {
    state.cargo = 1;
    sel.value = "1";
  }
  // Também atualiza o estado do toggle visual
  document.querySelectorAll(".turno-btn").forEach(b => {
    b.setAttribute("aria-pressed",
      Number(b.dataset.turno) === state.turno ? "true" : "false");
  });
}

function ajustarUFParaCargo() {
  ajustarCargosPorTurno();
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
  // 2T + Governador: só mostra UFs que têm 2º turno (CF art. 77 §2º,
  // >50% dos válidos no 1T encerra). As demais estão decididas, não
  // há coleta nem apuração de 2T lá.
  const ufsGov2T = state._ufsGov2T;  // populado por carregarUfsGov2T()
  Array.from(selUF.options).forEach(o => {
    if (o.value === "ZZ" || o.value === "BR") return;  // controlados acima
    const esconderPor2T = (state.turno === 2 && state.cargo === 3 &&
                           Array.isArray(ufsGov2T) && !ufsGov2T.includes(o.value));
    o.hidden = esconderPor2T;
    o.disabled = esconderPor2T;
  });
  // Se a UF atual não tem 2T de Gov, pula pra primeira que tem
  if (state.turno === 2 && state.cargo === 3 && Array.isArray(ufsGov2T) &&
      ufsGov2T.length > 0 && !ufsGov2T.includes(state.abrangencia)) {
    state.abrangencia = ufsGov2T[0];
    selUF.value = state.abrangencia;
  }
}

// Lista de UFs com 2T de Gov. Cacheia uma vez por carga; refetch quando
// chega evento SEGUNDO_TURNO_DEFINIDO (novo 2T aparece durante apuração 1T).
async function carregarUfsGov2T() {
  try {
    state._ufsGov2T = await get("/api/segundo-turno/ufs-governador");
  } catch (e) {
    state._ufsGov2T = [];
  }
}

// Trocar turno = reset completo (muda cargos disponíveis, estado da
// apuração é outro, snapshots diferentes, candidatos diferentes).
// Equivalente a mudar cargo+UF ao mesmo tempo + persistir em URL.
async function trocarTurno(novoTurno) {
  if (novoTurno !== 1 && novoTurno !== 2) return;
  if (state.turno === novoTurno) return;
  state.turno = novoTurno;
  _sincronizarClasseTurno();
  // Força ECharts a redimensionar após layout do novo turno aplicar.
  // Em TV 2T sem isso o mapa e gráfico ficam no tamanho antigo até
  // o próximo snapshot — primeiros 20s parecem bugados.
  requestAnimationFrame(() => {
    setTimeout(() => window.dispatchEvent(new Event("resize")), 150);
  });
  // Reset de contexto específico do turno anterior
  state.ultimoSnapshot = null;
  state.snapshotAnterior = null;
  state.proporcional = null;
  state.eliminados.clear();
  state.eleitos.clear();
  state.segundoTurno.clear();
  state.selecionados = [];
  salvarPrefs();
  // Reflete turno na URL pra links compartilhados preservarem o contexto
  try {
    const u = new URL(location.href);
    u.searchParams.set("turno", String(state.turno));
    history.replaceState({}, "", u.toString());
  } catch(e) {}
  await carregarUfsGov2T();  // lista pode ter mudado entre páginas 1T↔2T
  await onFiltroChange();
}

// ============ lista de candidatos ============
async function carregarCandidatos() {
  renderSkeletons(6);
  const uf = state.abrangencia === "BR" ? "" : `&uf=${state.abrangencia}`;
  let cands;
  try {
    cands = await get(`/api/candidatos?cargo=${state.cargo}${uf}&turno=${state.turno}`);
  } catch (e) {
    // Error state: ao invés de travar com skeletons eternos, mostra uma
    // UI acionável com botão "tentar de novo". Toast também sinaliza.
    console.warn("falha ao carregar candidatos:", e);
    toast("Falha de rede ao carregar candidatos", "warn");
    renderErroCarregamento("candidatos", carregarCandidatos);
    return;
  }
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

// Error state generalizado — reusável pra qualquer fetch que falhar.
// UI acionável (botão de retry) + mensagem clara + ícone.
function renderErroCarregamento(contexto, acaoRetry) {
  const el = document.getElementById("lista-candidatos");
  if (!el) return;
  el.innerHTML = `
    <div class="empty-state error-state" role="alert">
      <svg class="empty-ico" width="48" height="48" aria-hidden="true"><use href="#i-x"/></svg>
      <h3>Não consegui carregar ${contexto}</h3>
      <p>Pode ser rede caindo ou o servidor sobrecarregado no dia da apuração.
      Tenta de novo em alguns segundos.</p>
      <button type="button" class="btn-primary error-retry">↻ Tentar de novo</button>
    </div>`;
  el.querySelector(".error-retry")?.addEventListener("click", () => {
    renderSkeletons(6);
    acaoRetry();
  });
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
  // Identifica retirados (situacao != ativo). Avalanche, Marçal e cia:
  // votos neles são nulos por lei (9.504/97 art. 175 §3º) → sempre pro FIM
  // da lista, independente do filtro de ordenação, pra não ocupar lugar
  // de candidato real na visão principal do usuário.
  const retiradoDe = (c) => {
    const f = state.ficha[c.sq_candidato];
    return !!(f?.situacao && f.situacao !== "ativo");
  };
  // Detecta "fantasma de duplicata ativa": quando 2+ candidatos ativos
  // compartilham (uf, numero) e um tem votos > 0 e outro tem 0. O de 0
  // é o cadastro TSE que ficou órfão — mandamos pro fim também.
  const chaveNumero = (c) => `${c.uf || "BR"}|${c.numero}`;
  const temVotosNoGrupo = new Map();
  for (const c of arr) {
    const k = chaveNumero(c);
    const v = votosPorSq.get(c.sq_candidato) || 0;
    temVotosNoGrupo.set(k, Math.max(temVotosNoGrupo.get(k) || 0, v));
  }
  const fantasmaDe = (c) => {
    const k = chaveNumero(c);
    const meus = votosPorSq.get(c.sq_candidato) || 0;
    const maxDoGrupo = temVotosNoGrupo.get(k) || 0;
    return maxDoGrupo > 0 && meus === 0 && !retiradoDe(c);
  };
  const ord = state.filtro.ordenar;
  arr.sort((a, b) => {
    // 1) retirados sempre no fim
    const rA = retiradoDe(a) ? 1 : 0, rB = retiradoDe(b) ? 1 : 0;
    if (rA !== rB) return rA - rB;
    // 2) fantasmas de duplicata ativa no fim do grupo ativo
    const gA = fantasmaDe(a) ? 1 : 0, gB = fantasmaDe(b) ? 1 : 0;
    if (gA !== gB) return gA - gB;
    // 3) critério escolhido pelo usuário
    if (ord === "nome") return (a.nome_urna || "").localeCompare(b.nome_urna || "");
    if (ord === "numero") return a.numero - b.numero;
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
  // Detecta candidatos "em conflito": mesmo (uf, numero) com >1 ativo.
  // Caso real 2026: Guto Schiavetto SP-144 tem 2 sq_candidato ambos
  // ativos (TSE deixou dois registros). Nenhum de nós sabe qual é o
  // "real" — os votos no dia D revelam. Marcamos visualmente pra
  // deixar explícito que não é bug de renderização.
  const ctConflito = new Map();
  for (const c of state.candidatos) {
    if (c.situacao && c.situacao !== "ativo") continue;
    const k = `${c.uf || "BR"}|${c.numero}`;
    ctConflito.set(k, (ctConflito.get(k) || 0) + 1);
  }
  const emConflito = new Set();
  for (const c of state.candidatos) {
    if (c.situacao && c.situacao !== "ativo") continue;
    const k = `${c.uf || "BR"}|${c.numero}`;
    if ((ctConflito.get(k) || 0) > 1) emConflito.add(c.sq_candidato);
  }
  state._emConflito = emConflito;
  $("chip-total").textContent =
    filtrados.length === state.candidatos.length
      ? `${state.candidatos.length} candidatos`
      : `${filtrados.length} de ${state.candidatos.length}`;
  if (state.candidatos.length === 0) {
    if (state.turno === 2) {
      // Contexto diferente — 2T é em 26/10/2026 e normalmente só define
      // os candidatos depois que o 1T fecha matematicamente.
      const cargoNome = state.cargo === 3 ? "esta UF" : "a disputa nacional";
      el.innerHTML = `<div class="empty-state">
        <svg class="empty-ico" width="48" height="48"><use href="#i-clock"/></svg>
        <h3>Sem 2º turno aqui</h3>
        <p>Ou ${cargoNome} foi decidida no 1º turno (vitória por maioria absoluta),
        ou o TSE ainda não publicou os candidatos do 2º turno.
        Volte pro 1º turno no toggle acima pra ver o resultado final.</p>
      </div>`;
    } else {
      el.innerHTML = `<div class="empty-state">
        <svg class="empty-ico" width="48" height="48"><use href="#i-clock"/></svg>
        <h3>Aguardando o TSE liberar os dados</h3>
        <p>Os primeiros resultados começam a sair a partir das 17h de domingo, quando as urnas fecham. O placar preenche sozinho assim que os primeiros votos chegarem.</p>
      </div>`;
    }
    return;
  }
  if (filtrados.length === 0) {
    el.innerHTML = `<div class="empty-state">
      <h3>Nada com esse filtro</h3>
      <p>Tente escrever outra parte do nome, mudar o partido ou limpar a busca.</p>
    </div>`;
    return;
  }
  // PAGINAÇÃO — ativa quando lista tem mais que CANDS_POR_PAGINA.
  // Dep Est SP tem 94 candidatos; renderizar tudo trava celular médio.
  // 20 por página = ~3-5 páginas, scroll leve + dispositivo responsivo.
  const CANDS_POR_PAGINA = 20;
  const temPaginacao = filtrados.length > CANDS_POR_PAGINA;
  const totalPaginas = Math.ceil(filtrados.length / CANDS_POR_PAGINA);
  // Clamp: se trocou cargo e página atual não existe mais, volta pra 1
  if (state.paginaAtual > totalPaginas) state.paginaAtual = 1;
  const pagina = temPaginacao ? state.paginaAtual : 1;
  const inicio = (pagina - 1) * CANDS_POR_PAGINA;
  const fim = inicio + CANDS_POR_PAGINA;
  const paginaAtualItens = temPaginacao ? filtrados.slice(inicio, fim) : filtrados;
  // FLIP: mede posições antes de re-renderizar pra animar reordenação
  const flip = flipReorder(el);

  const primeiraVez = !el.dataset.jaRenderizou;
  // PERF: constrói todos os cards em DocumentFragment e appenda UMA vez
  // no DOM. Antes N appendChild sucessivos causavam N reflows em
  // dispositivos lentos. Agora é 1 reflow só.
  const frag = document.createDocumentFragment();
  for (const c of paginaAtualItens) {
    const sel = state.selecionados.indexOf(c.sq_candidato);
    const div = document.createElement("div");
    const eliminado = state.eliminados.has(c.sq_candidato);
    const eleito = state.eleitos.has(c.sq_candidato);
    const segundoTurno = state.segundoTurno.has(c.sq_candidato);
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
    // Cor do partido como accent do card — a mesma usada pra pintar o
    // mapa quando o candidato é líder de UF/município. Casando o visual
    // o usuário identifica "aquela cor do mapa é esse candidato".
    div.style.setProperty("--cor-partido", corPartido(c.partido));
    // Modo TV: card recebe tabindex pra receber foco via setas do controle
    if (document.body.classList.contains("is-tv")) div.tabIndex = 0;
    div.style.setProperty("--sel-cor", sel >= 0 ? PALETA[sel] : "");
    if (sel >= 0) {
      div.style.borderColor = PALETA[sel];
      div.style.boxShadow = `0 0 0 2px ${PALETA[sel]}55, 0 8px 24px rgba(0,0,0,.35)`;
    }
    const prop = statusProporcionalDe(c.sq_candidato);
    let badgeProp = "";
    if (prop) {
      // Em proporcional, "eleito" é resultado do motor QE/QP/sobras
      // sobre a foto ATUAL da apuração. Com 4% apurado o cálculo é
      // matematicamente correto mas o resultado VAI MUDAR conforme
      // chegam mais votos (QE sobe, barreiras recalculam, D'Hondt
      // redistribui sobras). Pra evitar induzir o usuário a erro,
      // só diz "ELEITO" quando >= 90% apurado — abaixo mostra
      // "LIDERANDO VAGA" (ou "VAGA PROVÁVEL") com visual mais sóbrio.
      const pctApurProp = state.ultimoSnapshot?.totais?.pct_apurado || 0;
      const alta = pctApurProp >= 90;
      const cls = {
        eleito: alta ? "badge-eleito" : "badge-liderando",
        suplente: "badge-suplente",
        nao_atingiu_barreira: "badge-barreira",
        partido_sem_vaga: "badge-sem-vaga",
      }[prop.status] || "";
      const label = {
        eleito: alta ? "✓ ELEITO" : "LIDERANDO VAGA",
        suplente: alta ? "SUPLENTE" : "SUPLENTE (parcial)",
        nao_atingiu_barreira: "S/ BARREIRA",
        partido_sem_vaga: "PARTIDO S/ VAGA",
      }[prop.status] || "";
      const fed = prop.federacao ? ` · Fed.` : "";
      const title = alta ? prop.status
                         : `${prop.status} — cálculo baseado em ${pctApurProp.toFixed(1)}% apurado; muda conforme chegam mais votos`;
      badgeProp = `<div class="badge-prop ${cls}" title="${title}">${label}${fed}</div>`;
      // Status projetado — só mostra quando difere do atual. Útil pra
      // proporcional: candidato ainda não está eleito, mas se o ritmo
      // recente continuar, estaria. Visual bem discreto.
      const sp = prop.status_projetado;
      if (sp && sp !== prop.status) {
        const labelProj = {
          eleito: "~ proj. ELEITO",
          suplente: "~ proj. suplente",
          nao_atingiu_barreira: "~ proj. s/ barreira",
          partido_sem_vaga: "~ proj. partido s/ vaga",
        }[sp] || `~ proj. ${sp}`;
        badgeProp += `<div class="badge-prop-proj" title="Projeção baseada no ritmo recente — não é resultado final">${labelProj}</div>`;
      }
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
    } else if (segundoTurno) {
      tarja = `<div class="cand-tarja tarja-segundo-turno">
        <svg width="14" height="14" aria-hidden="true"><use href="#i-bolt"/></svg>
        <span>Vai pro 2º turno</span>
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
    // Conflito de duplicata ativa no TSE: dois cadastros, mesmo (uf, nº),
    // ambos ativos. Mostramos os dois (não cabe a nós escolher), mas
    // sinalizamos pra não parecer bug.
    const conflito = state._emConflito?.has(c.sq_candidato);
    if (conflito && !retirado) {
      tarja = `<div class="cand-tarja tarja-conflito">
        <svg width="14" height="14" aria-hidden="true"><use href="#i-info"/></svg>
        <span>TSE tem 2 registros ativos neste número — só um receberá votos</span>
      </div>` + tarja;
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
        <button type="button" class="cand-check-vazio" data-comparar="${c.sq_candidato}" aria-label="${sel >= 0 ? 'Remover da comparação' : 'Adicionar à comparação'}" aria-pressed="${sel >= 0 ? 'true' : 'false'}"></button>
      </div>
      <div class="cand-metricas">
        <div class="cand-pct" data-sq-pct="${c.sq_candidato}">0,00%<span class="cand-pct-sub"> dos válidos</span></div>
        <div class="cand-linha-inf">
          <span class="cand-votos" data-sq="${c.sq_candidato}">0 votos</span>
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
    frag.appendChild(div);
  }
  // PERF: um único reflow em vez de N
  el.appendChild(frag);
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
  // PERF: cascata é O(n) de reflow + animation handles. Com >30 cards
  // (Dep Fed SP = 70+, SP Dep Est = 94+) trava celular mediano por
  // 1-2s. Acima desse corte entramos sem animação — card aparece
  // instantâneo mas tudo responde.
  const LIMITE_CASCATA = 30;
  if (primeiraVez || conjuntoMudou) {
    if (cards.length <= LIMITE_CASCATA) anexarEntradaCascata(cards);
    el.dataset.jaRenderizou = "1";
    el.dataset.sqsRenderizados = sqsNovos;
  } else {
    flip.commit();
  }
  // Ripple é caro em listas grandes (adiciona pointer listeners).
  // Também corta no mesmo limite — card ainda clica, só sem efeito ripple.
  if (cards.length <= LIMITE_CASCATA) {
    el.querySelectorAll(".cand-acao").forEach(addRipple);
    cards.forEach(addRipple);
  }
  // CRÍTICO: todo renderLista reconstrói innerHTML com "0 votos"
  // placeholder. SEMPRE re-preencher via atualizarPainelTotais logo
  // depois — senão interações do usuário (buscar, filtrar partido,
  // reordenar, selecionar comparar) zeram os votos até o próximo WS.
  // atualizarPainelTotais é no-op se state.ultimoSnapshot ainda não
  // existe (branch early-return no topo da função).
  if (state.ultimoSnapshot?.disponivel) {
    atualizarPainelTotais();
  }
  // Pagination controls — só quando há mais que 1 página
  const paginadorExistente = document.getElementById("paginador-lista");
  if (paginadorExistente) paginadorExistente.remove();
  if (temPaginacao && totalPaginas > 1) {
    const p = document.createElement("nav");
    p.id = "paginador-lista";
    p.className = "paginador";
    p.setAttribute("aria-label", "Páginas da lista de candidatos");
    const btnPrev = pagina > 1
      ? `<button type="button" class="pag-btn" data-pag="${pagina - 1}" aria-label="Página anterior">← anterior</button>`
      : `<span class="pag-btn pag-off">← anterior</span>`;
    const btnNext = pagina < totalPaginas
      ? `<button type="button" class="pag-btn" data-pag="${pagina + 1}" aria-label="Próxima página">próxima →</button>`
      : `<span class="pag-btn pag-off">próxima →</span>`;
    // Números individuais (max 5 visíveis + ...): sempre mostra 1,
    // final, atual-1, atual, atual+1. Preenche com ellipsis quando pula.
    const nums = [];
    const visiveis = new Set([1, totalPaginas, pagina - 1, pagina, pagina + 1]
      .filter(n => n >= 1 && n <= totalPaginas));
    let last = 0;
    [...visiveis].sort((a, b) => a - b).forEach(n => {
      if (n - last > 1) nums.push(`<span class="pag-ellipsis">…</span>`);
      nums.push(n === pagina
        ? `<span class="pag-btn pag-atual" aria-current="page">${n}</span>`
        : `<button type="button" class="pag-btn" data-pag="${n}">${n}</button>`);
      last = n;
    });
    p.innerHTML = `
      ${btnPrev}
      <div class="pag-nums">${nums.join("")}</div>
      ${btnNext}
      <div class="pag-info">Página <b>${pagina}</b> de <b>${totalPaginas}</b> · ${filtrados.length} candidatos</div>
    `;
    p.querySelectorAll(".pag-btn[data-pag]").forEach(b => {
      b.addEventListener("click", () => {
        state.paginaAtual = Number(b.dataset.pag);
        renderLista();
        // Volta scroll pro topo da lista pra ver os cards da página nova
        document.getElementById("lista-candidatos")?.scrollIntoView(
          { behavior: "smooth", block: "start" });
      });
    });
    el.after(p);
  }
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
  // Mobile: user tá na aba "comparar" quando clica no X. Esconder só
  // .comparacao deixa a página preta (tabs de m-tab-comparar escondem
  // tudo que não é .comparacao). Volta pra aba "placar" automaticamente.
  if (document.body.classList.contains("m-tab-comparar")) {
    trocarTabMobile("placar");
  }
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
    hist = await get(`/api/apuracao/historico?cargo=${state.cargo}&abrangencia=${state.abrangencia}&candidatos=${sqs}&turno=${state.turno}`);
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

  // Margem matemática contra os OUTROS SELECIONADOS.
  // Pra 2 candidatos as duas linhas são paralelas (mesmo `restantes`
  // global desloca ambas), virariam ruído visual. Então:
  //   - 2 selecionados → UMA linha: margem do LÍDER entre eles
  //     (positivo = líder já tem mais que o pior cenário do outro).
  //   - 3+ selecionados → uma linha POR candidato (líder relativo
  //     dentro do grupo).
  // Importante: "venceu/perdeu" aqui é só CONTRA O GRUPO SELECIONADO,
  // não a eleição toda (em Pres 1T pode ter outros candidatos fora
  // do grupo). Rotulamos "lidera/atrás no confronto" pra evitar
  // confusão com vitória matemática real da urna.
  const tempoDeTudo = new Set();
  for (const sq of state.selecionados) {
    for (const p of (hist.series[sq] || [])) tempoDeTudo.add(p.t);
  }
  const histMap = {};
  for (const sq of state.selecionados) {
    histMap[sq] = new Map((hist.series[sq] || []).map(p => [p.t, p]));
  }

  let seriesFinal;
  if (state.selecionados.length === 2) {
    // Uma linha só: margem do líder dinâmico (quem tiver mais votos naquele t)
    const [A, B] = state.selecionados;
    const dados = [];
    for (const t of [...tempoDeTudo].sort()) {
      const pA = histMap[A].get(t), pB = histMap[B].get(t);
      if (!pA || !pB) continue;
      const [lider, segundo] = pA.votos >= pB.votos ? [pA, pB] : [pB, pA];
      const nomeLider = pA.votos >= pB.votos ? nomes[0] : nomes[1];
      const margem = lider.votos - (segundo.votos + (segundo.restantes_max || 0));
      dados.push([t, margem, nomeLider]);
    }
    seriesFinal = [{
      name: "margem do líder no confronto", type: "line", smooth: true, showSymbol: false,
      data: dados.map(([t, m]) => [t, m]),
      _rotulosLider: dados.map(([_, __, n]) => n),
      lineStyle: { width: 2.5, color: "#f0b429" },
      areaStyle: {
        opacity: 0.22,
        color: {
          type: "linear", x: 0, y: 0, x2: 0, y2: 1,
          colorStops: [
            { offset: 0, color: "rgba(34,197,94,0.5)" },
            { offset: 0.5, color: "rgba(240,180,41,0.3)" },
            { offset: 1, color: "rgba(239,68,68,0.4)" },
          ],
        },
      },
      markLine: {
        symbol: "none", silent: true,
        data: [{
          yAxis: 0,
          label: { formatter: "fronteira do confronto", color: "#f0b429", fontSize: 10, position: "end" },
          lineStyle: { color: "#f0b429", type: "dashed", width: 1.5 },
        }],
      },
    }];
  } else {
    // 3+ selecionados: margem_i vs max_outros_selecionados
    const seriesPorSq = {};
    for (const sq of state.selecionados) {
      seriesPorSq[sq] = [];
      const outros = state.selecionados.filter(x => x !== sq).map(x => histMap[x]);
      for (const [t, pMeu] of histMap[sq].entries()) {
        let tetoMax = 0, temOutro = false;
        for (const outro of outros) {
          const po = outro.get(t);
          if (!po) continue;
          temOutro = true;
          const teto = (po.votos || 0) + (po.restantes_max || 0);
          if (teto > tetoMax) tetoMax = teto;
        }
        if (!temOutro) continue;
        seriesPorSq[sq].push([t, (pMeu.votos || 0) - tetoMax]);
      }
    }
    seriesFinal = state.selecionados.map((sq, i) => ({
      name: `margem de ${nomes[i]}`, type: "line", smooth: true, showSymbol: false,
      data: seriesPorSq[sq],
      lineStyle: { width: 2.5, color: PALETA[i] },
      areaStyle: { opacity: 0.08, color: PALETA[i] },
      markLine: i === 0 ? {
        symbol: "none", silent: true,
        data: [{
          yAxis: 0,
          label: { formatter: "fronteira do confronto", color: "#f0b429", fontSize: 10, position: "end" },
          lineStyle: { color: "#f0b429", type: "dashed", width: 1.5 },
        }],
      } : undefined,
    }));
  }

  const rotuloMargem = (v, pctApurFinal) => {
    if (v >= 0) return `<b style="color:#22c55e">+${fmtNum(v)}</b> ${pctApurFinal ? "(venceu o confronto)" : "(lidera no confronto)"}`;
    if (pctApurFinal) return `<span style="color:#f87171">${fmtNum(v)}</span> (perdeu o confronto)`;
    return `<span style="color:#f0b429">${fmtNum(v)}</span> (ainda alcançável)`;
  };
  const pctApurFinal = (state.ultimoSnapshot?.totais?.pct_apurado || 0) >= 99.995;

  graf("graf-banda").setOption({
    ...baseOpts(),
    legend: {
      show: state.selecionados.length > 2,
      textStyle: { color: "#c8d0dc", fontSize: 11 },
      top: 2,
    },
    tooltip: { trigger: "axis",
      formatter: (params) => {
        const data = new Date(params[0].value[0]).toLocaleString("pt-BR");
        const linhas = params.map(p => {
          const v = p.value[1];
          let nome = p.seriesName;
          if (state.selecionados.length === 2 && seriesFinal[0]._rotulosLider) {
            const dsIdx = seriesFinal[0].data.findIndex(d => d[0] === p.value[0]);
            if (dsIdx >= 0) nome = `líder: ${seriesFinal[0]._rotulosLider[dsIdx]}`;
          }
          return `${p.marker} ${nome}: ${rotuloMargem(v, pctApurFinal)}`;
        }).join("<br>");
        return `${data}<br>${linhas}`;
      } },
    series: seriesFinal,
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
  // PERF: antes fazia 4 × N querySelectors globais no documento. Agora
  // escaneia a lista UMA vez e indexa por sq pros 4 campos. Em Dep Est
  // SP (94 candidatos × 4 queries = 376 scans do DOM) ia 50-200ms;
  // agora é 1 pass de ~5ms.
  const listaEl = document.getElementById("lista-candidatos");
  const idx = { votos: {}, pct: {}, barra: {}, delta: {} };
  if (listaEl) {
    listaEl.querySelectorAll("[data-sq]").forEach(el => { idx.votos[el.dataset.sq] = el; });
    listaEl.querySelectorAll("[data-sq-pct]").forEach(el => { idx.pct[el.dataset.sqPct] = el; });
    listaEl.querySelectorAll("[data-sq-barra]").forEach(el => { idx.barra[el.dataset.sqBarra] = el; });
    listaEl.querySelectorAll("[data-sq-delta]").forEach(el => { idx.delta[el.dataset.sqDelta] = el; });
  }
  dados.candidatos.forEach(c => {
    const votos = idx.votos[c.sq_candidato];
    const pct = idx.pct[c.sq_candidato];
    const barra = idx.barra[c.sq_candidato];
    const delta = idx.delta[c.sq_candidato];
    if (votos) {
      // Agora votos vira texto secundário ("1.234.567 votos"), com %
      // promovido pro número principal. animarNumero recebe só o número,
      // o " votos" entra via dataset pra não re-renderizar.
      animarNumero(votos, c.votos, 400, " votos");
    }
    if (pct) {
      const pctApur = dados.totais?.pct_apurado || 0;
      // Projeção como FAIXA (votos e %, quando disponível):
      //   - L = linear: votos_atual × secoes_total ÷ secoes_apuradas
      //   - T = janela móvel: usa o ritmo das últimas 15 snapshots
      // Convergem → número único. Divergem → faixa reflete incerteza real.
      // Projeção % só nos majoritários (Presidente, Governador, Senador).
      // Em proporcional (Dep. Fed/Est) % individual não decide eleição —
      // é o cálculo proporcional (QE/QP/sobras) que define a vaga.
      const L = c.projecao_linear, T = c.projecao_tendencia;
      const Tp = c.projecao_pct_tendencia;  // só vem pra majoritários
      const mostra = pctApur >= 30 && pctApur < 100 && L;
      let projTxt = "";
      if (mostra) {
        // Votos: faixa L↔T quando divergem
        const vTxt = (T != null && T !== L)
          ? `${fmtNum(Math.min(L, T))}–${fmtNum(Math.max(L, T))}`
          : fmtNum(L);
        // Pct: faixa pct_atual↔Tp quando Tp existe E diverge do pct atual
        let pTxt = "";
        if (Tp != null) {
          const pAtual = c.pct_validos;
          const diff = Math.abs(Tp - pAtual);
          pTxt = diff >= 0.1
            ? ` · ${Math.min(pAtual, Tp).toFixed(1)}–${Math.max(pAtual, Tp).toFixed(1)}%`
            : ` · ${pAtual.toFixed(1)}%`;
        }
        projTxt = ` · ~ ${vTxt}${pTxt} proj.`;
      }
      const tooltip = "Projeção aritmética — faixa entre extrapolação linear e "
        + "janela móvel das últimas 15 atualizações. Não considera composição "
        + "regional das urnas faltantes. Projeção de % só em cargos majoritários. "
        + "Some ao atingir 100%.";
      // % passou a ser o número hero do card. Formato:
      //   48,50<span class="cand-pct-sub"> dos válidos</span>
      // Visual: 48,50 é o grande (herda font-size do .cand-pct), "dos
      // válidos" é cinza/pequeno via .cand-pct-sub.
      pct.innerHTML = `${c.pct_validos.toFixed(2)}%<span class="cand-pct-sub"> dos válidos</span>`
        + (projTxt ? `<span class="cand-proj" title="${tooltip}">${projTxt}</span>` : "");
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
      const r = await fetch(`/api/apuracao/lideres-por-uf?cargo=${state.cargo}&turno=${state.turno}`);
      if (r.ok) {
        const j = await r.json();
        for (const [uf, d] of Object.entries(j.ufs || {})) {
          const partidoNum = state.ficha?.[d.sq_candidato]?.partido;
          dadosPorUF[uf] = {
            valor: d.votos || 0,
            cor: corDoCandidato(d.sq_candidato, d.cor_idx),
            partido_sigla: partidoNum ? siglaDoPartido(partidoNum) : "",
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
  async function _puxarLideresMun() {
    const r = await fetch(`/api/apuracao/lideres-por-municipio?cargo=${state.cargo}&uf=${state.abrangencia}&turno=${state.turno}`);
    if (!r.ok) return {};
    const j = await r.json();
    return j.municipios || {};
  }
  try {
    let mun = await _puxarLideresMun();
    // Vazio = TSE não envia breakdown de município nos JSONs de UF
    // (confirmado em 05/10/2026 pra todos os cargos). Dispara lazy
    // populate que puxa cada município direto do TSE em paralelo e
    // persiste. Cacheado 15 min server-side. Primeira abertura leva
    // ~5-15s; subsequentes ficam instantâneas.
    if (Object.keys(mun).length === 0) {
      renderLegenda(leg, {}, {
        tituloVazio: `Carregando municípios de ${state.abrangencia}…`,
        tituloCheio: "", dica: "Puxando dados direto do TSE em paralelo. Pode levar alguns segundos.",
      });
      try {
        await fetch(`/api/apuracao/popular-municipios?cargo=${state.cargo}&uf=${state.abrangencia}&turno=${state.turno}`, { method: "POST" });
        mun = await _puxarLideresMun();
      } catch (e) {}
    }
    for (const [codMun, d] of Object.entries(mun)) {
      dadosPorMun[codMun] = {
        valor: d.votos || 0,
        cor: corDoCandidato(d.sq_candidato, d.cor_idx),
        nome_lider: d.nome_lider,
        votos: d.votos,
      };
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

// ============ Gráfico único da home ============
let _grafHome = null;
async function atualizarGrafHome() {
  const container = $("graf-home");
  const vazio = $("home-graf-vazio");
  if (!container) return;
  const snap = state.ultimoSnapshot;
  const pctApur = snap?.totais?.pct_apurado || 0;
  // Antes de 1% apurado, não há dados reais ainda
  if (!snap?.disponivel || pctApur < 0.5) {
    vazio?.classList.remove("oculto");
    if (_grafHome) { _grafHome.clear(); }
    return;
  }
  // Top N do snapshot (só ativos, não retirados — já ordenados por posicao).
  // No mobile, 3 em vez de 5 — legenda com 5 nomes atropela o eixo Y
  // em viewports estreitos.
  const topN = window.innerWidth < 640 ? 3 : 5;
  const topSqs = (snap.candidatos || [])
    .filter(c => (state.ficha[c.sq_candidato]?.situacao || "ativo") === "ativo")
    .slice(0, topN)
    .map(c => c.sq_candidato);
  if (!topSqs.length) {
    vazio?.classList.remove("oculto");
    return;
  }
  let data;
  try {
    const r = await fetch(`/api/apuracao/historico?cargo=${state.cargo}&abrangencia=${state.abrangencia}&candidatos=${topSqs.join(",")}&turno=${state.turno}`);
    if (!r.ok) throw 0;
    data = await r.json();
  } catch (e) {
    vazio?.classList.remove("oculto");
    return;
  }
  const temDados = Object.values(data.series || {}).some(a => a.length > 1);
  if (!temDados) {
    vazio?.classList.remove("oculto");
    return;
  }
  vazio?.classList.add("oculto");
  if (!_grafHome) {
    _grafHome = echarts.init(container, null, { renderer: "canvas" });
    // ECharts captura width/height no init(). Se o container tava escondido
    // (aba Mapa inativa, modo TV toggled, etc.) o canvas nasce com tamanho
    // 0 e nunca cresce sozinho. ResizeObserver corrige automaticamente
    // quando o layout do pai estabiliza — resolve "gráfico só ocupa 50%
    // da tela" e "TV mostra só até 18h30" (chart não refez quando a
    // janela mudou).
    if (window.ResizeObserver) {
      const ro = new ResizeObserver(() => {
        try { _grafHome?.resize(); } catch(e) {}
      });
      ro.observe(container);
    }
    window.addEventListener("resize", () => {
      try { _grafHome?.resize(); } catch(e) {}
    });
  } else {
    // Já existe — garante que está no tamanho certo antes de redesenhar
    try { _grafHome.resize(); } catch(e) {}
  }
  const series = topSqs.map(sq => {
    const ficha = state.ficha[sq] || {};
    const nome = ficha.nome_urna || sq;
    const cor = ficha.partido != null ? corDoPartido(ficha.partido) : "#f0b429";
    return {
      name: nome, type: "line", smooth: true, symbol: "none",
      lineStyle: { width: 2.5, color: cor },
      itemStyle: { color: cor },
      data: (data.series[sq] || []).map(p => [p.t, p.pct]),
    };
  });
  // Layout responsivo. Mobile: legenda em cima (top:4) MAIS COMPACTA
  // em uma linha. Grid com top:28 e bottom:28 pra dar área grande ao
  // plot. Antes virava "listra" porque bottom:44 + containLabel comia
  // metade da altura disponível.
  const estreito = window.innerWidth < 640;
  _grafHome.setOption({
    backgroundColor: "transparent",
    tooltip: { trigger: "axis", formatter: tooltipHoraBRT,
                backgroundColor: "#161b24", borderColor: "#303a4d",
                textStyle: { color: "#ecf0f7" } },
    legend: estreito
      ? { textStyle: { color: "#94a1b8", fontSize: 10 }, top: 4,
          type: "scroll", icon: "circle", itemGap: 10,
          itemWidth: 10, itemHeight: 10, pageIconSize: 10,
          pageTextStyle: { color: "#94a1b8", fontSize: 9 } }
      : { textStyle: { color: "#94a1b8" }, top: 0, type: "scroll" },
    grid: estreito
      ? { left: 44, right: 14, top: 28, bottom: 24 }
      : { left: 48, right: 16, top: 36, bottom: 32 },
    xAxis: {
      type: "time",
      axisLabel: {
        color: "#94a1b8",
        fontSize: estreito ? 9 : 12,
        hideOverlap: true,
        formatter: (val) => new Date(val).toLocaleTimeString("pt-BR",
          { timeZone: TZ, hour: "2-digit", minute: "2-digit" }),
      },
    },
    yAxis: {
      type: "value",
      axisLabel: { color: "#94a1b8", fontSize: estreito ? 10 : 12,
                   formatter: "{value}%" },
      splitLine: { lineStyle: { color: "#2a3242" } },
    },
    series,
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
  //
  // IGNORA eventos majoritários em cargos proporcionais (Dep Fed=6, Dep
  // Est=7). O motor matemático foi corrigido pra não emitir mais esses
  // eventos pra proporcional, mas o banco pode ter eventos antigos
  // acumulados do bug 05/10/2026 (candidato com AMBAS tarjas verde eleito
  // + vermelha "sem chance"). Pra proporcional, quem está eleito ou sem
  // chance vem do cálculo QE/QP/sobras em state.proporcional.
  if (state.cargo === 6 || state.cargo === 7) {
    return;
  }
  if (ev.tipo === "MATEMATICAMENTE_ELIMINADO" && ev.sq_candidato_a) {
    state.eliminados.add(ev.sq_candidato_a);
  } else if ((ev.tipo === "ELEITO_1T" || ev.tipo === "ELEITO_MAJORITARIO")
             && ev.sq_candidato_a) {
    state.eleitos.add(ev.sq_candidato_a);
  } else if (ev.tipo === "SEGUNDO_TURNO_DEFINIDO") {
    if (ev.sq_candidato_a) state.segundoTurno.add(ev.sq_candidato_a);
    if (ev.sq_candidato_b) state.segundoTurno.add(ev.sq_candidato_b);
  }
}

async function carregarEventos() {
  let evs = [];
  try { evs = await get(`/api/eventos?cargo=${state.cargo}&abrangencia=${state.abrangencia}&turno=${state.turno}`); } catch (e) {}
  // Reseta os sets — cargo/UF podem ter mudado e temos que zerar
  state.eliminados.clear();
  state.eleitos.clear();
  state.segundoTurno.clear();
  evs.forEach(_absorverEventoNoState);
  // Faixa persistente de "VENCEDOR" quando o usuário navega pra um cargo
  // já decidido: diferente do modal (one-shot ao vivo), fica no topo da
  // página enquanto a disputa estiver resolvida.
  renderFaixaVencedor(evs);
  renderNotaContexto();
  // CRÍTICO: re-renderiza os cards agora que state.eleitos/eliminados/
  // segundoTurno estão populados. SEM atualizarPainelTotais na sequência,
  // os votos ficam zerados: renderLista() reconstrói templates com
  // "0 votos" placeholder e nada preenche depois. Bug 20:18 BRT em dia
  // D — a cada snapshot com eventos novos, cards voltavam a 0.
  if (document.getElementById("lista-candidatos")?.children.length) {
    renderLista();
    // Re-aplica votos imediatamente — senão fica tudo em 0 até o próximo
    // snapshot (que também vai zerar antes de preencher). atualizarPainelTotais
    // lê de state.ultimoSnapshot (já populado) e usa querySelector
    // [data-sq=...], então é no-op se não tiver dados ainda.
    if (state.ultimoSnapshot?.disponivel) atualizarPainelTotais();
  }
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
    const novo = await get(`/api/apuracao/atual?cargo=${state.cargo}&abrangencia=${state.abrangencia}&turno=${state.turno}`);
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
      const p = await get(`/api/apuracao/proporcional?cargo=${state.cargo}&uf=${state.abrangencia}&turno=${state.turno}`);
      if (p.disponivel) state.proporcional = p;
    } catch (e) { /* sem dados ainda */ }
  }
  // ORDEM IMPORTA: renderLista() faz `el.innerHTML = ""` e reconstrói
  // os cards a partir do template (que vem com "0 votos" placeholder).
  // Então ele PRECISA rodar antes de atualizarPainelTotais, que é quem
  // preenche os votos de verdade via querySelector `[data-sq=...]`.
  // Até 05/10/2026 estava invertido — votos apareciam por 1ms e eram
  // sobrescritos pelo renderLista a cada ciclo. Bug invisível em
  // pré-apuração (todo mundo com 0 mesmo), explodiu quando TSE começou
  // a publicar números reais no dia D.
  renderLista();
  atualizarPainelTotais();
  atualizarPainelProporcional();
  atualizarTituloAba(state.ultimoSnapshot);
  // Countdown só aparece enquanto TSE não publica dados de verdade
  if (!state.ultimoSnapshot?.disponivel) atualizarContagemRegressiva();
  else { const c = $("countdown"); if (c) c.classList.add("oculto"); }
  if (state.selecionados.length >= 2 && !$("comparacao").classList.contains("oculto")) {
    atualizarComparacao();
  }
  // Mapa + gráfico casam com o snapshot. Antes só o WS puxava eles,
  // então quem abria a página depois do início da apuração via a lista
  // atualizar mas o mapa continuava cinza até chegar um snapshot NOVO
  // pelo WS (podia demorar minutos). Agora refresh já sincroniza tudo.
  if (state.ultimoSnapshot?.disponivel) {
    try { atualizarMapa(); } catch(e) {}
    try { atualizarGrafHome(); } catch(e) {}
    try { atualizarPlacar2T(); } catch(e) {}
  }
}

// Placar extra do modo TV 2T: diferença absoluta, barra de split
// proporcional, tendência (quem está subindo), progresso de apuração,
// e UFs lideradas por cada candidato. Noop fora de TV 2T.
async function atualizarPlacar2T() {
  if (!document.body.classList.contains("is-tv") || state.turno !== 2) return;
  const snap = state.ultimoSnapshot;
  if (!snap?.disponivel || !snap.candidatos?.length) return;
  const ativos = snap.candidatos
    .filter(c => (state.ficha[c.sq_candidato]?.situacao || "ativo") === "ativo")
    .sort((a, b) => b.votos - a.votos);
  if (ativos.length < 2) return;
  const [a, b] = ativos;
  const corA = corDoCandidato(a.sq_candidato);
  const corB = corDoCandidato(b.sq_candidato);
  // Diferença absoluta + em pontos percentuais
  const diffVotos = a.votos - b.votos;
  const diffPct = a.pct_validos - b.pct_validos;
  const diffNumEl = document.getElementById("tv2t-diff-num");
  const diffPctEl = document.getElementById("tv2t-diff-pct");
  if (diffNumEl) diffNumEl.textContent = fmtNum(diffVotos);
  if (diffPctEl) diffPctEl.textContent = `${diffPct.toFixed(2)} pontos`;
  // Spread bar: % de A e % de B proporcional. Com 0 votos (pré-apuração)
  // 50/50 fica visualmente mentiroso — mostramos barra neutra "aguardando".
  const total = a.pct_validos + b.pct_validos;
  const spreadA = document.getElementById("tv2t-spread-a");
  const spreadB = document.getElementById("tv2t-spread-b");
  const spreadWrap = document.getElementById("tv2t-spread");
  if (total <= 0) {
    if (spreadWrap) {
      spreadWrap.classList.add("tv2t-spread-vazio");
      spreadWrap.setAttribute("data-aguardando", "Aguardando apuração");
    }
    if (spreadA) { spreadA.style.flexBasis = "50%"; spreadA.style.background = "transparent"; spreadA.textContent = ""; }
    if (spreadB) { spreadB.style.flexBasis = "50%"; spreadB.style.background = "transparent"; spreadB.textContent = ""; }
  } else {
    if (spreadWrap) { spreadWrap.classList.remove("tv2t-spread-vazio"); spreadWrap.removeAttribute("data-aguardando"); }
    const flexA = (a.pct_validos / total * 100);
    const flexB = 100 - flexA;
    if (spreadA) {
      spreadA.style.flexBasis = flexA + "%";
      spreadA.style.setProperty("--cor-a", corA);
      spreadA.style.background = corA;
      spreadA.textContent = `${a.pct_validos.toFixed(1)}%`;
    }
    if (spreadB) {
      spreadB.style.flexBasis = flexB + "%";
      spreadB.style.setProperty("--cor-b", corB);
      spreadB.style.background = corB;
      spreadB.textContent = `${b.pct_validos.toFixed(1)}%`;
    }
  }
  // Tendência: compara com snapshot anterior pra ver se o líder tá
  // puxando ou perdendo gás. Delta de pct_validos > 0 = subindo.
  const ant = state.snapshotAnterior?.candidatos?.find(c => c.sq_candidato === a.sq_candidato);
  const tendEl = document.getElementById("tv2t-tend-num");
  if (tendEl) {
    if (!ant) {
      tendEl.textContent = "—";
      tendEl.className = "tv2t-tend-num estavel";
    } else {
      const deltaPct = a.pct_validos - ant.pct_validos;
      if (Math.abs(deltaPct) < 0.01) {
        tendEl.textContent = "estável";
        tendEl.className = "tv2t-tend-num estavel";
      } else {
        tendEl.textContent = (deltaPct > 0 ? "▲ " : "▼ ") + Math.abs(deltaPct).toFixed(2);
        tendEl.className = "tv2t-tend-num " + (deltaPct > 0 ? "subindo" : "caindo");
      }
    }
  }
  // Progresso de apuração
  const t = snap.totais || {};
  const pctApur = t.pct_apurado || 0;
  const fill = document.getElementById("tv2t-progresso-fill");
  const lab = document.getElementById("tv2t-progresso-lab");
  if (fill) fill.style.width = Math.min(100, pctApur) + "%";
  if (lab) lab.textContent = `${pctApur.toFixed(2)}% apurado · ${fmtNum(t.secoes_totalizadas || 0)} de ${fmtNum(t.secoes_total || 0)} seções`;
  // UFs lideradas (só Pres BR) — para Governador 2T uf-específico
  // o conceito não faz sentido, então mostra municípios liderados.
  const colA = document.getElementById("tv2t-ufs-a");
  const colB = document.getElementById("tv2t-ufs-b");
  if (!colA || !colB) return;
  colA.innerHTML = "";
  colB.innerHTML = "";
  if (state.cargo === 1 && state.abrangencia === "BR") {
    try {
      const r = await fetch(`/api/apuracao/lideres-por-uf?cargo=1&turno=${state.turno}`);
      if (r.ok) {
        const j = await r.json();
        const ufs = j.ufs || {};
        for (const [uf, info] of Object.entries(ufs)) {
          const pill = document.createElement("span");
          pill.className = "tv2t-uf-pill";
          pill.style.background = corDoCandidato(info.sq_candidato, info.cor_idx);
          pill.innerHTML = `${uf} <small>${fmtNum(info.votos || 0)}</small>`;
          if (info.sq_candidato === a.sq_candidato) colA.appendChild(pill);
          else if (info.sq_candidato === b.sq_candidato) colB.appendChild(pill);
        }
      }
    } catch(e) { /* silencia */ }
  }
  // Props aria pros leitores de tela
  document.getElementById("tv2t-placar")?.setAttribute("aria-hidden", "false");
  document.getElementById("tv2t-ufs")?.setAttribute("aria-hidden", "false");
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
  const ws = new WebSocket(`${proto}//${location.host}/ws/apuracao?cargo=${state.cargo}&abrangencia=${state.abrangencia}&turno=${state.turno}`);
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
      atualizarGrafHome();
      if (state.selecionados.length >= 2) await inicializarGraficos();
      for (const ev of msg.eventos || []) {
        _absorverEventoNoState(ev);
        const nome = state.ficha[ev.sq_candidato_a]?.nome_urna || ev.sq_candidato_a;
        const num = state.ficha[ev.sq_candidato_a]?.partido;
        const cor = num ? corDoPartido(num) : "#f0b429";
        if (ev.tipo === "ELEITO_1T" || ev.tipo === "ELEITO_MAJORITARIO") {
          comemorar(nome, cor);
          abrirModalVitoria(ev.sq_candidato_a, cor);
          toast(`${nome} eleito(a)!`, "ok");
        } else if (ev.tipo === "SEGUNDO_TURNO_DEFINIDO") {
          toast(`2º turno matematicamente definido`, "ok");
          // Nova UF com 2T de Gov → refresca o dropdown pra ela aparecer
          carregarUfsGov2T().then(() => ajustarUFParaCargo());
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
  state.paginaAtual = 1;  // reset paginação ao trocar cargo/UF
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
  atualizarGrafHome();
  conectarWS();
}

// ============ UX: contagem regressiva pro dia D ============
function atualizarContagemRegressiva() {
  const el = $("countdown");
  if (!el) return;
  // Qual DIA D exibir depende do turno escolhido no header
  const alvo = state.turno === 2 ? DIA_D_2T : DIA_D;
  const titulo = state.turno === 2 ? "2º turno começa em" : "Apuração começa em";
  const dataStr = state.turno === 2 ? "· 26/10 17h BRT" : "· 4/10 17h BRT";
  const diff = alvo.getTime() - Date.now();
  if (diff <= 0) { el.classList.add("oculto"); return; }
  const dias = Math.floor(diff / 86_400_000);
  const horas = Math.floor((diff % 86_400_000) / 3_600_000);
  const min = Math.floor((diff % 3_600_000) / 60_000);
  const seg = Math.floor((diff % 60_000) / 1000);
  el.classList.remove("oculto");
  el.innerHTML = `
    <svg class="cd-icone" width="14" height="14"><use href="#i-hourglass"/></svg>
    <span class="cd-titulo">${titulo}</span>
    <span class="cd-nums">
      <b>${String(dias).padStart(2,"0")}</b>d
      <b>${String(horas).padStart(2,"0")}</b>h
      <b>${String(min).padStart(2,"0")}</b>m
      <b>${String(seg).padStart(2,"0")}</b>s
    </span>
    <span class="cd-sub">${dataStr}</span>
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

// Notas de contexto pra disputas com história atípica (cassação pós-apuração,
// mudança jurisprudencial no meio do pleito, etc). Data-driven pra facilitar
// adicionar casos novos sem mexer no fluxo principal.
const NOTAS_CONTEXTO = [
  {
    cargo: 3, uf: "RJ", turno: 1,
    titulo: "Decisão atípica — cassação pós-apuração",
    corpo: "A disputa pelo Governo do RJ só ficou decidida no 1º turno depois do TSE julgar a cassação de ANTHONY GAROTINHO (REP 10) em 09/10/2026. Durante a apuração, ele estava com registro INDEFERIDO em prazo recursal — pela Lei 9.504 art. 16-A, votos a candidato sub judice contam como válidos enquanto roda o recurso. Com os 274.411 votos dele dentro: líder tinha 49,27% → iria pro 2T. Com a cassação mantida, esses votos viraram NULOS (Lei 9.504 art. 175 §3º) → denominador caiu de 8.669.038 pra 8.394.627 → DOUGLAS RUAS passou pra 50,88% → eleito no 1º turno.",
    link: "https://www.tse.jus.br/comunicacao/noticias/",
  },
];

function renderNotaContexto() {
  const prev = document.getElementById("nota-contexto");
  if (prev) prev.remove();
  const nota = NOTAS_CONTEXTO.find(n =>
    n.cargo === state.cargo &&
    n.uf === state.abrangencia &&
    (n.turno == null || n.turno === state.turno)
  );
  if (!nota) return;
  // Honra o dismiss persistido por nota
  const dismissKey = `nota-contexto-dismiss:${nota.cargo}-${nota.uf}-${nota.turno || "any"}`;
  if (localStorage.getItem(dismissKey) === "1") return;
  const el = document.createElement("div");
  el.id = "nota-contexto";
  el.className = "nota-contexto";
  el.setAttribute("role", "note");
  el.innerHTML = `
    <svg class="nc-ico" width="20" height="20" aria-hidden="true"><use href="#i-help"/></svg>
    <div class="nc-corpo">
      <div class="nc-titulo">${nota.titulo}</div>
      <div class="nc-texto">${nota.corpo}${nota.link ? ` <a href="${nota.link}" target="_blank" rel="noopener">Saiba mais ↗</a>` : ""}</div>
    </div>
    <button class="nc-fechar" aria-label="Fechar nota" title="Fechar">✕</button>
  `;
  el.querySelector(".nc-fechar").onclick = () => {
    try { localStorage.setItem(dismissKey, "1"); } catch(e) {}
    el.remove();
  };
  const main = document.querySelector("main.page");
  if (main) main.insertBefore(el, main.firstChild);
}

// Faixa fixa no topo "VENCEDOR: fulano" quando a disputa já foi
// matematicamente decidida. Some sozinha se o cargo/UF muda pra um
// que ainda não decidiu.
function renderFaixaVencedor(eventos) {
  const prev = document.getElementById("faixa-vencedor");
  if (prev) prev.remove();
  if (state.cargo === 6 || state.cargo === 7) return;  // proporcional não tem "o vencedor"
  const eleito = (eventos || []).find(e =>
    (e.tipo === "ELEITO_1T" || e.tipo === "ELEITO_MAJORITARIO") && e.sq_candidato_a
  );
  if (!eleito) return;
  const ficha = state.ficha[eleito.sq_candidato_a] || {};
  const nome = ficha.nome_urna || "Vencedor(a)";
  const partido = ficha.partido || "";
  const cor = partido ? corDoPartido(partido) : "#10b981";
  const cargoNome = { 1: "Presidente", 3: "Governador(a)", 5: "Senador(a)" }[state.cargo] || "";
  const abr = state.abrangencia === "BR" ? "do Brasil" : `de ${state.abrangencia}`;
  const faixa = document.createElement("div");
  faixa.id = "faixa-vencedor";
  faixa.className = "faixa-vencedor";
  faixa.style.setProperty("--cor-vencedor", cor);
  faixa.innerHTML = `
    <svg class="fv-ico" width="22" height="22" aria-hidden="true"><use href="#i-trophy"/></svg>
    <span class="fv-lab">VENCEDOR</span>
    <span class="fv-nome">${nome}</span>
    <span class="fv-cargo">${cargoNome} ${abr}</span>
  `;
  const main = document.querySelector("main.page");
  if (main) main.insertBefore(faixa, main.firstChild);
}

// ============ UX: troféu grande + confete ao eleger ============
// Mostra MODAL DE VITÓRIA ocupando a tela inteira com foto, nome do
// candidato, cargo + abrangência e % final. Fica até o usuário fechar
// ou 25s. Dispara apenas pra ELEITO_* no cargo/abrangência que a pessoa
// está acompanhando (WS já é canal-based, então garantido).
function abrirModalVitoria(sq_candidato, cor = "#f0b429") {
  const ficha = state.ficha[sq_candidato] || {};
  const nome = ficha.nome_urna || "Vencedor(a)";
  const foto = ficha.foto_url;
  const partido = ficha.partido || "";
  const numero = ficha.numero || "";
  const lider = (state.ultimoSnapshot?.candidatos || []).find(c => c.sq_candidato === sq_candidato);
  const pct = lider ? `${lider.pct_validos.toFixed(2)}%` : "";
  const cargoNome = { 1: "Presidente da República", 3: "Governador(a)", 5: "Senador(a)",
                      6: "Deputado(a) Federal", 7: "Deputado(a) Estadual" }[state.cargo] || "";
  const abr = state.abrangencia === "BR" ? "do Brasil" : `de ${state.abrangencia}`;

  // Remove modal anterior se houver
  document.querySelectorAll(".modal-vitoria").forEach(el => el.remove());

  const modal = document.createElement("div");
  modal.className = "modal-vitoria";
  modal.setAttribute("role", "dialog");
  modal.setAttribute("aria-modal", "true");
  modal.setAttribute("aria-label", `${nome} eleito ${cargoNome}`);
  modal.style.setProperty("--cor-vencedor", cor);
  modal.innerHTML = `
    <div class="mv-back"></div>
    <div class="mv-card">
      <button class="mv-fechar" aria-label="Fechar">✕</button>
      <div class="mv-trofeu" aria-hidden="true">
        <svg width="72" height="72"><use href="#i-trophy"/></svg>
      </div>
      <div class="mv-selo">VENCEDOR</div>
      ${foto ? `<img class="mv-foto" src="${foto}" alt="" onerror="this.style.display='none'">` : ""}
      <div class="mv-nome">${nome}</div>
      <div class="mv-partido">${numero ? numero + " · " : ""}${partido}</div>
      <div class="mv-cargo">${cargoNome} ${abr}</div>
      ${pct ? `<div class="mv-pct"><span class="mv-pct-num">${pct}</span><span class="mv-pct-lab">dos votos válidos</span></div>` : ""}
      <div class="mv-sub">Matematicamente eleito(a)</div>
      <button class="mv-ok">Continuar acompanhando</button>
    </div>
  `;
  document.body.appendChild(modal);

  const fechar = () => {
    modal.classList.add("saindo");
    setTimeout(() => modal.remove(), 400);
  };
  modal.querySelector(".mv-fechar").onclick = fechar;
  modal.querySelector(".mv-ok").onclick = fechar;
  modal.querySelector(".mv-back").onclick = fechar;
  const onKey = (e) => { if (e.key === "Escape") { fechar(); document.removeEventListener("keydown", onKey); } };
  document.addEventListener("keydown", onKey);
  setTimeout(fechar, 25000);
}

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
  if (p.has("turno")) {
    const t = +p.get("turno");
    if (t === 1 || t === 2) state.turno = t;
  }
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

  // Chip Cargo → bottom sheet. Em 2T só mostra Pres e Gov (único com 2T).
  $("m-chip-cargo")?.addEventListener("click", () => {
    const permitidos = new Set(CARGOS_POR_TURNO[state.turno] || CARGOS_POR_TURNO[1]);
    abrirBottomSheet("Escolher cargo",
      Object.entries(NOMES_CARGO)
        .filter(([k]) => permitidos.has(+k))
        .map(([k, v]) => ({
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
  // Toggle 1T / 2T no header
  document.querySelectorAll(".turno-btn").forEach(b => {
    b.addEventListener("click", () => trocarTurno(Number(b.dataset.turno)));
  });
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
      state.paginaAtual = 1;  // reset pra ver resultado desde a 1ª página
      salvarPrefs();
      renderLista();
    }, 150);
  });
  $("filtro-partido").addEventListener("change", (e) => {
    state.filtro.partido = e.target.value;
    state.paginaAtual = 1;
    salvarPrefs();
    renderLista();
  });
  $("ordenar").addEventListener("change", (e) => {
    state.filtro.ordenar = e.target.value;
    state.paginaAtual = 1;
    salvarPrefs();
    renderLista();
  });

  // Link do bot do Telegram — só aparece quando backend confirma que
  // TELEGRAM_BOT_TOKEN está setado.
  try {
    const cfg = await get("/api/config-publica");
    if (cfg?.telegram_bot) {
      const url = `https://t.me/${cfg.telegram_bot}`;
      for (const id of ["btn-telegram", "m-btn-telegram"]) {
        const a = $(id);
        if (a) {
          a.href = url;
          a.classList.remove("oculto");
        }
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
  _sincronizarClasseTurno();
  // Em modo TV + turno 2 (layout drasticamente diferente), força
  // ECharts a redimensionar quando o DOM estabilizar.
  requestAnimationFrame(() => {
    setTimeout(() => window.dispatchEvent(new Event("resize")), 200);
  });
  // Ripple em botões desktop também (não só mobile — QA reclamou de
  // "não vi animação"). Aplica em botões que já existem no DOM inicial.
  document.querySelectorAll(".btn-ghost, .btn-primary, .d-topnav-link").forEach(addRipple);

  iniciarRelogio();
  aplicarEstadoDaURL();
  // Reflete no <select> antes do primeiro carregamento. ajustarUFParaCargo
  // pode mudar state.abrangencia (ex.: cargo=5 obriga UF, muda BR→SP), então
  // só sincronizamos os selects DEPOIS dele pra evitar valor desatualizado.
  const selCargo = $("sel-cargo"); if (selCargo) selCargo.value = state.cargo;
  await carregarUfsGov2T();  // antes do ajustarUFParaCargo pra já esconder as sem 2T no primeiro paint
  ajustarUFParaCargo();
  const selUF = $("sel-uf"); if (selUF) selUF.value = state.abrangencia;
  // Restaura filtros nos inputs (localStorage → UI). filtro.texto é
  // sempre resetado em carregarPrefs — campo de busca abre vazio.
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
  atualizarGrafHome();
  conectarWS();
  bootMobile();
  navTVPorSetas();  // só ativa se body.is-tv
  document.getElementById("btn-tv")?.addEventListener("click", alternarModoTV);
  atualizarBotaoTV();
}

boot().catch(e => { console.error(e); toast("Erro: " + e.message, "danger"); });
