/**
 * Worker Cloudflare que faz proxy dos endpoints do TSE.
 *
 * Como Cloudflare tem PoPs no Brasil (SP/RJ/Fortaleza), os requests que
 * o Worker faz ao TSE saem de IPs BR e passam pelo Akamai WAF.
 *
 * Mapeamento de paths:
 *   /divulga/*   → https://divulgacandcontas.tse.jus.br/divulga/*
 *   /oficial/*   → https://resultados.tse.jus.br/oficial/*
 *   /fotos/*     → https://divulgacandcontas.tse.jus.br/divulga/rest/v1/candidato/foto/*
 *
 * Deploy: veja instruções em cloudflare-worker/README.md
 */

const ROTAS = {
  "/divulga/":  "https://divulgacandcontas.tse.jus.br/divulga/",
  "/oficial/":  "https://resultados.tse.jus.br/oficial/",
  "/fotos/":    "https://divulgacandcontas.tse.jus.br/divulga/rest/v1/candidato/foto/",
};

const HEADERS_TSE = {
  "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
  "Accept": "application/json, text/plain, */*",
  "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
  "Referer": "https://divulgacandcontas.tse.jus.br/divulga/",
};

export default {
  async fetch(request) {
    const url = new URL(request.url);

    // Endpoint de saúde
    if (url.pathname === "/" || url.pathname === "/health") {
      return new Response(JSON.stringify({
        ok: true,
        rotas: Object.keys(ROTAS),
        uso: "Prefixe seu path com um dos prefixos acima",
      }), { headers: { "content-type": "application/json" } });
    }

    // Encontra a rota que casa
    let alvoBase = null;
    let prefixo = null;
    for (const [pref, base] of Object.entries(ROTAS)) {
      if (url.pathname.startsWith(pref)) {
        alvoBase = base;
        prefixo = pref;
        break;
      }
    }
    if (!alvoBase) {
      return new Response("prefixo não mapeado", { status: 404 });
    }

    // Monta URL do TSE
    const restante = url.pathname.slice(prefixo.length) + url.search;
    const alvo = alvoBase + restante;

    try {
      const resp = await fetch(alvo, {
        method: request.method,
        headers: HEADERS_TSE,
        cf: { cacheTtl: 5 },  // cache curto pra economizar
      });
      // Repassa o corpo e o content-type
      const headers = new Headers();
      headers.set("access-control-allow-origin", "*");
      const ct = resp.headers.get("content-type");
      if (ct) headers.set("content-type", ct);
      return new Response(resp.body, { status: resp.status, headers });
    } catch (e) {
      return new Response(JSON.stringify({ erro: e.message, alvo }),
        { status: 502, headers: { "content-type": "application/json" } });
    }
  },
};
