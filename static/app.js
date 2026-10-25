import { renderMapa } from "/static/mapa-br.js?v=20261023e";
import { corDoPartido, siglaDoPartido, badgePartidoHtml, urlLogoPartido } from "/static/partidos.js?v=20261022a";

// Dados ao vivo nunca vêm do cache do navegador. A API manda
// "max-age=3, stale-while-revalidate=15" (bom pra proxies), e com isso o
// navegador podia devolver a resposta ANTERIOR quando o aviso de dado novo
// chegava: o site ficava um ciclo atrasado (no começo, "preso" em 0%).
// "no-cache" obriga a buscar de novo a cada pedido.
{
  const _fetch = window.fetch.bind(window);
  window.fetch = (input, init = {}) => {
    const url = typeof input === "string" ? input : input?.url || "";
    const metodo = (init.method || "GET").toUpperCase();
    if (metodo === "GET" && /^\/api\/|^https?:\/\/[^/]*\/api\//.test(url.replace(location.origin, "")) && !init.cache) {
      init = { ...init, cache: "no-cache" };
    }
    return _fetch(input, init);
  };
}

// Hora certa. O relógio do aparelho pode estar segundos fora (TVs
// principalmente), e duas telas lado a lado mostravam segundos diferentes.
// Mede a diferença para o servidor, sincronizado por NTP, e usa agora() em
// tudo que mostra hora ou conta tempo até um horário. Várias medidas, fica
// a de ida e volta mais rápida (erro máximo = metade dela).
let _desvioRelogio = 0;
function agora() { return Date.now() + _desvioRelogio; }
async function sincronizarHora() {
  let melhor = null;
  for (let i = 0; i < 4; i++) {
    try {
      const t0 = Date.now();
      const r = await fetch("/api/hora", { cache: "no-store" });
      const t1 = Date.now();
      const { agora_ms } = await r.json();
      if (!melhor || t1 - t0 < melhor.ida) melhor = { ida: t1 - t0, desvio: agora_ms - (t0 + t1) / 2 };
    } catch (e) { /* segue com o relógio do aparelho */ }
  }
  if (melhor && melhor.ida < 3000) _desvioRelogio = Math.round(melhor.desvio);
}
sincronizarHora();
setInterval(sincronizarHora, 10 * 60_000);

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

// Cor do i-ésimo selecionado nos gráficos de comparação: a do partido
// (igual ao card e ao mapa); se dois selecionados forem do mesmo partido,
// o segundo cai na paleta pra não ficarem idênticos.
function corSel(i) {
  const sqs = state.selecionados;
  const cor = corDoCandidato(sqs[i], i);
  const repetida = sqs.slice(0, i).some((sq, j) => corDoCandidato(sq, j) === cor);
  return repetida ? PALETA[i % PALETA.length] : cor;
}

const PALETA = ["#f0b429", "#3b82f6", "#ec4899", "#10b981", "#a855f7", "#f97316"];
const TZ = "America/Sao_Paulo";
const MAX_SEL = 4;
// Início oficial da apuração 2026: domingo, 4/10/2026 às 17h de Brasília.
// Eleições Gerais 2026 — primeiro domingo de outubro, art. 1º da Lei 9.504/97.
// 17h BRT = fechamento das urnas e início da apuração.
const DIA_D = new Date("2026-10-04T17:00:00-03:00");
// 2º turno 2026: 25/10/2026 (último domingo de outubro), 17h BRT.
// (26/10 é segunda — eleição é sempre no último domingo do mês.)
const DIA_D_2T = new Date("2026-10-25T17:00:00-03:00");
const TITULO_BASE = "Apuração 2026 · Brasil";

