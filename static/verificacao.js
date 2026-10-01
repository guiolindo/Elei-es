// Transforma cada link de API em um card com botão "Executar" + viewer
// JSON inline. Mantém o link clicável original pra quem quiser abrir em
// nova aba. Links que não começam com /api não ganham botão (páginas HTML).
(function() {
  const ESC = {"&": "&amp;", "<": "&lt;", ">": "&gt;"};
  const esc = s => String(s).replace(/[&<>]/g, c => ESC[c]);

  function highlightJson(obj) {
    const str = JSON.stringify(obj, null, 2);
    return esc(str).replace(
      /(&quot;[^&]*?&quot;)(\s*:)?|(\btrue\b|\bfalse\b)|(\bnull\b)|(-?\d+\.?\d*)/g,
      (match, s, colon, bool, nul, num) => {
        if (s) return `<span class="${colon ? "j-key" : "j-str"}">${s}</span>${colon || ""}`;
        if (bool) return `<span class="j-bool">${bool}</span>`;
        if (nul) return `<span class="j-null">${nul}</span>`;
        if (num) return `<span class="j-num">${num}</span>`;
        return match;
      }
    );
  }

  async function executar(card, url) {
    const btn = card.querySelector(".verif-exec");
    const antigo = card.querySelector(".verif-resp");
    if (antigo) antigo.remove();
    btn.disabled = true;
    btn.textContent = "executando...";
    const t0 = performance.now();
    try {
      const r = await fetch(url, { headers: { "Accept": "application/json" } });
      const ms = Math.round(performance.now() - t0);
      const ct = r.headers.get("content-type") || "";
      const box = document.createElement("div");
      box.className = "verif-resp";
      const statusClass = r.ok ? "verif-status-ok" : "verif-status-err";
      let meta = `<div class="verif-resp-meta"><span class="${statusClass}">${r.status} ${r.statusText}</span> · ${ms}ms · ${esc(ct)}</div>`;
      if (ct.includes("json")) {
        const data = await r.json();
        box.innerHTML = meta + highlightJson(data);
      } else {
        const txt = await r.text();
        box.innerHTML = meta + esc(txt.slice(0, 4000));
      }
      card.appendChild(box);
    } catch (e) {
      const box = document.createElement("div");
      box.className = "verif-resp erro";
      box.textContent = "erro: " + e.message;
      card.appendChild(box);
    } finally {
      btn.disabled = false;
      btn.textContent = "executar";
    }
  }

  document.querySelectorAll(".verif-card").forEach(card => {
    const link = card.querySelector(".verif-card-url");
    if (!link) return;
    const href = link.getAttribute("href");
    // Só adiciona "executar" em endpoints JSON (/api/* ou /health)
    if (!href.startsWith("/api/") && href !== "/health") return;
    const btn = document.createElement("button");
    btn.className = "verif-exec";
    btn.type = "button";
    btn.textContent = "executar";
    btn.addEventListener("click", () => executar(card, href));
    card.appendChild(btn);
  });
})();
