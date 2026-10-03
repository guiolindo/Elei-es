// Verificação por seção eleitoral (BU). Faz GET em /api/apuracao/bu
// e renderiza o resultado inline. Sem framework — vanilla, 60 linhas.
const $ = id => document.getElementById(id);
const fmt = new Intl.NumberFormat("pt-BR").format;

async function buscar(e) {
  e.preventDefault();
  const btn = $("btn-buscar");
  const resp = $("resp");
  const uf = $("uf").value;
  const mu = $("municipio").value.trim();
  const zn = $("zona").value.trim();
  const se = $("secao").value.trim();
  const cargo = $("cargo").value;
  const turno = $("turno").value;
  if (!uf || !mu || !zn || !se) return;
  btn.disabled = true;
  btn.textContent = "Buscando...";
  resp.classList.remove("visivel");
  try {
    const url = `/api/apuracao/bu?uf=${encodeURIComponent(uf)}&municipio=${encodeURIComponent(mu)}&zona=${encodeURIComponent(zn)}&secao=${encodeURIComponent(se)}&cargo=${cargo}&turno=${turno}`;
    const r = await fetch(url, { headers: { Accept: "application/json" } });
    const d = await r.json();
    render(d);
    resp.classList.add("visivel");
  } catch (err) {
    resp.innerHTML = `<div class="urna-erro">Erro ao buscar: ${err.message}</div>`;
    resp.classList.add("visivel");
  } finally {
    btn.disabled = false;
    btn.textContent = "Buscar BU";
  }
}

function render(d) {
  const resp = $("resp");
  if (!d.disponivel) {
    resp.innerHTML = `<div class="urna-erro">
      <strong>Não encontrado.</strong> ${d.motivo || "A seção pode não ter sido totalizada ainda, ou os códigos estão incorretos."}
      ${d.url_imagem_bu ? `<br><br><a class="urna-img-link" href="${d.url_imagem_bu}" target="_blank" rel="noopener">Tentar imagem do BU direto no TSE →</a>` : ""}
    </div>`;
    return;
  }
  const t = d.totais || {};
  const cards = [
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
      <span class="urna-cand-num">${c.sq_candidato || "—"}</span>
      <span class="urna-cand-nome">${c.sq_candidato}</span>
      <span class="urna-cand-votos">${fmt(c.votos)} · ${c.pct_validos.toFixed(2)}%</span>
    </div>`
  ).join("");
  resp.innerHTML = `
    <h2>Seção ${d.secao} · Zona ${d.zona} · ${d.uf} · Município ${d.municipio}</h2>
    <div class="urna-stats">${cards}</div>
    ${cands ? `<div class="urna-cands"><h3 style="font-size:14px;margin:16px 0 8px;color:var(--muted);text-transform:uppercase;letter-spacing:.5px">Candidatos</h3>${cands}</div>` : ""}
    <a class="urna-img-link" href="${d.url_imagem_bu}" target="_blank" rel="noopener">
      Ver imagem assinada do BU original (JPEG do TSE) →
    </a>
  `;
}

$("form-urna").addEventListener("submit", buscar);