// Default do turno: depois do fechamento do 1T (04/10 17h BRT), o site
// vira a cara pro 2T automaticamente. Antes de 04/10 = 1T (pré-apuração);
// a partir de 05/10 = 2T (foco principal do site). User pode trocar
// manualmente via toggle no header.
function _turnoPadrao() {
  // Depois de 05/10/2026 00h BRT (dia seguinte ao 1T), default = 2
  const CORTE = new Date("2026-10-05T00:00:00-03:00");
  return agora() >= CORTE.getTime() ? 2 : 1;
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
function ehCelular() {
  return matchMedia("(pointer: coarse)").matches
    && Math.min(screen.width, screen.height) < 600;
}
function detectarTV() {
  try {
    const forcado = new URLSearchParams(location.search).get("tv");
    if (forcado === "1") return true;
    if (forcado === "0") return false;
    // Preferência manual salva (botão no rodapé). Precede detecção de UA
    // — útil quando o navegador da TV se identifica como mobile (caso
    // comum em Android TV com browsers de terceiros).
    const salvo = localStorage.getItem(TV_KEY);
    // Celular: modo TV ligado sem querer ficava salvo e prendia a pessoa
    // nele a cada abertura. Em tela de celular a preferência salva não vale.
    if (salvo === "1" && ehCelular()) { localStorage.setItem(TV_KEY, "0"); return false; }
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
  if (ativar && ehCelular()) {
    toast("O modo TV é para TV ou computador. No celular, use o placar normal.", "warn");
    return;
  }
  document.body.classList.toggle("is-tv", ativar);
  // O botão sempre prometeu "TV" — agora entra em tela cheia de verdade.
  if (ativar) entrarTelaCheia();
  else { sairTelaCheia(); try { localStorage.removeItem(FS_KEY); } catch (e) {} }
  try { aplicarQuadroTV(); } catch (e) { console.error(e); }
  // Ao entrar, busca já as outras disputas para o letreiro.
  if (ativar) atualizarResumo2T().then(() => { try { aplicarQuadroTV(); } catch (e) {} });
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
      // Placar e projeção da TV 2T só renderizam com body.is-tv — sem isso
      // ficavam "0% apurado · 0 de 0 seções" até o próximo snapshot.
      try { atualizarPlacar2T(); } catch(e) {}
      try { renderProjecaoTV(); } catch(e) {}
      try { renderProjecaoPainel(); } catch(e) {}
      try { renderDuelo(); } catch(e) {}
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
  // Modo TV sem tela cheia (voltou de um recarregamento, ou a pessoa
  // apertou Esc): botão pra voltar à tela cheia com um clique.
  const fs = document.getElementById("btn-tela-cheia");
  if (fs) fs.hidden = !ativo || !!document.fullscreenElement
    || !(document.documentElement.requestFullscreen || document.documentElement.webkitRequestFullscreen);
}
document.addEventListener("fullscreenchange", () => atualizarBotaoTV());

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
// Um só tique por segundo para tudo que mostra hora (relógio e contagens
// regressivas): todos mudam juntos, logo depois da virada do segundo. Cada
// tique reagenda pelo relógio do aparelho, porque setInterval escorrega
// alguns milissegundos por minuto e intervalos separados ficavam defasados
// entre si (o segundo do relógio e o da contagem mudavam em momentos diferentes).
const _porSegundo = [];
function aCadaSegundo(fn) { _porSegundo.push(fn); }
(function tique() {
  for (const fn of _porSegundo) { try { fn(); } catch (e) { console.error(e); } }
  setTimeout(tique, 1000 - (agora() % 1000) + 5);
})();
// Tempo que falta em dias/horas/min/s, arredondando os segundos para cima:
// às 16:59:50 faltam 10 s para as 17:00:00, não 9 (o relógio e a contagem
// precisam fechar a conta juntos).
function partesAte(diff) {
  const t = Math.ceil(diff / 1000);
  return { d: Math.floor(t / 86400), h: Math.floor(t % 86400 / 3600), m: Math.floor(t % 3600 / 60), s: t % 60 };
}
function tickRelogio() {
  const el = document.getElementById("relogio-brt");
  if (!el) return;
  el.textContent = _fmtRelogio.format(new Date(agora()));
  el.setAttribute("datetime", new Date(agora()).toISOString());
  const q = document.getElementById("tvq-relogio");
  if (q) q.innerHTML = `${el.textContent}<small>BRT</small>`;
}
function iniciarRelogio() {
  tickRelogio();
  // Alinha pra começar no próximo segundo cheio pra o relógio não
  // flutuar com drift de hundreds-of-ms. Depois intervalo fixo de 1s.
  // No mesmo tique, o "há X" do último dado (quando o TSE gerou o
  // boletim, que pode estar minutos atrás da hora atual).
  aCadaSegundo(tickRelogio);
  aCadaSegundo(tickUltimoRelativo);
}

// ============ Contraste de cores de partido como TEXTO ============
// Cores oficiais (ex.: azul-escuro PL #1e3a8a) somem no fundo escuro:
// 1,66:1. Mistura com branco o mínimo necessário pra atingir 4,5:1
// (WCAG AA). Barras/bordas seguem com a cor original.
function _lum(hex) {
  const h = hex.replace("#", "");
  const n = h.length === 3 ? h.split("").map(x => x + x).join("") : h;
  return [0, 2, 4].map(i => parseInt(n.slice(i, i + 2), 16) / 255)
    .map(c => c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4)
    .reduce((acc, c, i) => acc + c * [0.2126, 0.7152, 0.0722][i], 0);
}
function _contraste(a, b) {
  const [l1, l2] = [_lum(a), _lum(b)].sort((x, y) => y - x);
  return (l1 + 0.05) / (l2 + 0.05);
}
const _cacheCorLegivel = new Map();
function corLegivel(cor, fundo = "#161b24", alvo = 4.5) {
  if (!/^#([0-9a-f]{3}|[0-9a-f]{6})$/i.test(cor || "")) return cor;
  const k = cor + fundo;
  if (_cacheCorLegivel.has(k)) return _cacheCorLegivel.get(k);
  const h = cor.length === 4 ? "#" + cor.slice(1).split("").map(x => x + x).join("") : cor;
  const rgb = [1, 3, 5].map(i => parseInt(h.slice(i, i + 2), 16));
  let out = h;
  for (let t = 0; t <= 1.0001 && _contraste(out, fundo) < alvo; t += 0.05) {
    out = "#" + rgb.map(c => Math.round(c + (255 - c) * t).toString(16).padStart(2, "0")).join("");
  }
  _cacheCorLegivel.set(k, out);
  return out;
}

// ============ Projeção estatística do 2T ============
function cargoComProjecao2T() {
  return state.turno === 2 &&
    ((state.cargo === 1 && state.abrangencia === "BR") || state.cargo === 3);
}
function projecaoAplicavel() {
  // Com alguém matematicamente eleito a estimativa não acrescenta nada
  // (e um "x% de chance" ao lado de "ELEITO" confunde): some.
  const decidido = (state.ultimoSnapshot?.candidatos || []).some(c => state.eleitos.has(c.sq_candidato));
  return cargoComProjecao2T() && !decidido;
}
// Decimal com vírgula (pt-BR). Ponto fica só como separador de milhar
// (fmtNum) — "70.05%" ao lado de "313.655 seções" lia como milhar.
const dec = (x, n = 2) => Number(x).toFixed(n).replace(".", ",");
const fmtPct1 = (x) => `${dec(x, 1)}%`;
// Nunca "100%" de chance: o modelo é estatístico; certeza só vem da
// decisão matemática (evento ELEITO), que a UI mostra à parte.
// Só o número, para a TV: nunca "100%" nem "0%" (estimativa não é certeza).
function chanceCurta(p) {
  return p >= 0.99 ? ">99%" : p <= 0.01 ? "<1%" : `${Math.round(p * 100)}%`;
}
function textoChance(p) {
  if (p >= 0.99) return ">99% de chance de vencer";
  if (p <= 0.01) return "<1% de chance de vencer";
  return `${Math.round(p * 100)}% de chance de vencer`;
}

// "há N s/min/h" relativo a agora. Null em menos de 2s pra não piscar
// "há 0s". `tsIso` pode ser null → retorna null (chamador decide o texto).
function tempoRelativo(tsIso) {
  if (!tsIso) return null;
  const d = new Date(tsIso);
  if (isNaN(d.getTime())) return null;
  const diffS = Math.round((agora() - d.getTime()) / 1000);
  if (diffS < 2) return "agora";
  if (diffS < 60) return `há ${diffS}s`;
  if (diffS < 3600) return `há ${Math.round(diffS / 60)} min`;
  if (diffS < 86400) return `há ${Math.round(diffS / 3600)} h`;
  const dias = Math.round(diffS / 86400);
  return `há ${dias} ${dias === 1 ? "dia" : "dias"}`;
}

// Classifica staleness por idade (seg). Thresholds alinhados ao intervalo
// real do poller (default 20s): até 1 min = fresh; até 5 min = warn;
// mais que isso = stale. Usado pra pintar o indicador do "último dado".
function classeStaleness(tsIso) {
  if (!tsIso) return "stale-sem";
  const diffS = (agora() - new Date(tsIso).getTime()) / 1000;
  if (diffS < 60) return "stale-fresh";
  if (diffS < 300) return "stale-warn";
  return "stale-stale";
}

// ============ Painel de status da coleta (pré-apuração) ============
// Pré-apuração sem o bloco do duelo (ex.: cargo sem 2T definido): diz
// quando começa e se o site está conectado ao TSE.
let _statusColetaCache = null;
let _statusColetaTimer = null;

async function renderPainelStatusColeta() {
  const grid = document.getElementById("status-coleta-grid");
  const tit = document.getElementById("status-coleta-titulo");
  const dot = document.getElementById("status-dot");
  const rodape = document.getElementById("status-coleta-rodape");
  if (!grid || !tit) return;
  let s;
  try {
    s = await get("/api/poller-status");
    _statusColetaCache = s;
  } catch (e) {
    s = _statusColetaCache || null;
  }
  if (!s) {
    tit.textContent = "Não foi possível checar o status";
    dot.className = "status-dot stale-sem";
    grid.innerHTML = "";
    rodape.textContent = "Tente recarregar a página.";
    return;
  }
  const ultimoIso = s.ultimo_ciclo_em || null;
  const intervalo = s.intervalo_s || 20;
  const diffUltimo = ultimoIso ? (agora() - new Date(ultimoIso).getTime()) / 1000 : null;
  const alvos = s.alvos_total || 0;
  const falhas = s.ultimo?.falhas || 0;

  // Linguagem pra qualquer pessoa: o que importa é QUANDO começa e se o
  // site está conectado. Detalhes técnicos do poller ficam em /verificacao.
  let estado, textoConexao;
  if (alvos === 0) {
    estado = "stale-sem";
    textoConexao = "";
  } else if (diffUltimo != null && diffUltimo <= intervalo * 3 && falhas === 0) {
    estado = "stale-fresh";
    textoConexao = "Conectado ao TSE";
  } else if (diffUltimo == null) {
    estado = "stale-sem";
    textoConexao = "Conectando ao TSE…";
  } else {
    estado = "stale-warn";
    textoConexao = "Conexão com o TSE instável, tentando de novo";
  }
  const diaD = state.turno === 2 ? DIA_D_2T : DIA_D;
  const nomeTurno = state.turno === 2 ? "do 2º turno" : "do 1º turno";
  if (agora() < diaD.getTime()) {
    const dataTxt = diaD.toLocaleDateString("pt-BR", { timeZone: TZ, weekday: "long", day: "2-digit", month: "2-digit" });
    const horaTxt = diaD.toLocaleTimeString("pt-BR", { timeZone: TZ, hour: "2-digit", minute: "2-digit" });
    tit.textContent = `A apuração ${nomeTurno} começa ${dataTxt}, às ${horaTxt}`;
  } else {
    tit.textContent = "A apuração vai começar em instantes";
  }
  dot.className = "status-dot " + estado;
  grid.innerHTML = "";
  // Linha de conexão só quando diz algo útil (conectado / instável).
  rodape.innerHTML = textoConexao ? `<span class="status-dot-inline ${estado}"></span> ${textoConexao}` : "";

  // Auto-refresh a cada 30s enquanto o painel estiver visível
  if (_statusColetaTimer) clearTimeout(_statusColetaTimer);
  _statusColetaTimer = setTimeout(() => {
    if (document.getElementById("status-coleta")?.offsetParent) renderPainelStatusColeta();
  }, 30000);
}

function tickUltimoRelativo() {
  const el = document.getElementById("ultimo-rel");
  if (!el) return;
  const iso = document.getElementById("ultimo")?.dataset?.iso;
  if (!iso) { el.textContent = "—"; return; }
  const txt = tempoRelativo(iso);
  if (txt) {
    el.textContent = txt;
    const parent = el.closest(".stat-ultimo");
    if (parent) {
      // Cor de atraso só faz sentido com a apuração ANDANDO. Antes dela o
      // arquivo do TSE é de dias atrás (normal) e depois de 100% ele não
      // muda mais — vermelho nesses casos só assusta.
      const pct = state.ultimoSnapshot?.totais?.pct_apurado || 0;
      const andando = pct > 0 && pct < 100;
      parent.classList.remove("stale-fresh", "stale-warn", "stale-stale", "stale-sem");
      parent.classList.add(andando ? classeStaleness(iso) : "stale-sem");
    }
  }
  // Quadro da TV: "TSE 20:41:58 · há 15 s", com a mesma cor de atraso.
  const q = document.getElementById("tvq-tse");
  if (q && document.body.classList.contains("tv-quadro")) {
    const pct = state.ultimoSnapshot?.totais?.pct_apurado || 0;
    const andando = pct > 0 && pct < 100;
    q.innerHTML = `<span>Dado TSE</span><strong>${fmtHora(iso)}</strong>`
      + (andando && txt ? `<em>${txt}</em>` : "");
    q.className = "tvq-tse " + (andando ? classeStaleness(iso) : "stale-sem");
    // Selo do alto: "AO VIVO" só quando está mesmo chegando dado. Parado
    // há 5 min ou mais, ou sem conexão com o site, vira aviso âmbar legível
    // de longe (o "há 12 min" pequeno ao lado não se via a 3 metros).
    const vivo = document.getElementById("tvq-vivo");
    if (vivo) {
      const minParado = (agora() - new Date(iso).getTime()) / 60000;
      const semConexao = (state.ws && state.ws.readyState !== 1)
        || (state.erroApiEm && Date.now() - state.erroApiEm < 60_000);
      let txt = "AO VIVO";
      if (andando && minParado >= 5) txt = `Sem dado novo do TSE há ${minParado < 120 ? `${Math.floor(minParado)} min` : `${Math.floor(minParado / 60)} h`}`;
      else if (semConexao) txt = "Reconectando…";
      if (vivo.textContent !== txt) vivo.textContent = txt;
      vivo.classList.toggle("parado", txt !== "AO VIVO");
    }
  }
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
      // fresco: ignora o cache do navegador (as rotas /api/apuracao mandam
      // max-age=3 + stale-while-revalidate=15). Usado quando o WS avisa que
      // chegou boletim novo: sem isso a tela podia mostrar o anterior.
      const r = await fetch(url, opts.fresco ? { cache: "no-store" } : undefined);
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
    state._ufsGov2T = null;  // falha ≠ "nenhuma UF com 2T"
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
  state.projecao = null;
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
  // Busca/filtro/ordenação só atrapalham com poucos nomes (2T tem 2).
  document.querySelector(".filtro-lista")?.classList.toggle("oculto", (state.candidatos || []).length <= 4);
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
      // Contexto diferente — 2T é em 25/10/2026 e normalmente só define
      // os candidatos depois que o 1T fecha matematicamente.
      // O sistema sabe qual UF tem 2T de governador (eventos do 1T): diz
      // o motivo exato em vez de "ou isso, ou aquilo".
      const uf = state.abrangencia;
      const decidida1T = state.cargo === 3 && Array.isArray(state._ufsGov2T) && !state._ufsGov2T.includes(uf);
      const titulo = decidida1T ? `${uf} decidiu o governo no 1º turno` : "Candidatos do 2º turno ainda não publicados";
      const texto = decidida1T
        ? `Toque em "1º turno" no alto da página para ver quem foi eleito.`
        : `O TSE ainda não divulgou os finalistas de ${state.cargo === 3 ? uf : "presidente"}.`;
      el.innerHTML = `<div class="empty-state">
        <svg class="empty-ico" width="48" height="48"><use href="#i-clock"/></svg>
        <h3>${titulo}</h3>
        <p>${texto}</p>
      </div>`;
    } else {
      el.innerHTML = `<div class="empty-state">
        <svg class="empty-ico" width="48" height="48"><use href="#i-clock"/></svg>
        <h3>Apuração ainda não começou</h3>
        <p>Os resultados saem a partir das 17h de ${(state.turno === 2 ? DIA_D_2T : DIA_D).toLocaleDateString("pt-BR", { timeZone: TZ, weekday: "long", day: "2-digit", month: "2-digit" })}, quando as urnas fecham.</p>
      </div>`;
    }
    return;
  }
  if (filtrados.length === 0) {
    el.innerHTML = `<div class="empty-state">
      <h3>Nenhum candidato com esse filtro</h3>
      <p>Limpe a busca ou escolha "Todos os partidos".</p>
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
    div.style.setProperty("--cor-partido-txt", corLegivel(corPartido(c.partido)));
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
                         : `${prop.status}: cálculo com ${dec(pctApurProp, 1)}% apurado, muda conforme chegam votos`;
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
        badgeProp += `<div class="badge-prop-proj" title="Projeção pelo ritmo recente, não é resultado final">${labelProj}</div>`;
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
        <span>${motivo}: votos nulos por lei</span>
      </div>`;
    } else if (eleito) {
      tarja = `<div class="cand-tarja tarja-eleito">
        <svg width="14" height="14" aria-hidden="true"><use href="#i-trophy"/></svg>
        <span>Eleito(a)</span>
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
        <span>O TSE tem 2 registros ativos neste número, e só um receberá votos</span>
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
        <button type="button" class="cand-check-vazio" data-comparar="${c.sq_candidato}" tabindex="-1" aria-hidden="true"></button>
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
    $("sub-lista").innerHTML = `Votos de presidente <strong>só no estado ${abr}</strong>. O resultado que vale é o nacional.`;
  } else {
    // Instrução de comparação só quando há nomes suficientes pra escolher
    $("sub-lista").innerHTML = (state.candidatos || []).length > 4
      ? `Marque até <strong>4</strong> para comparar.` : "";
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
      ["% Válidos",       votos ? dec(votos.pct_validos, 2) + "%" : "—", "num"],
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
              <div style="font-size:11px;color:var(--muted)">${dec(c.pct_validos, 1)}%</div>
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
    div.style.borderTopColor = corPartido(c.partido);
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
    $("dif-prob").textContent = "—";
    $("dif-prob-hint").textContent = "";
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
      pctEl.textContent = dec(c.pct_validos, 2) + "%";
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
    $("dif-pct").textContent = dec((ordenados[0].pct_validos - ordenados[1].pct_validos), 2) + " pp";
    const restantes = Math.max(0, (dados.totais.eleitorado_apto || 0) - (dados.totais.eleitorado_apto_totalizado || 0));
    // Pergunta aritmética simples entre os dois mais votados da seleção:
    // a diferença cabe nos votos que ainda faltam? (teto: eleitores aptos
    // das seções não totalizadas — conservador, mesmo critério do motor).
    if (!(dados.totais.pct_apurado > 0) || ordenados[0].votos === 0) {
      $("dif-prob").textContent = "—";
      $("dif-prob-hint").textContent = "";
    } else if (restantes === 0) {
      $("dif-prob").textContent = "Não";
      $("dif-prob-hint").textContent = "Apuração encerrada";
    } else if (dif < restantes) {
      $("dif-prob").textContent = "Sim";
      $("dif-prob-hint").textContent = `Faltam até ${fmtNum(restantes)} votos; a diferença é ${fmtNum(dif)}`;
    } else {
      $("dif-prob").textContent = "Não";
      $("dif-prob-hint").textContent = `Diferença maior que os ${fmtNum(restantes)} votos que faltam`;
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

// Eixo Y de votos: "50 mi", "800 mil" — "50,000,000" (padrão do ECharts)
// era formato americano e largo demais no celular.
function fmtEixo(v) {
  const a = Math.abs(v);
  if (a >= 1e6) return `${dec(v / 1e6, a % 1e6 ? 1 : 0)} mi`;
  if (a >= 1e3) return `${dec(v / 1e3, 0)} mil`;
  return String(v);
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
        hideOverlap: true,
        // Rótulos do eixo X em BRT (HH:mm quando cabe, dd/mm HH:mm no zoom)
        formatter: (val) => {
          const d = new Date(val);
          return d.toLocaleTimeString("pt-BR", { timeZone: TZ, hour: "2-digit", minute: "2-digit" });
        },
      },
    },
    yAxis: { type: "value", axisLine: { lineStyle: { color: "#303a4d" } },
             axisLabel: { color: "#7d8899", formatter: fmtEixo },
             splitLine: { lineStyle: { color: "#1e2531" } } },
    // Mesma pilha do CSS: sem fallback, o canvas caía em serifa (Times)
    // quando a Inter não carregava.
    textStyle: { fontFamily: "Inter, system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif" },
  };
}

function graf(id) {
  if (state.graficos[id]) state.graficos[id].dispose();
  // Sem ECharts (CDN falhou, rede ruim): objeto inerte em vez de erro que
  // derrubaria o resto da comparação.
  if (typeof echarts === "undefined") return { setOption() {}, resize() {}, dispose() {} };
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
      data: dadosPor(i, "votos"), color: corSel(i), lineStyle: { width: 2.5 },
    })),
  });

  graf("graf-pct").setOption({
    ...baseOpts(),
    yAxis: { ...baseOpts().yAxis, max: 100, axisLabel: { color: "#7d8899", formatter: "{value}%" } },
    series: state.selecionados.map((sq, i) => ({
      name: nomes[i], type: "line", smooth: true, showSymbol: false,
      data: dadosPor(i, "pct"), color: corSel(i), lineStyle: { width: 2.5 },
      areaStyle: { opacity: 0.08, color: corSel(i) },
    })),
  });

  // Diferença: quem lidera AGORA menos o outro (positivo = vantagem do
  // líder). Antes era na ordem em que a pessoa marcou os cards, e o
  // gráfico podia ficar todo negativo sem dizer de quem pra quem.
  const seriesDif = [];
  if (state.selecionados.length >= 2) {
    const votosAgora = sq => state.ultimoSnapshot?.candidatos?.find(c => c.sq_candidato === sq)?.votos || 0;
    const [A, B] = state.selecionados.slice(0, 2).sort((x, y) => votosAgora(y) - votosAgora(x));
    const mA = new Map((hist.series[A] || []).map(p => [p.t, p.votos]));
    const mB = new Map((hist.series[B] || []).map(p => [p.t, p.votos]));
    for (const t of mA.keys()) if (mB.has(t)) seriesDif.push([t, mA.get(t) - mB.get(t)]);
    const tit = $("graf-dif")?.previousElementSibling;
    const nome = sq => state.ficha[sq]?.nome_urna || "—";
    if (tit) tit.textContent = `Vantagem de ${nome(A)} sobre ${nome(B)}`;
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
      lineStyle: { width: 2.5, color: corSel(i) },
      areaStyle: { opacity: 0.08, color: corSel(i) },
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
// "ao vivo" com bolinha verde só quando a conexão está aberta E a
// apuração ainda corre. Com 100% apurado (ex.: 1º turno, dias depois)
// o verde pulsando dizia que algo ainda estava mudando.
function atualizarRotuloConexao(ws = state.ws) {
  const el = $("conexao");
  if (!el) return;
  const conectado = ws?.readyState === 1;
  const encerrada = (state.ultimoSnapshot?.totais?.pct_apurado || 0) >= 100;
  el.querySelector(".dot")?.classList.toggle("on", conectado && !encerrada);
  $("conexao-label").textContent = !conectado ? "reconectando…"
    : (encerrada ? "apuração encerrada" : "ao vivo");
}

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
  $("pct-apurado").textContent = dec(t.pct_apurado, 2) + "%";
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
  // Comparecimento e abstenção do TSE contam só as seções já apuradas: a
  // porcentagem é sobre os eleitores dessas seções (como na TV), não sobre
  // o eleitorado inteiro (com 70% apurado dava "57% de comparecimento").
  const totalAptos = t.eleitorado_apto_totalizado || t.eleitorado_apto || 1;
  const pctCompar = dec((t.comparecimento / totalAptos * 100), 1);
  const pctAbst = dec((t.abstencoes / totalAptos * 100), 1);
  $("pct-comparecimento").textContent = `${pctCompar}% dos aptos já apurados`;
  $("pct-abstencoes").textContent = `${pctAbst}% dos aptos já apurados`;
  $("brancos-nulos").textContent = `${fmtNum(t.votos_brancos)} · ${fmtNum(t.votos_nulos)}`;
  // "Último dado" mostra a hora em que o TSE GEROU o arquivo (fonte da
  // verdade pro cross-check), caindo pra "coletado_em" (quando a gente
  // baixou) quando o TSE não envia gerado_em_tse. Tooltip explica
  // divergência entre níveis (BR × UF × município têm timestamps
  // distintos — é operação normal do TSE).
  const ts = dados.gerado_em_tse || dados.coletado_em;
  const el = $("ultimo");
  el.textContent = fmtHora(ts);
  atualizarRotuloConexao();
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
      // No 2T a projeção vive no painel #proj-painel (e no placar da TV).
      const mostra = !cargoComProjecao2T() && pctApur >= 30 && pctApur < 100 && L;
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
            ? ` · ${dec(Math.min(pAtual, Tp), 1)}–${dec(Math.max(pAtual, Tp), 1)}%`
            : ` · ${dec(pAtual, 1)}%`;
        }
        projTxt = ` · ~ ${vTxt}${pTxt} proj.`;
      }
      const tooltip = "Projeção aritmética: faixa entre extrapolação linear e "
        + "janela móvel das últimas 15 atualizações. Não considera composição "
        + "regional das urnas faltantes. Projeção de % só em cargos majoritários. "
        + "Some ao atingir 100%.";
      // % passou a ser o número hero do card. Formato:
      //   48,50<span class="cand-pct-sub"> dos válidos</span>
      // Visual: 48,50 é o grande (herda font-size do .cand-pct), "dos
      // válidos" é cinza/pequeno via .cand-pct-sub.
      pct.innerHTML = `${dec(c.pct_validos, 2)}%<span class="cand-pct-sub"> dos válidos</span>`
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
        state.secoesUF = j.secoes || {};
        // Quem lidera em cada estado (para o recorde de estados do eleito).
        state.lideresUF = Object.fromEntries(Object.entries(j.ufs || {})
          .filter(([uf]) => uf !== "ZZ").map(([uf, d]) => [uf, d.sq_candidato]));
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
      rotuloPartido: state.turno !== 2,
      onClickArea: (sigla) => {
        state.abrangencia = sigla;
        $("sel-uf").value = sigla;
        onFiltroChange();
      },
    });
    registrarViradasUF(dadosPorUF);
    renderLegenda(leg, dadosPorUF, {
      tituloVazio: "Mapa por UF",
      tituloCheio: "Líderes por UF", unidade: "UF",
      dica: "Sem votos apurados ainda.",
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
        tituloCheio: "", dica: "Pode levar alguns segundos.",
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
    tituloCheio: `Líderes por município (${state.abrangencia})`, unidade: "mun.",
    dica: "Sem votos apurados nos municípios ainda.",
  });
}

// ============ Gráfico único da home ============
let _grafHome = null;
// Estado vazio do gráfico: msg=null → painel de status da coleta (pré-
// apuração); msg=texto → apuração já começou mas ainda não há série.
function mostrarVazioGrafico(msg) {
  const vazio = $("home-graf-vazio");
  if (!vazio) return;
  vazio.classList.remove("oculto");
  $("home-graf-secao")?.classList.add("graf-vazio");
  const painel = $("status-coleta");
  const txt = $("home-graf-msg");
  if (painel) painel.hidden = msg != null;
  if (txt) { txt.hidden = msg == null; txt.textContent = msg || ""; }
  if (msg == null) renderPainelStatusColeta();
}
async function atualizarGrafHome() {
  const container = $("graf-home");
  const vazio = $("home-graf-vazio");
  if (!container) return;
  const snap = state.ultimoSnapshot;
  const pctApur = snap?.totais?.pct_apurado || 0;
  // Antes de 1% apurado, não há dados reais ainda. Mostra painel de
  // status da coleta no lugar do "aguardando" vago.
  if (!snap?.disponivel || pctApur < 0.5) {
    if (_grafHome) { _grafHome.clear(); }
    mostrarVazioGrafico(null);
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
    mostrarVazioGrafico("Gráfico disponível a partir da 2ª atualização da apuração.");
    return;
  }
  let data;
  try {
    const r = await fetch(`/api/apuracao/historico?cargo=${state.cargo}&abrangencia=${state.abrangencia}&candidatos=${topSqs.join(",")}&turno=${state.turno}`);
    if (!r.ok) throw 0;
    data = await r.json();
  } catch (e) {
    mostrarVazioGrafico("Gráfico disponível a partir da 2ª atualização da apuração.");
    return;
  }
  const temDados = Object.values(data.series || {}).some(a => a.length > 1);
  if (!temDados) {
    mostrarVazioGrafico("Gráfico disponível a partir da 2ª atualização da apuração.");
    return;
  }
  vazio?.classList.add("oculto");
  if (typeof echarts === "undefined") {
    mostrarVazioGrafico("Não foi possível carregar o gráfico. Verifique a conexão e recarregue a página.");
    return;
  }
  $("home-graf-secao")?.classList.remove("graf-vazio");
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
  // Quadro da TV: sem legenda (os nomes estão no placar), letras e linhas
  // na escala do quadro, linha tracejada nos 50%.
  const quadro = document.body.classList.contains("tv-quadro");
  const esc = quadro ? Math.max(0.45, Math.min(innerWidth / 1920, innerHeight / 1080)) : 1;
  if (quadro) {
    series.forEach(s => { s.lineStyle = { ...s.lineStyle, width: Math.max(2, 4 * esc) }; });
    if (series[0]) series[0].markLine = { symbol: "none", silent: true, label: { show: false },
      lineStyle: { color: "#56627a", type: "dashed", width: 1 }, data: [{ yAxis: 50 }] };
  }
  _grafHome.setOption({
    backgroundColor: "transparent",
    textStyle: { fontFamily: "Inter, system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif" },
    tooltip: { trigger: "axis", formatter: tooltipHoraBRT,
                backgroundColor: "#161b24", borderColor: "#303a4d",
                textStyle: { color: "#ecf0f7" } },
    legend: quadro ? { show: false } : estreito
      ? { textStyle: { color: "#94a1b8", fontSize: 10 }, top: 4,
          type: "scroll", icon: "circle", itemGap: 10,
          itemWidth: 10, itemHeight: 10, pageIconSize: 10,
          pageTextStyle: { color: "#94a1b8", fontSize: 9 } }
      : { textStyle: { color: "#94a1b8" }, top: 0, type: "scroll" },
    grid: quadro
      ? { left: 64 * esc, right: 18 * esc, top: 16 * esc, bottom: 34 * esc }
      : estreito
      ? { left: 44, right: 14, top: 28, bottom: 24 }
      : { left: 48, right: 16, top: 36, bottom: 32 },
    xAxis: {
      type: "time",
      axisLabel: {
        color: "#94a1b8",
        fontSize: quadro ? Math.round(17 * esc) : estreito ? 9 : 12,
        hideOverlap: true,
        formatter: (val) => new Date(val).toLocaleTimeString("pt-BR",
          { timeZone: TZ, hour: "2-digit", minute: "2-digit" }),
      },
    },
    yAxis: {
      type: "value",
      // Escala pelos dados: no 2º turno as linhas ficam perto de 50% e,
      // num eixo 0–100, viravam duas retas coladas.
      scale: true,
      axisLabel: { color: "#94a1b8", fontSize: quadro ? Math.round(17 * esc) : estreito ? 10 : 12,
                   formatter: "{value}%" },
      splitLine: { lineStyle: { color: "#2a3242" } },
    },
    series,
  }, true);  // notMerge: entrar/sair do quadro da TV não deixa sobra de opções
}

function renderLegenda(leg, dados, texto) {
  // Quantas áreas (UFs ou municípios) cada um lidera — o placar do mapa.
  const nomes = new Map();
  for (const [area, d] of Object.entries(dados)) {
    // Exterior (ZZ) não é estado: fica fora do "lidera em N estados".
    if (!d.nome_lider || area === "ZZ") continue;
    const atual = nomes.get(d.nome_lider) || { cor: d.cor, n: 0 };
    atual.n += 1;
    nomes.set(d.nome_lider, atual);
  }
  if (texto.unidade) state.contagemMapa = { unidade: texto.unidade, nomes };
  if (nomes.size) {
    const un = texto.unidade || "";
    leg.innerHTML = `<h3>${texto.tituloCheio}</h3>` +
      Array.from(nomes.entries()).sort((a, b) => b[1].n - a[1].n).map(([n, { cor, n: k }]) =>
        `<div class="leg-item"><span class="leg-cor" style="background:${cor}"></span>${n}`
        + (un ? `<span class="leg-n">${k} ${un}</span>` : "") + `</div>`
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
// Tipos de evento que declaram vencedor. ELEITO_2T é o do Presidente no
// 2º turno (Governador no 2T usa ELEITO_MAJORITARIO) — math_engine/engine.py.
const TIPOS_ELEITO = new Set(["ELEITO_1T", "ELEITO_2T", "ELEITO_MAJORITARIO"]);
const TIPOS_EVENTO = {
  ELEITO_1T:                 { label: "Eleito 1T", classe: "ok",     ico: "trophy" },
  ELEITO_2T:                 { label: "Eleito 2T", classe: "ok",     ico: "trophy" },
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
  } else if (TIPOS_ELEITO.has(ev.tipo) && ev.sq_candidato_a) {
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
  state.eventosLista = evs;
  // Vitória que a pessoa ainda não viu neste aparelho (tela estava apagada,
  // a aba foi recarregada pelo navegador, conexão caiu): troféu agora.
  for (const ev of evs) {
    if (TIPOS_ELEITO.has(ev.tipo) && celebrarSeNovo(ev)) break;
  }
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
  try { renderDuelo(); renderProjecaoPainel(); renderTVQuadro(); } catch (e) {}  // selo "eleito"
  const ul = $("lista-eventos");
  if (evs.length === 0) {
    const comecou = (state.ultimoSnapshot?.totais?.pct_apurado || 0) > 0;
    ul.innerHTML = comecou
      ? `<li class="vazio">Nenhuma virada nem decisão matemática até agora.</li>`
      : `<li class="vazio">A apuração ainda não começou.</li>`;
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
    } else if (ev.tipo === "ELEITO_2T") {
      texto = `<strong>${nome}</strong> eleito(a) no 2º turno`;
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
// Modo admin (/admin): token guardado neste navegador por 24 h. Com ele a
// estimativa e a chance aparecem desde o 1º boletim (o servidor confere o
// token). Selo fixo na tela para não confundir com o modo normal.
function modoAdmin() {
  try {
    const a = JSON.parse(localStorage.getItem("elei-es:admin") || "null");
    if (a?.token && a.ate > Date.now()) return a;
    if (a) localStorage.removeItem("elei-es:admin");
  } catch (e) {}
  return null;
}
function sairModoAdmin() {
  try { localStorage.removeItem("elei-es:admin"); } catch (e) {}
  document.getElementById("selo-admin")?.remove();
  toast("Modo admin desativado", "warn");
}
// Textos de espera da estimativa: no modo admin ela sai no 1º boletim.
function textoInicioEstimativa() {
  return modoAdmin() ? "Modo admin: começa no 1º boletim do TSE" : "Começa com 10% apurado";
}
function textoInicioChance() {
  return modoAdmin() ? "chance desde o 1º boletim (admin)" : "chance a partir de 30% apurado";
}
function seloModoAdmin() {
  const adm = modoAdmin();
  let el = document.getElementById("selo-admin");
  if (!adm) { el?.remove(); return; }
  if (!el) {
    el = document.createElement("button");
    el.id = "selo-admin"; el.className = "selo-admin"; el.type = "button";
    el.title = "Desativar o modo admin neste aparelho";
    el.addEventListener("click", () => { if (confirm("Desativar o modo admin neste aparelho?")) { sairModoAdmin(); refreshApuracao(true); } });
  }
  // Celular: no topo, ao lado do nome do site (embaixo cobria o texto).
  const marca = document.querySelector(".m-brand");
  const destino = marca && marca.offsetParent ? marca : document.body;
  if (el.parentElement !== destino) destino.appendChild(el);
  el.classList.toggle("no-topo", destino === marca);
  const h = new Date(adm.ate).toLocaleString("pt-BR", { timeZone: TZ, day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
  el.textContent = "ADM";
  el.title = `Modo admin: estimativa sem limite de %, até ${h}. Clique para desativar.`;
  el.setAttribute("aria-label", el.title);
}

async function refreshApuracao(fresco = false) {
  seloModoAdmin();
  try {
    const novo = await get(`/api/apuracao/atual?cargo=${state.cargo}&abrangencia=${state.abrangencia}&turno=${state.turno}`, { fresco });
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
    // Falha momentânea da API (deploy, banco ocupado): mantém o último placar
    // em vez de zerar a tela (a TV voltava para "a apuração começa às 17h").
    // Trocar de cargo/turno já limpa o placar antes de chamar aqui.
    if (!state.ultimoSnapshot?.disponivel) state.ultimoSnapshot = { disponivel: false };
    state.erroApiEm = Date.now();
  }
  // Se for cargo proporcional (Deputado Fed/Est) e temos UF, busca cálculo
  state.proporcional = null;
  if ((state.cargo === 6 || state.cargo === 7) && state.abrangencia !== "BR") {
    try {
      const p = await get(`/api/apuracao/proporcional?cargo=${state.cargo}&uf=${state.abrangencia}&turno=${state.turno}`);
      if (p.disponivel) state.proporcional = p;
    } catch (e) { /* sem dados ainda */ }
  }
  // Projeção estatística do 2T (estratificada por UF, com IC95 e
  // probabilidade). Só Presidente-BR e Governador; antes de 10% apurado
  // ou com 100% o backend devolve disponivel=false.
  // Abaixo de 10% o backend não projeta: nem pergunta (o quadro mostra a espera).
  // Se a busca falhar, fica a estimativa anterior (só some quando o backend
  // disser que não há). Modo admin: pergunta desde o 1º boletim.
  const adm = modoAdmin();
  const pctAgora = state.ultimoSnapshot?.totais?.pct_apurado || 0;
  if (projecaoAplicavel() && (pctAgora >= 10 || (adm && pctAgora > 0))) {
    try {
      const pj = adm
        ? await (async () => {
            const r = await fetch(`/api/apuracao/projecao?cargo=${state.cargo}&abrangencia=${state.abrangencia}&turno=2&admin=1`,
              { cache: "no-store", headers: { "X-Admin-Token": adm.token } });
            if (r.status === 401) { sairModoAdmin(); throw new Error("token"); }
            if (!r.ok) throw new Error(String(r.status));
            return r.json();
          })()
        : await get(`/api/apuracao/projecao?cargo=${state.cargo}&abrangencia=${state.abrangencia}&turno=2`, { fresco });
      state.projecao = pj.disponivel ? pj : null;
    } catch (e) { /* mantém a anterior */ }
  } else {
    state.projecao = null;
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
  try { renderProjecaoTV(); } catch(e) {}
  try { renderProjecaoPainel(); } catch(e) {}
  try { renderDuelo(); } catch(e) {}
  await atualizarRegioes(fresco);
  try { renderRegioes(); } catch(e) { console.error(e); }
  if (regioesAplicavel()) await carregarLider1T();
  try { renderRecordes(); } catch(e) { console.error(e); }
  if (quadroTVAtivo()) await atualizarResumo2T();
  try { aplicarQuadroTV(); } catch(e) { console.error(e); }
}

// Bloco "Projeção para 100%" do placar TV 2T. Mostra % projetado,
// intervalo de 95% e chance de vitória por candidato. Quem já foi
// eleito matematicamente vê "Eleito" no lugar da chance (certeza
// aritmética > estatística).
function renderProjecaoTV() {
  const box = $("tv2t-proj");
  if (!box) return;
  const snap = state.ultimoSnapshot;
  const pctApur = snap?.totais?.pct_apurado || 0;
  // Desde 0%: o quadro fica no lugar (vazio) e não "pula" aos 10%.
  const mostrar = projecaoAplicavel() && pctApur < 100;
  renderBlocoProjecao(box, $("tv2t-proj-linhas"), $("tv2t-proj-aviso"), mostrar);
}

// Mesmo bloco da TV, fora dela (computador e celular): painel acima da
// lista de candidatos. Some antes da apuração começar (não há o que
// projetar) e com 100% (resultado é oficial, não projeção).
function renderProjecaoPainel() {
  const box = $("proj-painel");
  if (!box) return;
  const snap = state.ultimoSnapshot;
  const pctApur = snap?.totais?.pct_apurado || 0;
  const mostrar = projecaoAplicavel() && pctApur < 100
    && !document.body.classList.contains("is-tv");
  renderBlocoProjecao(box, $("proj-painel-linhas"), $("proj-painel-aviso"), mostrar);
}

// % projetado ± margem (IC95) e chance de vitória por candidato. Quem já
// foi eleito matematicamente vê "Eleito" no lugar da chance (certeza
// aritmética > estatística).
// Linha "≈ 99% apurado por volta das 20h05" (math_engine/ritmo.py). Só a
// partir de 90% apurado; antes, avisa quando aparece. Alvo 99%, não 100%:
// as últimas urnas atrasam sem padrão (2022: 99% às 20h00, 100% à 0h17).
function textoHorario99() {
  const pct = state.ultimoSnapshot?.totais?.pct_apurado || 0;
  if (pct >= 99) return "";
  const iso = state.projecao?.previsao_99;
  if (iso) {
    const d = new Date(Math.round(Date.parse(iso) / 300000) * 300000);
    const [h, m] = d.toLocaleTimeString("pt-BR", { timeZone: TZ, hour: "2-digit", minute: "2-digit" }).split(":");
    return `≈ 99% apurado por volta das ${+h}h${m}`;
  }
  return pct >= 90 ? "Horário dos 99% apurado: medindo o ritmo" : "Horário dos 99% apurado: aparece com 90%";
}

// "Empate técnico": a margem de 95% da estimativa ainda inclui 50%. Mesma
// leitura das pesquisas. Numa disputa de décimos a chance pode apontar
// para um lado por boa parte da noite (teste com 2022 deslocado para
// 50,05% × 49,95%); o selo deixa claro que o resultado ainda está aberto.
function empateTecnico(pj) {
  const c = pj?.disponivel && pj.candidatos?.[0];
  return !!c && c.ic95[0] <= 50 && 50 <= c.ic95[1];
}

// Quando a estimativa discorda do placar (quem está atrás no placar é o
// favorito da estimativa), em dois níveis:
//  - 55% a 70%: "leve vantagem" (sinal cedo, sem prometer nada; em 2022
//    teria saído às 18h30, 13 min antes da virada do placar);
//  - 70% ou mais: "indica virada" (nível em que a chance se mostrou
//    confiável nos testes, metodologia §8.4).
// Abaixo de 55% é cara ou coroa: fica só "empate técnico".
function avisoViradaEstimativa(pj) {
  if (!pj?.disponivel) return null;
  const snap = state.ultimoSnapshot?.candidatos || [];
  if (snap.length < 2 || [...state.eleitos].some(sq => pj.candidatos.some(c => c.sq_candidato === sq))) return null;
  const placar = [...snap].sort((x, y) => y.votos - x.votos);
  if (placar[0].votos === placar[1].votos) return null;
  const est = [...pj.candidatos].sort((x, y) => y.pct - x.pct)[0];
  if (est.sq_candidato === placar[0].sq_candidato || est.p_vitoria == null || est.p_vitoria < 0.55) return null;
  const nome = state.ficha[est.sq_candidato]?.nome_urna || "";
  return { nome, chance: Math.round(est.p_vitoria * 100), previa: !!pj.probabilidade_previa,
    forte: est.p_vitoria >= 0.70 };
}

// "Vitória projetada": se a tendência continuar, um candidato será eleito.
// Exige a chance de vencer oficial (50% apurado ou mais, nunca a prévia)
// acima de 99% e a margem de 95% já sem incluir 50%. Nos 28 segundos turnos
// de 2018 e 2022 refeitos urna por urna, nunca apontou o vencedor errado;
// para presidente em 2022 teria saído com 90% apurado. Não é o aviso de
// eleito: esse continua só quando os votos que faltam não mudam mais nada.
function vitoriaProjetada(pj) {
  if (!pj?.disponivel || pj.probabilidade_previa || empateTecnico(pj)) return null;
  if (pj.candidatos.some(c => state.eleitos.has(c.sq_candidato))) return null;
  const c = pj.candidatos.find(x => (x.p_vitoria ?? 0) >= 0.99);
  return c ? { sq: c.sq_candidato, nome: state.ficha[c.sq_candidato]?.nome_urna || "" } : null;
}

function renderBlocoProjecao(box, linhas, aviso, mostrar) {
  if (!mostrar) { box.hidden = true; return; }
  box.hidden = false;
  const pj = state.projecao;
  if (!pj?.disponivel) {
    // Antes de 10% apurado: mesmo layout, sem número. Nunca um valor
    // inventado — só "—" e quanto falta pra começar.
    const pct = state.ultimoSnapshot?.totais?.pct_apurado || 0;
    const fin = (state.candidatos || []).filter(c => (c.situacao || "ativo") === "ativo")
      .sort((x, y) => (x.numero || 0) - (y.numero || 0));
    const quando = pct > 0
      ? `${textoInicioEstimativa()} · agora ${dec(pct, 1)}%`
      : textoInicioEstimativa();
    linhas.innerHTML = `<div class="tv2t-proj-espera">
        <span>${quando}</span>
        <span class="tv2t-proj-barra" aria-hidden="true"><span style="width:${Math.min(100, pct * 10)}%;background:var(--muted)"></span></span>
      </div>` + fin.map(c => {
        const cor = corPartido(c.partido);
        return `<div class="tv2t-proj-linha tv2t-proj-pendente" style="--cor:${cor};--cor-txt:${corLegivel(cor)}">
          <span class="tv2t-proj-nome">${c.nome_urna}</span>
          <span class="tv2t-proj-pct" aria-label="Estimativa ainda não disponível">≈ —</span>
          <span class="tv2t-proj-chance tv2t-proj-mudo">${textoInicioChance()}</span>
        </div>`;
      }).join("") + `<p class="proj-horario">${textoHorario99()}</p>`;
    aviso.textContent = "";
    return;
  }
  const ordenados = [...pj.candidatos].sort((x, y) => y.pct - x.pct);
  const vir = avisoViradaEstimativa(pj);
  const proj = vitoriaProjetada(pj);
  const empate = proj
    ? `<p class="proj-projetada"><b>Vitória projetada</b> · se a tendência continuar, <b>${proj.nome}</b> será eleito (mais de 99% de chance, não oficial). O aviso de eleito sai quando os votos que faltam não puderem mais mudar o resultado.</p>`
    : vir?.forte
    ? `<p class="proj-empate proj-virada"><b>A estimativa indica virada:</b> ${vir.nome} tem ${vir.chance}% de chance de terminar na frente${vir.previa ? " (prévia)" : ""}</p>`
    : vir
      ? `<p class="proj-empate"><b>Empate técnico</b> · a estimativa vê leve vantagem de ${vir.nome} no fim (${vir.chance}% de chance de vencer)</p>`
    : empateTecnico(pj) && !ordenados.some(c => state.eleitos.has(c.sq_candidato))
      ? `<p class="proj-empate"><b>Empate técnico</b> · o placar ainda pode virar</p>` : "";
  linhas.innerHTML = empate + ordenados.map(c => {
    const nome = state.ficha[c.sq_candidato]?.nome_urna || "—";
    const cor = corDoCandidato(c.sq_candidato);
    const margem = (c.ic95[1] - c.ic95[0]) / 2;
    let chance;
    if (state.eleitos.has(c.sq_candidato)) {
      chance = `<span class="tv2t-proj-eleito">Eleito</span>`;
    } else if (c.p_vitoria != null) {
      const w = Math.round(c.p_vitoria * 100);
      // 30–50% apurado: prévia, em cinza (só aparece com favorito ≥70%).
      const previa = pj.probabilidade_previa;
      chance = `<span class="tv2t-proj-barra${previa ? " previa" : ""}" aria-hidden="true"><span style="width:${w}%;background:${previa ? "var(--muted)" : cor}"></span></span>`
        + `<span class="tv2t-proj-chance${previa ? " tv2t-proj-previa" : ""}">${textoChance(c.p_vitoria)}${previa ? ` <em class="selo-previa">prévia</em>` : ""}</span>`;
    } else if (pj.disputa_indefinida) {
      chance = `<span class="tv2t-proj-chance tv2t-proj-mudo">disputa indefinida</span>`;
    } else {
      chance = `<span class="tv2t-proj-chance tv2t-proj-mudo">${textoInicioChance()}</span>`;
    }
    return `<div class="tv2t-proj-linha" style="--cor:${cor};--cor-txt:${corLegivel(cor)}">
      <span class="tv2t-proj-nome">${nome}</span>
      <span class="tv2t-proj-pct" aria-label="Estimativa: cerca de ${fmtPct1(c.pct)}, margem de ${dec(margem, 1)} pontos">≈${fmtPct1(c.pct)}<small> ±${dec(margem, 1)}</small></span>
      ${chance}
    </div>`;
  }).join("") + (textoHorario99() ? `<p class="proj-horario">${textoHorario99()}</p>` : "");
  aviso.textContent = pj.aviso || "";
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
  // Pré-apuração (0 votos): mostrar "—" é melhor que "0" + "0.00 pontos"
  // que pareciam dado real de empate técnico.
  const semVotos = (a.votos === 0 && b.votos === 0);
  if (diffNumEl) diffNumEl.textContent = semVotos ? "—" : fmtNum(diffVotos);
  if (diffPctEl) diffPctEl.textContent = semVotos ? "aguardando" : `${dec(diffPct, 2)} pontos`;
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
      spreadA.textContent = `${dec(a.pct_validos, 1)}%`;
    }
    if (spreadB) {
      spreadB.style.flexBasis = flexB + "%";
      spreadB.style.setProperty("--cor-b", corB);
      spreadB.style.background = corB;
      spreadB.textContent = `${dec(b.pct_validos, 1)}%`;
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
        tendEl.textContent = (deltaPct > 0 ? "▲ " : "▼ ") + dec(Math.abs(deltaPct), 2);
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
  if (lab) {
    // Estado explícito pré-apuração: "0 de 0 seções" era confuso (parecia
    // dado faltante). Agora: antes da apuração mostra "Aguardando dia D";
    // sem secoes_total mas com apuração começada: "Carregando total…".
    if (!t.secoes_total) {
      lab.textContent = pctApur > 0
        ? "Carregando total de seções…"
        : "Aguardando apuração começar";
    } else {
      lab.textContent = `${dec(pctApur, 2)}% apurado · ${fmtNum(t.secoes_totalizadas || 0)} de ${fmtNum(t.secoes_total || 0)} seções`;
    }
  }
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
  clearTimeout(state.wsTimer);
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
    state.wsJaAbriu = true;
    atualizarRotuloConexao(ws);
    state.wsRetry = 0;
    // Puxa snapshot E eventos assim que reconecta: o que aconteceu com a
    // conexão caída (tela apagada, túnel, troca de rede) aparece agora —
    // inclusive o troféu, via carregarEventos → celebrarSeNovo.
    state.ultimaMsgWs = Date.now();
    refreshApuracao().then(carregarEventos).catch(() => {});
    // Deploy derruba o WebSocket; ao reconectar é a hora de ver se o
    // front mudou.
    checarVersao();
  };
  const reconectar = () => {
    // Se o WS foi fechado intencionalmente (troca de cargo/UF),
    // NÃO reconecta — outro conectarWS já está em andamento.
    if (ws.__intencional) return;
    $("conexao").querySelector(".dot").classList.remove("on");
    $("conexao-label").textContent = "reconectando…";
    // Tela apagada/aba em segundo plano: não fica tentando (gasta bateria);
    // o "visibilitychange" reconecta na hora em que a pessoa voltar.
    if (document.hidden) return;
    // Backoff exponencial com jitter: 1s, 2s, 4s, 8s, 15s teto
    state.wsRetry = (state.wsRetry || 0) + 1;
    const base = Math.min(15000, 1000 * Math.pow(2, state.wsRetry - 1));
    const jitter = Math.floor(Math.random() * 500);
    state.wsTimer = setTimeout(conectarWS, base + jitter);
  };
  ws.onclose = reconectar;
  ws.onerror = () => { try { ws.close(); } catch(e){} };
  ws.onmessage = async (m) => {
    state.ultimaMsgWs = Date.now();
    const msg = JSON.parse(m.data);
    if (msg.type === "snapshot") {
      // Vitória: tela do eleito antes de tudo. Busca só o placar novo (os
      // números que a tela mostra) e abre; o resto da página (estimativa,
      // regiões, mapa, gráficos) atualiza logo depois, por trás dela.
      const eleitos = (msg.eventos || []).filter(ev => TIPOS_ELEITO.has(ev.tipo));
      if (eleitos.length) {
        try {
          const novo = await get(`/api/apuracao/atual?cargo=${state.cargo}&abrangencia=${state.abrangencia}&turno=${state.turno}`, { fresco: true, retries: 0 });
          if (state.ultimoSnapshot?.disponivel && state.ultimoSnapshot.coletado_em !== novo.coletado_em) {
            state.snapshotAnterior = state.ultimoSnapshot;
          }
          state.ultimoSnapshot = novo;
        } catch (e) { /* abre com o placar que já tem */ }
        for (const ev of eleitos) { _absorverEventoNoState(ev); celebrarSeNovo(ev); }
      }
      await refreshApuracao(true);
      atualizarMapa();  // sem await — não bloqueia os toasts de evento
      atualizarGrafHome();
      if (state.selecionados.length >= 2) await inicializarGraficos();
      for (const ev of msg.eventos || []) {
        _absorverEventoNoState(ev);
        const nome = state.ficha[ev.sq_candidato_a]?.nome_urna || ev.sq_candidato_a;
        const num = state.ficha[ev.sq_candidato_a]?.partido;
        const cor = num ? corDoPartido(num) : "#f0b429";
        if (TIPOS_ELEITO.has(ev.tipo)) {
          celebrarSeNovo(ev);
          notificarSistema(`${nome} eleito(a)`, `${rotuloDisputaAtual()} · os votos que faltam não mudam mais o resultado`);
        } else if (ev.tipo === "SEGUNDO_TURNO_DEFINIDO") {
          toast(`2º turno matematicamente definido`, "ok");
          // Nova UF com 2T de Gov → refresca o dropdown pra ela aparecer
          carregarUfsGov2T().then(() => ajustarUFParaCargo());
        } else if (ev.tipo === "VIRADA") {
          // Antes caía num "✓ eleito(a)" genérico — virada não é vitória.
          const b = state.ficha[ev.sq_candidato_b]?.nome_urna || ev.sq_candidato_b;
          toast(`${nome} passou ${b}`, "warn");
          notificarSistema(`${nome} passou ${b}`, `${rotuloDisputaAtual()} · virada no placar`);
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
  state.projecao = null;
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
  const dataStr = state.turno === 2 ? "· 25/10 17h BRT" : "· 4/10 17h BRT";
  const diff = alvo.getTime() - agora();
  const apurando = (state.ultimoSnapshot?.totais?.pct_apurado || 0) > 0;
  if (diff <= 0 || apurando) { el.classList.add("oculto"); return; }
  const { d: dias, h: horas, m: min, s: seg } = partesAte(diff);
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
// depois do fechamento das urnas do 2º turno — a última votação de 2026.
// Chamado no boot e também pelo tick da contagem regressiva.
function esconderColaSeFechado() {
  if (agora() < DIA_D_2T.getTime()) return;
  document.querySelectorAll(
    ".cta-brand, .m-icon-cta, .d-topnav-cta, #btn-cola-cta"
  ).forEach(el => el.classList.add("oculto"));
}

// ============ Duelo do 2º turno (antes da apuração) ============
// Antes da apuração, as 5 caixas do topo só mostravam zeros e "há 2 dias".
// O que importa nesse momento é QUEM disputa e QUANDO começa — então elas
// dão lugar a este bloco. Some sozinho quando o TSE publica o 1º voto.
function emPreApuracao() {
  const snap = state.ultimoSnapshot;
  return !snap?.disponivel || (snap.totais?.pct_apurado || 0) === 0;
}

function renderDuelo() {
  const box = $("duelo");
  if (!box) return;
  const ativos = (state.candidatos || []).filter(c => (c.situacao || "ativo") === "ativo")
    .sort((x, y) => (x.numero || 0) - (y.numero || 0));  // lados fixos, como num placar
  const ehDuelo = state.turno === 2 && ativos.length === 2 && !document.body.classList.contains("is-tv");
  const pre = ehDuelo && emPreApuracao();
  box.hidden = !ehDuelo;
  document.body.classList.toggle("pre-apuracao", pre);
  document.body.classList.toggle("duelo-vivo", ehDuelo && !pre);
  document.body.classList.toggle("duelo-2t", ehDuelo);
  if (!ehDuelo) return;
  const cargo = state.cargo === 1 ? "Presidente da República"
    : `Governador${state.abrangencia ? " · " + state.abrangencia : ""}`;
  $("duelo-tit").textContent = `2º turno · ${cargo}`;
  const card = c => {
    const cor = corPartido(c.partido);
    return `<button type="button" class="duelo-cand" data-sq="${c.sq_candidato}" style="--cor:${cor};--cor-txt:${corLegivel(cor)}" aria-label="Ficha de ${c.nome_urna}">
      <img class="duelo-foto" src="${c.foto}" alt="" decoding="async">
      <span class="duelo-nome">${c.nome_urna}</span>
      <span class="duelo-meta"><span class="cand-numero-tag">${c.numero}</span>${badgePartidoHtml(c.partido)}</span>
      <span class="duelo-pct"></span>
      <span class="duelo-votos"></span>
    </button>`;
  };
  const cands = $("duelo-cands");
  const chave = ativos.map(c => c.sq_candidato).join(",");
  if (cands.dataset.chave !== chave) {
    cands.innerHTML = card(ativos[0]) + `<span class="duelo-x" aria-hidden="true">×</span>` + card(ativos[1]);
    cands.dataset.chave = chave;
    cands.querySelectorAll(".duelo-foto").forEach((img, i) =>
      anexarFotoComRetry(img, ativos[i].nome_urna, ativos[i].partido));
    cands.querySelectorAll(".duelo-cand").forEach(b =>
      b.addEventListener("click", () => abrirModal(b.dataset.sq)));
  }
  $("duelo-placar").hidden = pre;
  if (pre) {
    const dataTxt = DIA_D_2T.toLocaleDateString("pt-BR", { timeZone: TZ, weekday: "long", day: "2-digit", month: "2-digit" });
    $("duelo-data").textContent = `${dataTxt}, às 17h (horário de Brasília)`;
    cands.querySelectorAll(".duelo-pct, .duelo-votos").forEach(el => { el.textContent = ""; });
    cands.querySelectorAll(".duelo-cand").forEach(el => el.classList.remove("lidera", "eleito"));
    tickDuelo();
    return;
  }
  // Apuração em andamento: placar ao vivo.
  const snap = state.ultimoSnapshot;
  const porSq = new Map((snap.candidatos || []).map(c => [c.sq_candidato, c]));
  const [a, b] = ativos.map(c => porSq.get(c.sq_candidato) || { votos: 0, pct_validos: 0 });
  const liderIdx = a.votos === b.votos ? -1 : (a.votos > b.votos ? 0 : 1);
  cands.querySelectorAll(".duelo-cand").forEach((el, i) => {
    const v = i === 0 ? a : b;
    el.querySelector(".duelo-pct").textContent = `${dec(v.pct_validos, 2)}%`;
    el.querySelector(".duelo-votos").textContent = `${fmtNum(v.votos)} votos`;
    el.classList.toggle("lidera", i === liderIdx);
    el.classList.toggle("eleito", state.eleitos.has(ativos[i].sq_candidato));
  });
  const total = a.pct_validos + b.pct_validos;
  const wA = total > 0 ? a.pct_validos / total * 100 : 50;
  $("duelo-barra-a").style.cssText = `flex-basis:${wA}%;background:${corPartido(ativos[0].partido)}`;
  $("duelo-barra-b").style.cssText = `flex-basis:${100 - wA}%;background:${corPartido(ativos[1].partido)}`;
  const dif = $("duelo-dif");
  if (liderIdx < 0) {
    dif.textContent = "Empate";
  } else {
    const lider = ativos[liderIdx];
    const nome = state.ficha[lider.sq_candidato]?.nome_urna || lider.nome_urna;
    const eleito = state.eleitos.has(lider.sq_candidato);
    dif.innerHTML = eleito
      ? `<strong>${nome} eleito(a)</strong> · ${fmtNum(Math.abs(a.votos - b.votos))} votos de diferença`
      : `<strong>${nome}</strong> à frente por ${fmtNum(Math.abs(a.votos - b.votos))} votos `
        + `<span class="duelo-dif-pp">(${dec(Math.abs(a.pct_validos - b.pct_validos), 2)} pontos)</span>`;
  }
  const t = snap.totais || {};
  $("duelo-apurado-fill").style.width = Math.min(100, t.pct_apurado || 0) + "%";
  const ts = snap.gerado_em_tse || snap.coletado_em;
  const hora = ts ? fmtHora(ts) : "";
  $("duelo-apurado-lab").textContent = `${dec(t.pct_apurado || 0, 2)}% apurado`
    + (t.secoes_total ? ` · ${fmtNum(t.secoes_totalizadas || 0)} de ${fmtNum(t.secoes_total)} seções` : "")
    + (hora ? ` · atualizado às ${hora}` : "");
}

// TV antes da apuração: o painel do gráfico (vazio) vira uma contagem
// regressiva grande — é o que interessa a quem olha a TV de longe.
function tickContagemTV() {
  // Fica ao lado do grid, não dentro: renderPainelStatusColeta limpa o
  // grid a cada 30s e o cronômetro sumia por um segundo.
  const box = $("status-coleta");
  if (!box || !document.body.classList.contains("is-tv")) return;
  const alvo = state.turno === 2 ? DIA_D_2T : DIA_D;
  const diff = alvo.getTime() - agora();
  if (diff <= 0 || !box.offsetParent) { box.querySelector(".tv-cd")?.remove(); return; }
  const { d, h, m, s: sg } = partesAte(diff);
  const p2 = n => String(n).padStart(2, "0");
  let el = box.querySelector(".tv-cd");
  if (!el) {
    el = document.createElement("div"); el.className = "tv-cd"; el.setAttribute("aria-hidden", "true");
    box.insertBefore(el, $("status-coleta-rodape"));
  }
  el.innerHTML = (d ? `<b>${d}</b><small>${d === 1 ? "dia" : "dias"}</small> ` : "")
    + `<b>${p2(h)}</b><small>h</small> <b>${p2(m)}</b><small>min</small> <b>${p2(sg)}</b><small>s</small>`;
}

function tickDuelo() {
  const el = $("duelo-cd");
  if (!el || $("duelo")?.hidden) return;
  const diff = DIA_D_2T.getTime() - agora();
  if (diff <= 0) {
    $("duelo-quando-lab").textContent = "As urnas fecharam.";
    el.textContent = "Apuração começando…";
    return;
  }
  const { d, h, m, s: sg } = partesAte(diff);
  const p2 = n => String(n).padStart(2, "0");
  el.innerHTML = (d ? `<b>${d}</b>${d === 1 ? " dia" : " dias"} ` : "")
    + `<b>${p2(h)}</b>h <b>${p2(m)}</b>min <b>${p2(sg)}</b>s`;
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
  const pct = dec(lider.pct_validos, 0);
  const apurado = dec(t.pct_apurado, 0);
  document.title = `${nome} ${pct}% · ${apurado}% apurado · ${TITULO_BASE}`;
}

// Notas de contexto pra disputas com história atípica (cassação pós-apuração,
// mudança jurisprudencial no meio do pleito, etc). Data-driven pra facilitar
// adicionar casos novos sem mexer no fluxo principal.
const NOTAS_CONTEXTO = [
  {
    cargo: 3, uf: "RJ", turno: 1,
    titulo: "Resultado alterado pelo TSE em 09/10",
    corpo: "Anthony Garotinho (Republicanos) concorreu com o registro sob recurso, e os votos dele contaram como válidos durante a apuração. Por isso Douglas Ruas aparecia com 49,27%, abaixo da maioria. O TSE manteve a cassação, os 274.411 votos de Garotinho foram anulados e Ruas ficou com 50,88% dos válidos: eleito no 1º turno, sem 2º turno no RJ.",
    link: "https://www.tse.jus.br/comunicacao/noticias/2026/Outubro/tse-decide-pela-retotalizacao-dos-votos-para-governador-no-rio-de-janeiro",
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
    TIPOS_ELEITO.has(e.tipo) && e.sq_candidato_a
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
// ou 10s. Dispara apenas pra ELEITO_* no cargo/abrangência que a pessoa
// está acompanhando (WS já é canal-based, então garantido).
// Vitória em tela cheia (TV, computador e celular): foto do eleito sumindo
// para a direita (no celular, para baixo) e o nome grande. A foto do TSE é
// pequena (3x4): entra como retrato alto, com uma cópia desfocada dela
// mesma preenchendo o fundo, para não esticar até pixelar. Na TV fica 30 s
// (ninguém fecha); no computador e no celular 15 s, com botão para voltar.
// Depois fica o selo ELEITO no placar e a faixa "Vencedor" no topo.
function abrirModalVitoria(sq_candidato, cor = "#f0b429") {
  const naTV = document.body.classList.contains("is-tv");
  const ficha = state.ficha[sq_candidato] || {};
  const nome = ficha.nome_urna || "Vencedor(a)";
  const snap = state.ultimoSnapshot;
  const c = (snap?.candidatos || []).find(x => x.sq_candidato === sq_candidato);
  const pctApur = snap?.totais?.pct_apurado || 0;
  const cargoNome = { 1: "Presidente da República", 3: "Governador(a)", 5: "Senador(a)",
                      6: "Deputado(a) Federal", 7: "Deputado(a) Estadual" }[state.cargo] || "";
  const onde = state.abrangencia === "BR" ? "" : ` · ${NOMES_UF_EXT[state.abrangencia] || state.abrangencia}`;
  const selo = state.turno === 2 ? "Eleito no 2º turno" : "Eleito";
  const duracao = naTV ? 30 : 15;
  document.querySelectorAll(".modal-vitoria").forEach(el => el.remove());
  const el = document.createElement("div");
  el.className = "modal-vitoria mv-tv";
  el.setAttribute("role", "dialog");
  el.setAttribute("aria-modal", "true");
  el.setAttribute("aria-label", `${nome}, ${selo.toLowerCase()}, ${cargoNome}`);
  el.style.setProperty("--cor-vencedor", cor);
  el.style.setProperty("--cor-vencedor-txt", corLegivel(cor, "#05080f"));
  el.innerHTML = `
    <div class="mvt-fundo" aria-hidden="true">${ficha.foto ? `<img class="mvt-borrao" src="${ficha.foto}" alt="">` : ""}</div>
    <div class="mvt-foto">${ficha.foto
      ? `<img class="mvt-img" src="${ficha.foto}" alt="">`
      : `<div class="mvt-img cand-foto-fallback" style="background:${cor}">${iniciais(nome)}</div>`}</div>
    <div class="mvt-texto">
      <div class="mvt-selo"><svg aria-hidden="true"><use href="#i-trophy"/></svg>${selo}</div>
      <div class="mvt-cargo">${cargoNome}${onde}</div>
      <div class="mvt-nome">${nome}</div>
      <div class="mvt-part"><span class="mvt-num">${ficha.numero || ""}</span>${siglaDoPartido(+ficha.partido) || ""}</div>
      ${c ? `<div class="mvt-pct">${dec(c.pct_validos, 2)}<small>%</small></div>
      <div class="mvt-votos">${fmtNum(c.votos)} votos · ${dec(pctApur, 1)}% apurado</div>` : ""}
      <p class="mvt-sub">Os votos que faltam não mudam mais o resultado.</p>
      ${naTV ? "" : `<button class="mv-ok mvt-ok">Continuar acompanhando</button>`}
    </div>
    <button class="mv-fechar mvt-fechar" aria-label="Voltar ao placar">✕</button>
    <div class="mv-tempo mvt-tempo" aria-hidden="true"><span style="animation-duration:${duracao}s"></span></div>`;
  document.body.appendChild(el);
  const conf = document.querySelector("body > .confete");
  if (conf) el.insertBefore(conf, el.querySelector(".mvt-texto"));
  const img = el.querySelector(".mvt-img");
  if (img?.tagName === "IMG") anexarFotoComRetry(img, nome, ficha.partido);
  el.querySelector(".mvt-borrao")?.addEventListener("error", e => e.target.remove(), { once: true });
  let fechado = false;
  const fechar = () => {
    if (fechado) return;
    fechado = true;
    document.removeEventListener("keydown", onKey);
    el.classList.add("saindo");
    setTimeout(() => el.remove(), 400);
  };
  const onKey = (e) => { if (e.key === "Escape" || (naTV && e.key === "Enter")) fechar(); };
  el.querySelector(".mvt-fechar").onclick = fechar;
  const ok = el.querySelector(".mvt-ok");
  if (ok) { ok.onclick = fechar; ok.focus({ preventScroll: true }); }
  document.addEventListener("keydown", onKey);
  setTimeout(fechar, duracao * 1000);
}

// Troféu uma vez por vitória por aparelho. Chamado tanto pelo aviso ao
// vivo (WebSocket) quanto ao recarregar os eventos — assim quem estava com
// a tela apagada vê o troféu ao voltar, e ninguém vê o mesmo troféu duas
// vezes. Vitórias com mais de 12h não disparam (quem chega no dia seguinte
// vê a faixa "Vencedor", não a comemoração).
const TROFEU_JANELA_MS = 12 * 3600 * 1000;
const _trofeusVistos = new Set();
function celebrarSeNovo(ev) {
  if (!ev?.sq_candidato_a || document.hidden) return false;  // escondido: mostra ao voltar
  if (document.querySelector(".modal-vitoria")) return false;
  const quando = ev.ocorrido_em ? Date.parse(ev.ocorrido_em) : agora();
  if (agora() - quando > TROFEU_JANELA_MS) return false;
  const chave = `trofeu:${state.turno}:${state.cargo}:${state.abrangencia}:${ev.sq_candidato_a}`;
  if (_trofeusVistos.has(chave)) return false;
  try { if (localStorage.getItem(chave)) return false; } catch (e) {}
  _trofeusVistos.add(chave);
  try { localStorage.setItem(chave, String(Date.now())); } catch (e) {}
  const nome = state.ficha[ev.sq_candidato_a]?.nome_urna || "";
  const num = state.ficha[ev.sq_candidato_a]?.partido;
  const cor = num ? corDoPartido(num) : "#f0b429";
  comemorar(nome, cor);
  abrirModalVitoria(ev.sq_candidato_a, cor);
  return true;
}

// Tela do celular acendeu / voltou pra aba: a conexão ao vivo pode ter
// caído (ou estar "aberta" mas morta). Atualiza na hora em vez de esperar.
document.addEventListener("visibilitychange", () => {
  if (document.hidden) return;
  if (!state.ws || state.ws.readyState !== WebSocket.OPEN) {
    state.wsRetry = 0;
    conectarWS();  // onopen já puxa placar + eventos
  } else {
    refreshApuracao().then(carregarEventos).catch(() => {});
  }
});
// Página restaurada do cache de navegação (voltar/avançar, iOS): idem.
window.addEventListener("pageshow", (e) => {
  if (e.persisted) { state.wsRetry = 0; conectarWS(); }
});
// Rede: se a conexão ao vivo ficar muda por 90s durante a apuração
// (Wi-Fi ↔ 4G costuma deixar o socket "aberto" sem entregar nada),
// busca direto. O TSE atualiza bem antes disso nessa fase.
setInterval(() => {
  if (document.hidden) return;
  const pct = state.ultimoSnapshot?.totais?.pct_apurado || 0;
  if (pct <= 0 || pct >= 100) return;
  if (Date.now() - (state.ultimaMsgWs || 0) < 90_000) return;
  state.ultimaMsgWs = Date.now();
  refreshApuracao(true).then(carregarEventos).catch(() => {});
}, 30_000);

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
    ? `${nome} lidera com ${dec(lider.pct_validos, 1)}% dos votos válidos · ${dec(dados.totais.pct_apurado, 1)}% apurado`
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
        <tr><td><kbd>f</kbd></td><td>Modo TV</td></tr>
        <tr><td><kbd>?</kbd></td><td>Esta ajuda</td></tr>
        <tr><td><kbd>Esc</kbd></td><td>Fechar</td></tr>
      </table>
    </div>`;
  const modal = $("modal-cand");
  const card = $("modal-card");
  if (!modal || !card) return;
  card.innerHTML = html;
  modal.classList.remove("oculto");
}

// ============ Modo TV — quadro de transmissão (2º turno) ============
// No 2º turno (dois candidatos) o modo TV vira um quadro 16:9 fixo, estilo
// telejornal, que escala inteiro (1 unidade = 1px a 1920×1080): a mesma
// composição em 960×540 ou 1920×1080. Mapa e gráfico são os do site,
// "emprestados" pro quadro e devolvidos ao sair — continuam atualizando
// pela mesma lógica. Controles (turno/cargo/UF/sair) ficam escondidos e
// descem do topo com o mouse lá em cima ou uma tecla do controle.
function quadroTVAtivo() {
  if (!document.body.classList.contains("is-tv") || state.turno !== 2) return false;
  return (state.candidatos || []).filter(c => (c.situacao || "ativo") === "ativo").length === 2;
}
const _emprestimos = [];
function emprestar(el, destino) {
  if (!el || !destino || el.parentElement === destino) return;
  _emprestimos.push([el, el.parentElement, el.nextSibling]);
  destino.appendChild(el);
}
function devolverEmprestimos() {
  while (_emprestimos.length) {
    const [el, pai, prox] = _emprestimos.pop();
    pai.insertBefore(el, prox && prox.parentElement === pai ? prox : null);
  }
}
function aplicarQuadroTV() {
  const box = $("tv-quadro");
  if (!box) return;
  const ativo = quadroTVAtivo();
  const era = document.body.classList.contains("tv-quadro");
  box.hidden = !ativo;
  document.body.classList.toggle("tv-quadro", ativo);
  if (ativo && !era) {
    emprestar($("mapa-brasil"), $("tvq-mapa-slot"));
    emprestar($("mapa-legenda"), $("tvq-mapa-slot"));
    emprestar(document.querySelector(".home-graf-wrap"), $("tvq-graf-slot"));
  } else if (!ativo && era) {
    devolverEmprestimos();
    document.body.classList.remove("tv-controles");
  }
  if (ativo !== era) {
    _ticker.html = null; _ticker.x = 0;
    const f = $("tvq-fita"); if (f) f.innerHTML = "";
    requestAnimationFrame(() => {
      window.dispatchEvent(new Event("resize"));
      try { atualizarMapa(); } catch (e) {}
      try { atualizarGrafHome(); } catch (e) {}
    });
  }
  if (ativo) renderTVQuadro();
}

function renderTVQuadro() {
  if (!document.body.classList.contains("tv-quadro")) return;
  const snap = state.ultimoSnapshot || {};
  const t = snap.totais || {};
  const pct = t.pct_apurado || 0;
  const comecou = !!snap.disponivel && pct > 0;
  // Entre 17h e o 1º boletim: urnas fechadas, ainda sem número.
  const fechou = agora() >= DIA_D_2T.getTime();
  $("tvq-vivo").hidden = !((comecou || fechou) && pct < 100);
  $("tvq-titulo").innerHTML = `<b>2º turno</b> · ${state.cargo === 1 ? "Presidente da República" : `Governador · ${NOMES_UF_EXT[state.abrangencia] || state.abrangencia}`}`;
  $("tvq-pct").textContent = `${dec(pct, 2)}%`;
  $("tvq-barra").style.transform = `scaleX(${Math.min(1, pct / 100)})`;
  $("tvq-mapa-rot").textContent = state.abrangencia === "BR" ? "Quem lidera em cada estado" : "Quem lidera em cada município";
  $("tvq-graf-rot").textContent = comecou || fechou ? "Evolução dos válidos (%)" : "Contagem regressiva";

  // ---- placar (estrutura refeita só quando a dupla muda; números sempre)
  const ativos = (state.candidatos || []).filter(c => (c.situacao || "ativo") === "ativo")
    .sort((x, y) => (x.numero || 0) - (y.numero || 0));
  if (ativos.length !== 2) return;
  const placar = $("tvq-placar");
  const chave = ativos.map(c => c.sq_candidato).join(",");
  if (placar.dataset.chave !== chave) {
    const lado = (c, i) => {
      const cor = corPartido(c.partido);
      return `<div class="tvq-lado ${i ? "dir" : ""}" data-sq="${c.sq_candidato}" style="--cor:${cor};--cor-txt:${corLegivel(cor, "#0d1424")}">
        <div class="tvq-foto-box"><img class="tvq-foto" src="${c.foto}" alt=""></div>
        <div class="tvq-id"><div class="tvq-nome">${c.nome_urna}</div>
          <div class="tvq-part"><span class="tvq-numero">${c.numero}</span><img class="tvq-logo" src="${urlLogoPartido(+c.partido)}" alt="" decoding="async">${siglaDoPartido(+c.partido) || ""}</div></div>
        <div class="tvq-valores"><div class="tvq-pct"></div><div class="tvq-votos"></div></div>
      </div>`;
    };
    placar.innerHTML = lado(ativos[0], 0)
      + `<div class="tvq-centro"><span class="tvq-meio" id="tvq-dif-rot">Diferença</span><span class="tvq-dif" id="tvq-dif"></span>
          <div class="tvq-split" aria-hidden="true"><i id="tvq-split-a"></i><i id="tvq-split-b"></i></div>
          <span class="tvq-meio">50% dos válidos</span></div>`
      + lado(ativos[1], 1);
    placar.dataset.chave = chave;
    placar.querySelectorAll(".tvq-foto").forEach((img, i) =>
      anexarFotoComRetry(img, ativos[i].nome_urna, ativos[i].partido));
    // Logo que não carrega some; a sigla escrita continua ao lado.
    placar.querySelectorAll(".tvq-logo").forEach(img =>
      img.addEventListener("error", () => img.remove(), { once: true }));
  }
  const porSq = new Map((snap.candidatos || []).map(c => [c.sq_candidato, c]));
  const v = ativos.map(c => porSq.get(c.sq_candidato) || { votos: 0, pct_validos: 0 });
  const liderIdx = comecou && v[0].votos !== v[1].votos ? (v[0].votos > v[1].votos ? 0 : 1) : -1;
  placar.querySelectorAll(".tvq-lado").forEach((el, i) => {
    el.classList.toggle("lider", i === liderIdx);
    el.classList.toggle("eleito", state.eleitos.has(ativos[i].sq_candidato));
    el.querySelector(".tvq-pct").innerHTML = comecou ? `${dec(v[i].pct_validos, 2)}<small>%</small>` : "—";
    el.querySelector(".tvq-votos").textContent = comecou ? `${fmtNum(v[i].votos)} votos` : "aguardando";
  });
  const tot = v[0].pct_validos + v[1].pct_validos;
  const wA = comecou && tot > 0 ? v[0].pct_validos / tot * 100 : 50;
  $("tvq-split-a").style.cssText = `flex-basis:${wA}%;background:${comecou ? corPartido(ativos[0].partido) : "#1a2440"}`;
  $("tvq-split-b").style.cssText = `flex-basis:${100 - wA}%;background:${comecou ? corPartido(ativos[1].partido) : "#1a2440"}`;
  const eleito = ativos.find(c => state.eleitos.has(c.sq_candidato));
  $("tvq-dif-rot").textContent = eleito ? "Eleito" : (comecou ? "Diferença" : fechou ? "Urnas fechadas" : "A apuração começa");
  $("tvq-dif").innerHTML = eleito
    ? `${(state.ficha[eleito.sq_candidato]?.nome_urna || eleito.nome_urna)}`
    : comecou
      ? `${fmtNum(Math.abs(v[0].votos - v[1].votos))} <small>votos · ${dec(Math.abs(v[0].pct_validos - v[1].pct_validos), 2)} ponto${Math.abs(v[0].pct_validos - v[1].pct_validos) >= 2 ? "s" : ""}</small>`
      : fechou
        ? `Aguardando <small>o 1º boletim do TSE</small>`
        : `${DIA_D_2T.toLocaleDateString("pt-BR", { timeZone: TZ, day: "2-digit", month: "2-digit" })} <small>às 17h (Brasília)</small>`;

  renderEstimativaQuadro(ativos, pct, !!eleito);
  renderTickerQuadro(ativos, v, comecou, pct, t);
}

function renderEstimativaQuadro(ativos, pct, decidido) {
  const box = $("tvq-est");
  const tit = `<div class="tvq-rot">Estimativa para 100% apurado <span class="tvq-selo">não oficial</span>${
    !decidido && empateTecnico(state.projecao) ? ` <span class="tvq-selo tvq-empate">empate técnico</span>` : ""}</div>`;
  if (decidido || pct >= 100) {
    box.innerHTML = tit + `<p class="tvq-est-msg">${decidido
      ? "Resultado decidido: os votos que faltam não mudam mais o vencedor."
      : "Apuração encerrada: vale o resultado oficial."}</p>`;
    return;
  }
  const pj = state.projecao;
  const linha = (c, val, chance) => {
    const cor = corPartido(c.partido);
    return `<div class="tvq-est-l"><span class="tvq-est-n" style="border-color:${cor}">${c.nome_urna}</span>${val}${chance}</div>`;
  };
  if (!pj?.disponivel) {
    box.innerHTML = tit + `<p class="tvq-est-espera">${textoInicioEstimativa()}${pct > 0 ? ` · agora ${dec(pct, 1)}%` : ""}</p>`
      + ativos.map(c => linha(c, `<span class="tvq-est-p tvq-mudo">≈ —</span>`, `<span class="tvq-est-c tvq-mudo">—<span>${textoInicioChance()}</span></span>`)).join("")
      + `<p class="tvq-est-hora">${textoHorario99()}</p>`;
    return;
  }
  const porSq = new Map(pj.candidatos.map(c => [c.sq_candidato, c]));
  const vir = avisoViradaEstimativa(pj);
  const proj = vitoriaProjetada(pj);
  const linhaVirada = proj
    ? `<p class="tvq-est-virada tvq-projetada">Se a tendência continuar, <b>${proj.nome}</b> será eleito · mais de 99% de chance. O aviso oficial sai quando a conta fechar.</p>`
    : vir?.forte
    ? `<p class="tvq-est-virada">A estimativa indica virada: <b>${vir.nome}</b> tem ${vir.chance}% de chance de terminar na frente</p>`
    : vir ? `<p class="tvq-est-virada tvq-leve">Leve vantagem de <b>${vir.nome}</b> no fim, segundo a estimativa (${vir.chance}% de chance de vencer)</p>` : "";
  const titulo = proj ? tit.replace("</div>", ` <span class="tvq-selo tvq-selo-projetada">vitória projetada</span></div>`) : tit;
  box.innerHTML = titulo + linhaVirada + ativos.map(c => {
    const e = porSq.get(c.sq_candidato);
    if (!e) return "";
    const m = (e.ic95[1] - e.ic95[0]) / 2;
    const chance = e.p_vitoria != null
      ? (pj.probabilidade_previa
        ? `<span class="tvq-est-c tvq-previa">${chanceCurta(e.p_vitoria)}<span>chance de vencer · prévia</span></span>`
        : `<span class="tvq-est-c">${chanceCurta(e.p_vitoria)}<span>chance de vencer</span></span>`)
      : pj.disputa_indefinida
        ? `<span class="tvq-est-c tvq-mudo tvq-indef">indefinida<span>chance de vencer</span></span>`
        : `<span class="tvq-est-c tvq-mudo">—<span>${textoInicioChance()}</span></span>`;
    return linha(c, `<span class="tvq-est-p">≈${dec(e.pct, 1)}%<small>± ${dec(m, 1)}</small></span>`, chance);
  }).join("") + (textoHorario99() ? `<p class="tvq-est-hora">${textoHorario99()}</p>` : "");
}

// Letreiro "ÚLTIMAS". Rola por requestAnimationFrame (não animação CSS):
// a posição nunca volta ao começo quando o texto muda. O texto novo fica
// "na fila" e só entra quando uma volta completa termina, no ponto em que
// a costura não aparece. Cada volta repete os itens até cobrir a largura
// da faixa (antes sobrava um buraco). Quem foi eleito fica FIXO à
// esquerda, fora da rolagem.
const NOMES_UF_EXT = { AC: "Acre", AL: "Alagoas", AM: "Amazonas", AP: "Amapá", BA: "Bahia", CE: "Ceará",
  DF: "Distrito Federal", ES: "Espírito Santo", GO: "Goiás", MA: "Maranhão", MG: "Minas Gerais",
  MS: "Mato Grosso do Sul", MT: "Mato Grosso", PA: "Pará", PB: "Paraíba", PE: "Pernambuco", PI: "Piauí",
  PR: "Paraná", RJ: "Rio de Janeiro", RN: "Rio Grande do Norte", RO: "Rondônia", RR: "Roraima",
  RS: "Rio Grande do Sul", SC: "Santa Catarina", SE: "Sergipe", SP: "São Paulo", TO: "Tocantins", ZZ: "Exterior" };
// Viradas por estado: o TSE/motor só registra virada nacional; as dos
// estados são percebidas aqui, comparando o líder de cada UF entre
// atualizações do mapa.
state.viradasUF = [];
let _lideresUFAnt = null;
function registrarViradasUF(dadosPorUF) {
  const atual = {};
  for (const [uf, d] of Object.entries(dadosPorUF)) if (d.nome_lider && d.votos > 0) atual[uf] = d.nome_lider;
  if (_lideresUFAnt && state.turno === 2) {
    for (const [uf, nome] of Object.entries(atual)) {
      const antes = _lideresUFAnt[uf];
      if (antes && antes !== nome) {
        state.viradasUF.push({ t: Date.now(), txt: `${nome} passa à frente em ${NOMES_UF_EXT[uf] || uf}` });
      }
    }
    state.viradasUF = state.viradasUF.slice(-8);
  }
  _lideresUFAnt = atual;
}

const _ticker = { x: 0, w: 0, pendente: null, html: null, ultimo: 0, raf: 0 };
function renderTickerQuadro(ativos, v, comecou, pct, t) {
  const fita = $("tvq-fita");
  if (!fita) return;
  const nome = sq => state.ficha[sq]?.nome_urna || "";
  // Eleito: fixo à esquerda
  const fixo = $("tvq-fixo");
  const eleito = ativos.find(c => state.eleitos.has(c.sq_candidato));
  if (fixo) {
    if (eleito) {
      const vi = v[ativos.indexOf(eleito)];
      fixo.innerHTML = `<b>Eleito</b>${nome(eleito.sq_candidato) || eleito.nome_urna} <small>${siglaDoPartido(+eleito.partido) || ""}${vi?.pct_validos ? ` · ${dec(vi.pct_validos, 2)}%` : ""}</small>`;
      fixo.hidden = false;
    } else fixo.hidden = true;
  }
  // Últimos acontecimentos (mais recentes primeiro): viradas nacionais e
  // por estado, com hora.
  const recentes = [];
  for (const ev of (state.eventosLista || [])) {
    if (ev.tipo !== "VIRADA") continue;
    recentes.push({ t: ev.ocorrido_em ? Date.parse(ev.ocorrido_em) : 0,
      txt: `${nome(ev.sq_candidato_a)} passa ${nome(ev.sq_candidato_b)} no ${state.cargo === 1 ? "Brasil" : state.abrangencia}` });
  }
  if (state.abrangencia === "BR") recentes.push(...state.viradasUF);
  recentes.sort((a, b) => b.t - a.t);
  const itens = recentes.slice(0, 6).map(r =>
    `${r.t ? `<time>${new Date(r.t).toLocaleTimeString("pt-BR", { timeZone: TZ, hour: "2-digit", minute: "2-digit" })}</time>` : ""}${r.txt}`);
  const proj = comecou && !eleito ? vitoriaProjetada(state.projecao) : null;
  if (comecou && !eleito) {
    const vir = avisoViradaEstimativa(state.projecao);
    if (proj) itens.unshift(`<b>Vitória projetada:</b> se a tendência continuar, ${proj.nome} será eleito (mais de 99% de chance, não oficial)`);
    else if (vir?.forte) itens.unshift(`<b>A estimativa indica virada:</b> ${vir.nome} tem ${vir.chance}% de chance de terminar na frente (${vir.previa ? "prévia, " : ""}não oficial)`);
    else if (vir) itens.unshift(`Empate técnico: a estimativa vê leve vantagem de ${vir.nome} no fim (${vir.chance}% de chance de vencer, não oficial)`);
    else if (empateTecnico(state.projecao)) itens.unshift("Estimativa em empate técnico: o placar ainda pode virar (não oficial)");
  }
  if (comecou) {
    const i = v[0].votos >= v[1].votos ? 0 : 1;
    if (v[0].votos !== v[1].votos && !eleito) itens.push(`${ativos[i].nome_urna} à frente por ${fmtNum(Math.abs(v[0].votos - v[1].votos))} votos`);
    itens.push(`${dec(pct, 2)}% apurado · ${fmtNum(t.secoes_totalizadas || 0)} de ${fmtNum(t.secoes_total || 0)} seções`);
    itens.push(...itensApuracaoTicker(t, pct));
    const cm = state.contagemMapa;
    if (cm?.nomes?.size) {
      const partes = [...cm.nomes.entries()].sort((a, b) => b[1].n - a[1].n)
        .map(([n, { n: k }]) => `${n} em ${k} ${cm.unidade === "UF" ? (k === 1 ? "estado" : "estados") : (k === 1 ? "município" : "municípios")}`);
      itens.push(`Lidera: ${partes.join(" · ")}`);
    }
    itens.push(...itensOutrasDisputas());
    // Recordes logo depois do placar: entram e ficam enquanto valerem.
    const rec = recordesDaEleicao().map(x => `<b class="tvq-recorde">Recorde</b> ${x}`);
    itens.splice(Math.min(2, itens.length), 0, ...rec);
  } else {
    itens.push(agora() >= DIA_D_2T.getTime()
      ? "Urnas fechadas às 17h: aguardando o 1º boletim do TSE"
      : `A apuração do 2º turno começa domingo, ${DIA_D_2T.toLocaleDateString("pt-BR", { timeZone: TZ, day: "2-digit", month: "2-digit" })}, às 17h (Brasília)`);
    itens.push(`${ativos[0].nome_urna} (${ativos[0].numero}) × ${ativos[1].nome_urna} (${ativos[1].numero})`);
    itens.push(...itensAntesDaApuracao());
  }
  itens.push("Resultado oficial: resultados.tse.jus.br");
  const html = itens.map(x => `<span class="tvq-item">${x}</span><span class="tvq-sep" aria-hidden="true">◆</span>`).join("");
  if (html === _ticker.html) return;
  _ticker.html = html;
  // Mudou a notícia principal (eleito, troca de líder, início da apuração):
  // troca a faixa na hora, com fade. Esperar a volta terminar deixava até
  // ~75 s de "X à frente" ao lado do "Eleito Y".
  const iLider = comecou && v[0].votos !== v[1].votos ? (v[0].votos > v[1].votos ? 0 : 1) : -1;
  const chave = `${eleito?.sq_candidato || ""}|${iLider}|${comecou}|${proj?.sq || ""}`;
  const mudouPrincipal = _ticker.chave !== undefined && _ticker.chave !== chave;
  _ticker.chave = chave;
  if (!fita.firstElementChild) trocarFitaTicker();
  else if (mudouPrincipal) {
    _ticker.pendente = html;
    fita.style.transition = "opacity .35s";
    fita.style.opacity = "0";
    setTimeout(() => {
      _ticker.x = 0;
      trocarFitaTicker();
      fita.style.opacity = "1";
    }, 360);
  } else _ticker.pendente = html;
  if (!_ticker.raf) _ticker.raf = requestAnimationFrame(passoTicker);
}
// Placar por região (presidente, 2º turno, Brasil): soma dos estados no
// servidor (/api/apuracao/regioes). Some antes de haver voto apurado.
state.regioes = null;
function regioesAplicavel() {
  return state.turno === 2 && state.cargo === 1 && state.abrangencia === "BR";
}
async function atualizarRegioes(fresco = false) {
  if (!regioesAplicavel() || !(state.ultimoSnapshot?.totais?.pct_apurado > 0)) { state.regioes = null; return; }
  try { state.regioes = await get("/api/apuracao/regioes?cargo=1&turno=2", { fresco }); } catch (e) { /* mantém o anterior */ }
}
function renderRegioes() {
  const secao = $("regioes-secao"), tv = $("tvq-regioes");
  // As seis linhas aparecem desde antes das 17h ("aguardando"), e cada uma
  // ganha número quando chega o primeiro boletim da região.
  const daApi = Object.fromEntries((state.regioes?.regioes || []).map(r => [r.regiao, r]));
  const regs = ["Norte", "Nordeste", "Centro-Oeste", "Sudeste", "Sul", "Exterior"].map(nome => {
    const r = daApi[nome];
    return r && r.candidatos.length >= 2 ? r : { regiao: nome, pct_apurado: 0, candidatos: [] };
  });
  const fin = (state.candidatos || []).filter(c => (c.situacao || "ativo") === "ativo")
    .sort((x, y) => (x.numero || 0) - (y.numero || 0));
  const ok = regioesAplicavel() && fin.length === 2;
  if (secao) secao.hidden = !ok;
  if (tv) { tv.hidden = !ok; tv.parentElement?.classList.toggle("com-regioes", !!ok); }
  if (!ok) return;
  const [a, b] = fin;
  const cor = c => corPartido(c.partido);
  const pctDe = (r, c) => r.candidatos.find(x => x.sq_candidato === c.sq_candidato)?.pct || 0;
  const linha = (r, compacto) => {
    const pa = pctDe(r, a), pb = pctDe(r, b), vazio = r.pct_apurado <= 0 || !r.candidatos.length;
    const lider = pa === pb ? null : (pa > pb ? a : b);
    return `<div class="reg-linha${vazio ? " reg-vazia" : ""}">
      <span class="reg-nome">${r.regiao}<small>${vazio ? "aguardando" : `${dec(r.pct_apurado, compacto ? 0 : 1)}% apurado`}</small></span>
      <span class="reg-pct" style="color:${corLegivel(cor(a))}"${lider === a ? ' data-lider' : ""}>${vazio ? "—" : dec(pa, 1) + "%"}</span>
      <span class="reg-barra" aria-hidden="true">${vazio
        ? `<i style="width:100%;background:rgba(255,255,255,.08)"></i>`
        : `<i style="width:${pa}%;background:${cor(a)}"></i><i style="width:${pb}%;background:${cor(b)}"></i>`}</span>
      <span class="reg-pct" style="color:${corLegivel(cor(b))}"${lider === b ? ' data-lider' : ""}>${vazio ? "—" : dec(pb, 1) + "%"}</span>
    </div>`;
  };
  const cab = `<div class="reg-cab"><span></span><span style="color:${corLegivel(cor(a))}">${a.nome_urna}</span><span></span><span style="color:${corLegivel(cor(b))}">${b.nome_urna}</span></div>`;
  const html = cab + regs.map(r => linha(r, false)).join("");
  const lista = $("regioes-lista");
  if (lista && lista.innerHTML !== html) lista.innerHTML = html;
  if (tv) {
    const htv = `<div class="tvq-rot">Por região</div>` + cab + regs.map(r => linha(r, true)).join("");
    if (tv.innerHTML !== htv) tv.innerHTML = htv;
  }
}

// ============ Recordes e curiosidades (presidente, 2º turno, Brasil) ============
// Comparação com os 2º turnos para presidente desde 1989. 2018 e 2022 somados
// dos boletins de urna do TSE (batem com o resultado oficial: Lula 2022 =
// 60.345.999); 2010 do resultado oficial. Os demais anos ficam abaixo desses
// em todos os itens. Contagens só crescem durante a apuração, então o recorde
// em número aparece assim que é passado; porcentagens e diferença mudam até o
// fim, por isso só com 100% apurado.
const RECORDES_2T = {
  votosCandidato: { valor: 60345999, quem: "Lula", ano: 2022 },
  votosNaoEleito: { valor: 58206354, quem: "Bolsonaro", ano: 2022 },
  votosValidos: { valor: 118552353, ano: 2022 },
  nulos: { valor: 8608105, ano: 2018 },
  brancos: { valor: 2486593, ano: 2018 },
  brancosNulos: { valor: 11094698, ano: 2018 },
  brancosNulosPct: { valor: 9.57, ano: 2018 },
  abstencoes: { valor: 32200558, ano: 2022 },
  abstencaoPct: { valor: 21.50, ano: 2010 },
  comparecimento: { valor: 124252796, ano: 2022 },
  margemPontos: { valor: 1.80, votos: 2139645, ano: 2022 },
  // Unidades da federação (26 estados + DF) em que o eleito venceu. Menor
  // número desde 1989: Lula 2022, 13 (somado dos boletins de urna; Collor
  // 1989: 23; Dilma 2010: 16; Dilma 2014: 15; Bolsonaro 2018: 16).
  menosEstadosEleito: { valor: 13, quem: "Lula", ano: 2022 },
};
state.lider1T = undefined;
async function carregarLider1T() {
  if (state.lider1T !== undefined) return;
  state.lider1T = null;
  try {
    const j = await get("/api/apuracao/atual?cargo=1&abrangencia=BR&turno=1");
    const top = [...(j.candidatos || [])].sort((a, b) => b.votos - a.votos)[0];
    state.lider1T = top?.sq_candidato || null;
  } catch (e) { state.lider1T = undefined; }
}
function recordesDaEleicao() {
  if (!(state.turno === 2 && state.cargo === 1 && state.abrangencia === "BR")) return [];
  const snap = state.ultimoSnapshot;
  const t = snap?.totais;
  if (!snap?.disponivel || !t || !(t.pct_apurado > 0)) return [];
  const R = RECORDES_2T, out = [];
  const nome = sq => state.ficha[sq]?.nome_urna || "";
  const cands = (snap.candidatos || []).filter(c => (state.ficha[c.sq_candidato]?.situacao || "ativo") === "ativo")
    .sort((a, b) => b.votos - a.votos);
  // "Mais votado da história" só para quem está na frente: se os dois
  // passarem o recorde, o de trás não é o mais votado (aparece se virar).
  const [c1, c2] = cands;
  if (c1 && (!c2 || c1.votos > c2.votos) && c1.votos > R.votosCandidato.valor) {
    const n = nome(c1.sq_candidato);
    const dono = /\bLULA\b/i.test(n) ? "do próprio Lula, em 2022" : `de ${R.votosCandidato.quem}, em ${R.votosCandidato.ano}`;
    out.push(`${n} já tem ${fmtNum(c1.votos)} votos, mais que qualquer candidato a presidente na história. O recorde anterior era ${dono}: ${fmtNum(R.votosCandidato.valor)}.`);
  }
  // Com o eleito definido, o outro pode ter a maior votação de quem não se
  // elegeu (antes de definido, "não eleito" ainda não se sabe).
  const eleitoSq = cands.find(c => state.eleitos.has(c.sq_candidato))?.sq_candidato;
  const naoEleito = eleitoSq && cands.find(c => c.sq_candidato !== eleitoSq);
  if (naoEleito && naoEleito.votos > R.votosNaoEleito.valor) {
    out.push(`${nome(naoEleito.sq_candidato)} tem ${fmtNum(naoEleito.votos)} votos, mais que qualquer candidato a presidente que não foi eleito. O recorde anterior era de ${R.votosNaoEleito.quem}, em ${R.votosNaoEleito.ano}: ${fmtNum(R.votosNaoEleito.valor)}.`);
  }
  const bn = (t.votos_brancos || 0) + (t.votos_nulos || 0);
  const validos = cands.reduce((soma, c) => soma + (c.votos || 0), 0);
  if (validos > R.votosValidos.valor)
    out.push(`${fmtNum(validos)} votos válidos (dados a um candidato): o maior número num 2º turno. O recorde era de ${R.votosValidos.ano}: ${fmtNum(R.votosValidos.valor)}.`);
  if (t.comparecimento > R.comparecimento.valor)
    out.push(`${fmtNum(t.comparecimento)} eleitores já votaram: o maior comparecimento num 2º turno. O recorde era de ${R.comparecimento.ano}: ${fmtNum(R.comparecimento.valor)}.`);
  if (t.abstencoes > R.abstencoes.valor)
    out.push(`${fmtNum(t.abstencoes)} abstenções: o maior número de eleitores que não votaram num 2º turno. O recorde era de ${R.abstencoes.ano}: ${fmtNum(R.abstencoes.valor)}.`);
  if (t.votos_nulos > R.nulos.valor)
    out.push(`${fmtNum(t.votos_nulos)} votos nulos: recorde num 2º turno. O anterior era de ${R.nulos.ano}: ${fmtNum(R.nulos.valor)}.`);
  if (t.votos_brancos > R.brancos.valor)
    out.push(`${fmtNum(t.votos_brancos)} votos em branco: recorde num 2º turno. O anterior era de ${R.brancos.ano}: ${fmtNum(R.brancos.valor)}.`);
  if (bn > R.brancosNulos.valor)
    out.push(`Brancos e nulos somam ${fmtNum(bn)}: recorde num 2º turno. O anterior era de ${R.brancosNulos.ano}: ${fmtNum(R.brancosNulos.valor)}.`);
  if (t.pct_apurado >= 100 && t.comparecimento > 0) {
    const apto = t.eleitorado_apto_totalizado || t.eleitorado_apto || 0;
    const abstPct = apto ? t.abstencoes / apto * 100 : 0;
    if (abstPct > R.abstencaoPct.valor)
      out.push(`Abstenção de ${dec(abstPct, 2)}%: a maior proporção num 2º turno desde 1989. O recorde era de ${R.abstencaoPct.ano}: ${dec(R.abstencaoPct.valor, 2)}%.`);
    const bnPct = bn / t.comparecimento * 100;
    if (bnPct > R.brancosNulosPct.valor)
      out.push(`Brancos e nulos foram ${dec(bnPct, 2)}% dos votos: a maior proporção num 2º turno desde 1989 (${R.brancosNulosPct.ano}: ${dec(R.brancosNulosPct.valor, 2)}%).`);
    if (cands.length >= 2) {
      const pontos = cands[0].pct_validos - cands[1].pct_validos;
      if (pontos < R.margemPontos.valor)
        out.push(`Diferença de ${dec(pontos, 2)} ponto${pontos >= 2 ? "s" : ""} (${fmtNum(cands[0].votos - cands[1].votos)} votos): o 2º turno mais apertado desde 1989. O recorde era de ${R.margemPontos.ano}: ${dec(R.margemPontos.valor, 2)} ponto (${fmtNum(R.margemPontos.votos)} votos).`);
    }
  }
  // Eleito com menos estados (só com 100%: os estados ainda viram até o fim).
  const eleitoC = cands.find(c => state.eleitos.has(c.sq_candidato));
  const lideres = Object.values(state.lideresUF || {});
  if (eleitoC && t.pct_apurado >= 100 && lideres.length === 27) {
    const n = lideres.filter(sq => sq === eleitoC.sq_candidato).length;
    if (n < R.menosEstadosEleito.valor)
      out.push(`${nome(eleitoC.sq_candidato)} foi eleito vencendo em ${n} das 27 unidades da federação: o menor número para um eleito desde 1989. O recorde era de ${R.menosEstadosEleito.quem}, em ${R.menosEstadosEleito.ano}: ${R.menosEstadosEleito.valor}.`);
  }
  // Curiosidade: em todos os 2º turnos desde 1989, quem liderou o 1º turno venceu.
  const eleito = cands.find(c => state.eleitos.has(c.sq_candidato));
  if (eleito && state.lider1T && eleito.sq_candidato !== state.lider1T)
    out.push(`Pela primeira vez desde 1989, quem ficou em 2º lugar no 1º turno vence o 2º turno.`);
  return out;
}
function renderRecordes() {
  const secao = $("recordes-secao"), lista = $("recordes-lista");
  if (!secao || !lista) return;
  const itens = recordesDaEleicao();
  secao.hidden = !itens.length;
  const html = itens.map(x => `<li>${x}</li>`).join("");
  if (lista.innerHTML !== html) lista.innerHTML = html;
}

// Resumo de todas as disputas do 2º turno (/api/apuracao/resumo-2t), para
// o letreiro mostrar as outras disputas da noite. No máximo a cada 30 s.
state.resumo2T = null;
let _resumo2TEm = 0;
async function atualizarResumo2T() {
  if (state.turno !== 2 || Date.now() - _resumo2TEm < 30000) return;
  _resumo2TEm = Date.now();
  try { state.resumo2T = await get("/api/apuracao/resumo-2t"); } catch (e) { /* letreiro segue sem elas */ }
}
function rotuloDisputa(d) {
  return d.cargo === 1 ? "Presidente" : `Governador · ${NOMES_UF_EXT[d.abrangencia] || d.abrangencia}`;
}
function listaComE(xs) {
  return xs.length > 1 ? `${xs.slice(0, -1).join(", ")} e ${xs.at(-1)}` : (xs[0] || "");
}
// Durante a apuração: as disputas que não estão na tela.
function itensOutrasDisputas() {
  const sig = c => siglaDoPartido(+c.partido) || "";
  const out = [];
  for (const d of state.resumo2T?.disputas || []) {
    if (d.cargo === state.cargo && d.abrangencia === state.abrangencia) continue;
    const [a, b] = d.candidatos;
    if (d.eleito) {
      const e = d.candidatos.find(c => c.sq_candidato === d.eleito) || a;
      out.push(`${rotuloDisputa(d)}: <b>${e.nome_urna}</b> (${sig(e)}) eleito com ${dec(e.pct, 1)}%`);
    } else if (d.pct_apurado > 0) {
      out.push(`${rotuloDisputa(d)} · ${dec(d.pct_apurado, 1)}% apurado: ${a.nome_urna} ${dec(a.pct, 1)}% × ${b.nome_urna} ${dec(b.pct, 1)}%`);
    }
  }
  return out;
}
// Antes da apuração: 1º turno da disputa na tela e onde mais há 2º turno.
function itensAntesDaApuracao() {
  const ds = state.resumo2T?.disputas || [];
  const out = [];
  const atual = ds.find(d => d.cargo === state.cargo && d.abrangencia === state.abrangencia);
  if (atual && atual.candidatos.every(c => c.pct_1t != null)) {
    const [x, y] = [...atual.candidatos].sort((p, q) => q.pct_1t - p.pct_1t);
    out.push(`No 1º turno: ${x.nome_urna} ${dec(x.pct_1t, 1)}% × ${y.nome_urna} ${dec(y.pct_1t, 1)}% dos válidos`);
  }
  const ufs = ds.filter(d => d.cargo === 3).map(d => d.abrangencia).sort();
  if (state.cargo === 1 && ufs.length) out.push(`Também há 2º turno para governador em ${listaComE(ufs)}`);
  return out;
}
const REGIOES_UF = {
  Norte: ["AC", "AM", "AP", "PA", "RO", "RR", "TO"],
  Nordeste: ["AL", "BA", "CE", "MA", "PB", "PE", "PI", "RN", "SE"],
  "Centro-Oeste": ["DF", "GO", "MS", "MT"],
  Sudeste: ["ES", "MG", "RJ", "SP"],
  Sul: ["PR", "RS", "SC"],
};
// Só dado oficial do próprio boletim: comparecimento, brancos e nulos,
// apuração por região e estados encerrados.
function itensApuracaoTicker(t, pct) {
  const itens = [];
  const aptoTot = t.eleitorado_apto_totalizado || 0;
  if (aptoTot > 0 && t.comparecimento > 0) {
    itens.push(`Comparecimento: ${dec(t.comparecimento / aptoTot * 100, 1)}% dos eleitores das seções apuradas`);
  }
  if (t.comparecimento > 0) {
    const bn = (t.votos_brancos || 0) + (t.votos_nulos || 0);
    itens.push(`Brancos e nulos: ${dec(bn / t.comparecimento * 100, 1)}% (${fmtNum(t.votos_brancos || 0)} brancos, ${fmtNum(t.votos_nulos || 0)} nulos)`);
  }
  if (pct < 100 && t.eleitorado_apto > aptoTot && aptoTot > 0) {
    const falta = t.eleitorado_apto - aptoTot;
    itens.push(`Faltam seções com ${falta >= 1e6 ? `${dec(falta / 1e6, 1)} milhões de` : fmtNum(falta)} eleitores`);
  }
  const sec = state.abrangencia === "BR" ? state.secoesUF : null;
  if (sec && Object.keys(sec).length) {
    const partes = [];
    for (const [reg, ufs] of Object.entries(REGIOES_UF)) {
      let a = 0, tt = 0;
      for (const uf of ufs) { a += sec[uf]?.totalizadas || 0; tt += sec[uf]?.total || 0; }
      if (tt) partes.push(`${reg} ${dec(a / tt * 100, 1)}%`);
    }
    if (partes.length) itens.push(`Apurado por região: ${partes.join(" · ")}`);
    const fechadas = Object.entries(sec).filter(([uf, x]) => uf !== "ZZ" && x.total && x.totalizadas >= x.total).map(([uf]) => uf).sort();
    if (fechadas.length && fechadas.length < 27) {
      itens.push(`${fechadas.length === 1 ? "Estado" : "Estados"} com 100% apurado: ${fechadas.join(", ")}`);
    } else if (fechadas.length >= 27) itens.push("Todos os estados com 100% apurado");
  }
  return itens;
}
// Monta duas cópias idênticas; cada cópia repete os itens até ficar mais
// larga que a faixa, então a emenda nunca deixa espaço vazio.
function trocarFitaTicker() {
  const fita = $("tvq-fita"), trilho = fita?.parentElement;
  if (!fita || !trilho) return;
  const base = _ticker.pendente || _ticker.html;
  _ticker.pendente = null;
  fita.innerHTML = `<span class="tvq-copia">${base}</span>`;
  const um = fita.firstElementChild;
  let rep = 1;
  while (um.offsetWidth > 0 && um.offsetWidth < trilho.clientWidth + 40 && rep < 12) { um.innerHTML += base; rep++; }
  fita.innerHTML += `<span class="tvq-copia" aria-hidden="true">${um.innerHTML}</span>`;
  _ticker.w = um.offsetWidth;
}
function passoTicker(agora) {
  _ticker.raf = 0;
  const fita = $("tvq-fita");
  if (!fita || !document.body.classList.contains("tv-quadro")) { _ticker.ultimo = 0; return; }
  const dt = _ticker.ultimo ? Math.min(100, agora - _ticker.ultimo) : 0;
  _ticker.ultimo = agora;
  const escala = ($("tv-quadro")?.firstElementChild?.offsetWidth || 1920) / 1920;
  const reduzido = matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (!reduzido) _ticker.x -= (110 * escala) * dt / 1000;
  // Faixa mudou de largura (abriu agora, janela redimensionada) e a cópia
  // ficou curta: remonta já, sem esperar a volta, pra não abrir buraco.
  const larg = fita.parentElement?.clientWidth || 0;
  if (larg && fita.firstElementChild && fita.firstElementChild.offsetWidth < larg + 20) {
    _ticker.pendente = _ticker.pendente || _ticker.html;
    trocarFitaTicker();
    _ticker.x = Math.max(_ticker.x, -_ticker.w + 1);
  }
  // Largura medida sempre na hora: a medida guardada podia ser da fonte de
  // reserva (mais larga), antes da fonte da TV carregar, e a emenda passava
  // do ponto, abrindo buraco.
  _ticker.w = fita.firstElementChild?.offsetWidth || 0;
  if (_ticker.w && -_ticker.x >= _ticker.w) {
    _ticker.x += _ticker.w;
    if (_ticker.pendente) trocarFitaTicker();   // emenda: troca o texto aqui
  }
  fita.style.transform = `translateX(${_ticker.x}px)`;
  _ticker.raf = requestAnimationFrame(passoTicker);
}
window.addEventListener("resize", () => {
  // Só remede a largura (sem voltar ao início).
  if (!_ticker.html) return;
  _ticker.pendente = _ticker.pendente || _ticker.html;
});

// Controles escondidos: descem do topo com o mouse lá em cima, um toque
// no topo ou uma tecla do controle remoto; somem sozinhos depois.
let _tvCtlTimer = null;
function mostrarControlesTV(ms = 4000) {
  if (!document.body.classList.contains("tv-quadro")) return;
  document.body.classList.add("tv-controles");
  clearTimeout(_tvCtlTimer);
  _tvCtlTimer = setTimeout(esconderControlesTV, ms);
}
function esconderControlesTV() {
  const hero = document.querySelector(".hero");
  const focoDentro = hero && hero.contains(document.activeElement) && document.activeElement !== document.body;
  if (hero?.matches(":hover") || focoDentro || document.querySelector(".rodape-tv:hover")) {
    _tvCtlTimer = setTimeout(esconderControlesTV, 1500);
    return;
  }
  document.body.classList.remove("tv-controles");
}
// Qualquer movimento do mouse mostra os controles (antes só no alto da
// tela, e quem mexia no meio achava que não havia nada para clicar).
// Ignora tremidas de poucos pixels (mouse parado na mesa, controle com
// giroscópio), senão a barra nunca sumiria.
let _tvMouse = null;
document.addEventListener("mousemove", (e) => {
  const ant = _tvMouse;
  _tvMouse = { x: e.clientX, y: e.clientY };
  if (ant && Math.abs(e.clientX - ant.x) + Math.abs(e.clientY - ant.y) < 6) return;
  mostrarControlesTV(e.clientY < innerHeight * 0.2 ? 6000 : 4000);
});
// Toque em qualquer ponto da tela mostra os controles (com "Sair do modo
// TV"): no celular não há mouse pra levar ao topo.
document.addEventListener("pointerdown", (e) => {
  if (e.pointerType !== "mouse" || e.clientY < innerHeight * 0.15) mostrarControlesTV(6000);
});
document.addEventListener("keydown", (e) => {
  if (["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight", "Enter", "Tab", "Escape", "m"].includes(e.key)) mostrarControlesTV(6000);
});

// ============ UX: modo TV — tecla "f" = mesmo que o botão ============
function toggleModoTV() { alternarModoTV(); }

// Tela cheia do navegador. Só funciona a partir de um clique/tecla (regra
// do navegador) — por isso fica nos handlers de botão, nunca no boot.
function entrarTelaCheia() {
  const el = document.documentElement;
  const req = el.requestFullscreen || el.webkitRequestFullscreen;
  if (!req || document.fullscreenElement) return;
  try { const r = req.call(el); if (r?.catch) r.catch(() => {}); } catch (e) {}
}
// Quem entrou em tela cheia pelo Modo TV quer continuar nela. Depois de um
// recarregamento o navegador não deixa o site voltar sozinho, então o
// primeiro toque/tecla/botão do controle em qualquer lugar volta.
const FS_KEY = "elei-es:tv-tela-cheia";
let _recarregandoPagina = false;
["beforeunload", "pagehide"].forEach(t =>
  window.addEventListener(t, () => { _recarregandoPagina = true; }));
document.addEventListener("fullscreenchange", () => {
  if (_recarregandoPagina) return;
  try {
    if (document.fullscreenElement) localStorage.setItem(FS_KEY, "1");
    else localStorage.removeItem(FS_KEY);  // saiu por vontade própria (Esc)
  } catch (e) {}
});
function prepararVoltaTelaCheia() {
  let quer = false;
  try { quer = localStorage.getItem(FS_KEY) === "1"; } catch (e) {}
  if (!quer || !document.body.classList.contains("is-tv") || document.fullscreenElement) return;
  const voltar = () => {
    ["pointerdown", "keydown"].forEach(t => document.removeEventListener(t, voltar, true));
    if (document.body.classList.contains("is-tv")) entrarTelaCheia();
  };
  ["pointerdown", "keydown"].forEach(t => document.addEventListener(t, voltar, true));
  toast("Toque na tela ou aperte qualquer tecla para voltar à tela cheia", "");
}

function sairTelaCheia() {
  if (!document.fullscreenElement) return;
  try { const r = (document.exitFullscreen || document.webkitExitFullscreen).call(document); if (r?.catch) r.catch(() => {}); } catch (e) {}
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
  // 2º turno: comparar é sempre entre os dois finalistas — não precisa marcar.
  if (tab === "comparar" && state.selecionados.length < 2 && state.turno === 2) {
    const fin = (state.candidatos || []).filter(c => (c.situacao || "ativo") === "ativo");
    if (fin.length === 2) state.selecionados = fin.map(c => c.sq_candidato);
  }
  // Se for compare mas nada selecionado, avisa e mantém no placar
  if (tab === "comparar" && state.selecionados.length < 2) {
    toast("Marque 2 ou mais candidatos no placar para comparar.", "warn");
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
  // Celular não mostra notificação de página aberta (precisaria de service
  // worker e, no iPhone, instalar o site): lá os avisos vêm pelo bot.
  if (ehCelular() || !("Notification" in window)) {
    const tg = $("m-btn-telegram")?.href || $("btn-telegram")?.href;
    if (tg && !tg.endsWith("#")) {
      toast("No celular, os avisos chegam pelo bot do Telegram", "ok");
      window.open(tg, "_blank", "noopener");
    } else {
      toast("Este navegador não mostra notificações. Deixe o site aberto para ver os avisos.", "warn");
    }
    return;
  }
  const p = await Notification.requestPermission();
  toast(p === "granted" ? "Notificações ativadas: aviso de eleito e de virada com o site aberto em outra aba"
                        : "Notificações não permitidas pelo navegador",
        p === "granted" ? "ok" : "warn");
}

// Notificação do sistema quando o site está aberto mas em segundo plano
// (outra aba, janela minimizada). Com a aba visível, quem avisa é a tela.
function notificarSistema(titulo, corpo) {
  if (!document.hidden || !("Notification" in window) || Notification.permission !== "granted") return;
  try {
    const n = new Notification(titulo, { body: corpo, icon: "/static/logo.svg", tag: titulo });
    n.onclick = () => { window.focus(); n.close(); };
  } catch (e) { /* navegador recusou */ }
}
function rotuloDisputaAtual() {
  return state.cargo === 1 ? "Presidente" : `Governador · ${NOMES_UF_EXT[state.abrangencia] || state.abrangencia}`;
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
  aCadaSegundo(() => { atualizarContagemRegressiva(); esconderColaSeFechado(); tickDuelo(); tickContagemTV(); });
  atualizarContagemRegressiva();
  esconderColaSeFechado();

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
  // "Placar" aponta para a lista, que no 2º turno fica escondida (o duelo
  // faz o papel dela): aí o link só volta ao topo.
  document.querySelector('.d-topnav-link[data-anchor="lista"]')?.addEventListener("click", (e) => {
    if (!secoes.lista?.offsetParent) { e.preventDefault(); window.scrollTo({ top: 0, behavior: "smooth" }); }
  });
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
      opt.value = u.sigla; opt.textContent = `${u.sigla} · ${u.nome}`;
      selUF.appendChild(opt);
    }
    // Opção fixa: voto do exterior (ZZ). Só vota presidente — a função
    // ajustarUFParaCargo() esconde/mostra conforme o cargo escolhido.
    if (!Array.from(selUF.options).some(o => o.value === "ZZ")) {
      const optZZ = document.createElement("option");
      optZZ.value = "ZZ"; optZZ.textContent = "ZZ · Exterior";
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
  document.getElementById("btn-tela-cheia")?.addEventListener("click", entrarTelaCheia);
  atualizarBotaoTV();
  prepararVoltaTelaCheia();
  atualizarBotaoTV();
}

boot().then(restaurarRolagem).catch(e => { console.error(e); toast("Erro: " + e.message, "danger"); });

// Sem internet: o service worker (static/sw.js) guarda a página e os
// últimos números, para o site abrir e esperar a conexão voltar.
if ("serviceWorker" in navigator && (location.protocol === "https:" || location.hostname === "localhost")) {
  navigator.serviceWorker.register("/sw.js").catch(() => {});
}

// ============ Aviso de conexão ============
// Quando a conexão ao vivo cai, descobre de quem é o problema:
//  - da pessoa (sem internet): avisa em ~10 s;
//  - do site (internet ok, servidor não responde): só depois de 5 min,
//    porque um deploy derruba o servidor por alguns minutos e a página
//    se atualiza sozinha quando ele volta (checarVersao no onopen do WS).
// "Tem internet?" = o servidor do Google responde (generate_204).
const _conexao = { desde: 0, tipo: null, mostrado: false };
function _comTempo(promessa, ms) {
  return Promise.race([promessa, new Promise((_, rej) => setTimeout(() => rej(new Error("tempo")), ms))]);
}
async function diagnosticarConexao() {
  if (!navigator.onLine) return "sem-internet";
  try {
    const r = await _comTempo(fetch("/api/hora", { cache: "no-store" }), 6000);
    if (r.ok) return null;
  } catch (e) { /* segue para o teste de internet */ }
  try {
    await _comTempo(fetch("https://www.gstatic.com/generate_204", { mode: "no-cors", cache: "no-store" }), 6000);
    return "servidor";
  } catch (e) {
    return "sem-internet";
  }
}
function renderAvisoConexao() {
  const el = $("aviso-conexao");
  if (!el) return;
  const passou = Date.now() - _conexao.desde;
  // Abriu a página já sem internet (veio da cópia guardada): avisa logo.
  // Perdeu no meio: espera ~8 s, que muita queda de Wi-Fi volta sozinha.
  const abriuSem = !state.wsJaAbriu;
  const mostrar = (_conexao.tipo === "sem-internet" && passou >= (abriuSem ? 0 : 8_000))
    || (_conexao.tipo === "servidor" && passou >= 5 * 60_000);
  if (!mostrar) {
    if (!el.hidden && _conexao.mostrado && !_conexao.tipo) toast("Conexão de volta: números atualizados", "ok");
    el.hidden = true; _conexao.mostrado = false;
    return;
  }
  const snap = state.ultimoSnapshot;
  const iso = snap?.disponivel ? (snap.gerado_em_tse || snap.coletado_em) : null;
  const hoje = iso && new Date(iso).toLocaleDateString("pt-BR", { timeZone: TZ }) === new Date(agora()).toLocaleDateString("pt-BR", { timeZone: TZ });
  const quando = iso ? `${fmtHora(iso)}${hoje ? "" : ` de ${new Date(iso).toLocaleDateString("pt-BR", { timeZone: TZ, day: "2-digit", month: "2-digit" })}`}` : null;
  const dados = quando ? ` Os números na tela são os do boletim das ${quando}.` : "";
  el.innerHTML = _conexao.tipo === "sem-internet" && abriuSem
    ? `<b>Você abriu o site sem internet.</b> ${quando
        ? `Estes são os números guardados da sua última visita (boletim das ${quando}).`
        : "Ainda não há números guardados neste aparelho."} Assim que a internet voltar, o site atualiza sozinho.`
    : _conexao.tipo === "sem-internet"
    ? `<b>Você está sem internet.</b>${dados} O site atualiza sozinho quando a conexão voltar.`
    : `<b>O site está fora do ar no momento.</b>${dados} Ele volta sozinho, sem precisar recarregar. O resultado oficial está em resultados.tse.jus.br.`;
  el.hidden = false; _conexao.mostrado = true;
}
async function vigiarConexao() {
  const caiu = (state.ws && state.ws.readyState !== 1)
    || (state.erroApiEm && Date.now() - state.erroApiEm < 30_000) || !navigator.onLine;
  if (!caiu || document.hidden) {
    if (!caiu) { _conexao.tipo = null; _conexao.desde = 0; }
    renderAvisoConexao();
    return;
  }
  const tipo = await diagnosticarConexao();
  if (tipo !== _conexao.tipo) _conexao.desde = Date.now();
  _conexao.tipo = tipo;
  renderAvisoConexao();
}
setInterval(vigiarConexao, 5000);
setTimeout(vigiarConexao, 1500);  // quem abre já sem internet vê o aviso logo
window.addEventListener("offline", vigiarConexao);
window.addEventListener("online", () => { vigiarConexao(); if (state.ws?.readyState !== 1) conectarWS(); });

// ============ Atualização automática de versão ============
// A página nasce com a versão do front num <meta> (app/main.py). Se um
// deploy mudar o front, recarrega sozinha — na primeira hora em que não
// atrapalha: sem troféu/ficha/menu aberto, sem digitar, fora da tela
// cheia (navegador só volta pra tela cheia com clique). Cargo, UF, turno,
// modo TV e aba já ficam salvos; a rolagem é guardada aqui.
const VERSAO_PAGINA = document.querySelector('meta[name="versao"]')?.content || null;
let _recarregando = false;
async function checarVersao() {
  if (!VERSAO_PAGINA || _recarregando) return;
  let v = null;
  try { v = (await (await fetch("/api/versao", { cache: "no-store" })).json()).versao; } catch (e) { return; }
  if (!v || v === VERSAO_PAGINA) return;
  // Trava de laço: se já recarregou por esta versão e ainda vem a antiga
  // (deploy no meio da troca de instâncias), não insiste.
  try {
    if (sessionStorage.getItem("elei-es:recarregou-para") === v) return;
    sessionStorage.setItem("elei-es:recarregou-para", v);
  } catch (e) {}
  _recarregando = true;
  recarregarQuandoSeguro();
}
function recarregarQuandoSeguro() {
  const ocupado = !document.hidden && (
    document.querySelector(".modal-vitoria")
    || !$("modal-cand")?.classList.contains("oculto")
    || !$("m-sheet")?.classList.contains("oculto")
    || document.activeElement?.matches?.("input, select, textarea"));
  if (ocupado || document.fullscreenElement) { setTimeout(recarregarQuandoSeguro, 5000); return; }
  try { sessionStorage.setItem("elei-es:rolagem", String(window.scrollY)); } catch (e) {}
  location.reload();
}
function restaurarRolagem() {
  try {
    const y = sessionStorage.getItem("elei-es:rolagem");
    if (y == null) return;
    sessionStorage.removeItem("elei-es:rolagem");
    requestAnimationFrame(() => window.scrollTo(0, Number(y) || 0));
  } catch (e) {}
}
setInterval(() => { if (!document.hidden) checarVersao(); }, 120_000);

// Biblioteca de gráficos vem de /static/vendor. Se esse arquivo falhar,
// tenta o CDN (permitido pela CSP) e redesenha mapa e gráfico ao chegar.
if (typeof echarts === "undefined") {
  const sc = document.createElement("script");
  sc.src = "https://cdn.jsdelivr.net/npm/echarts@5.5.1/dist/echarts.min.js";
  sc.onload = () => { try { atualizarMapa(); atualizarGrafHome(); } catch (e) {} };
  document.head.appendChild(sc);
}

// Diagnóstico: "?tela" no endereço mostra o tamanho que o navegador usa
// pra montar a página (TVs costumam usar uma tela "virtual" menor que o
// painel). Não aparece pra ninguém sem o parâmetro.
if (new URLSearchParams(location.search).has("tela")) {
  const b = document.createElement("div");
  b.style.cssText = "position:fixed;left:8px;top:8px;z-index:100000;padding:6px 10px;border-radius:8px;"
    + "background:#ffeb3b;color:#000;font:700 16px/1.2 monospace;pointer-events:none";
  const upd = () => { b.textContent = `${innerWidth}×${innerHeight} · zoom ${devicePixelRatio} · tela ${screen.width}×${screen.height}`; };
  upd(); addEventListener("resize", upd); document.body.appendChild(b);
}
document.addEventListener("visibilitychange", () => { if (!document.hidden) checarVersao(); });
