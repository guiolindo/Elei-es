// Service worker: deixa o site abrir sem internet, com os últimos números
// que a pessoa viu, e atualizar sozinho quando a conexão voltar.
//
// Com internet nada muda: TUDO vem da rede primeiro (rede → cópia guardada
// só se a rede falhar). Não há "cache primeiro" em lugar nenhum, então um
// deploy novo nunca fica preso numa versão velha guardada aqui.
//
// Para desligar em produção: trocar este arquivo por um que chame
// self.registration.unregister() (os navegadores buscam o sw.js de novo
// a cada visita).
const CACHE = "elei-es-v1";
const BASICO = [
  "/",
  "/static/app.js", "/static/app.css", "/static/partidos.js", "/static/mapa-br.js",
  "/static/vendor/echarts-5.5.1.min.js", "/static/br-ufs.geojson",
  "/static/logo.svg", "/static/favicon.svg",
  "/static/fonts/barlow-condensed-700.woff2", "/static/fonts/barlow-condensed-800.woff2",
];
// Rotas que nunca vêm da cópia: hora certa, versão do front, admin.
const NUNCA = /^\/(api\/(hora|versao|poller-status|admin)|admin|ws)\b/;

self.addEventListener("install", (e) => {
  self.skipWaiting();
  // Melhor esforço: se algum arquivo falhar, os outros ficam.
  e.waitUntil(caches.open(CACHE).then(c => Promise.all(BASICO.map(u => c.add(u).catch(() => {})))));
});

self.addEventListener("activate", (e) => {
  e.waitUntil((async () => {
    for (const k of await caches.keys()) if (k !== CACHE) await caches.delete(k);
    await self.clients.claim();
  })());
});

self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== location.origin || NUNCA.test(url.pathname)) return;
  e.respondWith(redePrimeiro(req, url));
});

async function redePrimeiro(req, url) {
  const cache = await caches.open(CACHE);
  const pagina = req.mode === "navigate";
  // Páginas guardadas pelo caminho (sem ?turno=…); API pela URL inteira.
  const chave = pagina ? url.pathname : req;
  try {
    const resp = await fetch(req);
    if (resp.ok && resp.type === "basic") cache.put(chave, resp.clone()).catch(() => {});
    return resp;
  } catch (err) {
    const api = url.pathname.startsWith("/api/");
    const guardado = await cache.match(chave, { ignoreSearch: !api && !pagina })
      || (pagina ? await cache.match("/") : null);
    if (guardado) return guardado;
    return api
      ? new Response('{"erro":"sem conexão"}', { status: 503, headers: { "Content-Type": "application/json" } })
      : Response.error();
  }
}
