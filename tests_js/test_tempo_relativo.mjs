// Smoke test dos helpers de tempo relativo e staleness.
// Executa standalone com node — não depende de DOM, só exercita a lógica.

// Mock mínimo: extrai o código do app.js com stubs seguros
import { readFileSync } from "node:fs";
const src = readFileSync("static/app.js", "utf-8");

// Extrai só as funções que queremos testar (regex pelos cabeçalhos conhecidos)
const funcs = ["tempoRelativo", "classeStaleness"];
const codigo = funcs.map(nome => {
  const re = new RegExp(`function ${nome}\\s*\\([^)]*\\)\\s*\\{[\\s\\S]*?\\n\\}`, "m");
  const m = src.match(re);
  if (!m) throw new Error(`função ${nome} não encontrada em static/app.js`);
  return m[0];
}).join("\n\n");

// Avalia as funções isoladamente
const fab = new Function(`${codigo}\nreturn { tempoRelativo, classeStaleness };`);
const { tempoRelativo, classeStaleness } = fab();

let pass = 0, fail = 0;
function t(nome, cond) {
  if (cond) { pass++; console.log(`✓ ${nome}`); }
  else      { fail++; console.error(`✗ ${nome}`); }
}

// tempoRelativo
t("null → null", tempoRelativo(null) === null);
t("iso inválido → null", tempoRelativo("não-é-data") === null);
const agora = new Date().toISOString();
t("agora → 'agora mesmo'", tempoRelativo(agora) === "agora mesmo");
const ha10s = new Date(Date.now() - 10000).toISOString();
t("10s atrás → 'há 10s'", tempoRelativo(ha10s) === "há 10s");
const ha2min = new Date(Date.now() - 125000).toISOString();
t("2min atrás → 'há 2 min'", tempoRelativo(ha2min) === "há 2 min");
const ha3h = new Date(Date.now() - 3 * 3600 * 1000).toISOString();
t("3h atrás → 'há 3 h'", tempoRelativo(ha3h) === "há 3 h");
const ha1dia = new Date(Date.now() - 24 * 3600 * 1000 - 3600000).toISOString();
t("1 dia atrás → 'há 1 dia'", tempoRelativo(ha1dia) === "há 1 dia");
const ha5dias = new Date(Date.now() - 5 * 24 * 3600 * 1000).toISOString();
t("5 dias → 'há 5 dias'", tempoRelativo(ha5dias) === "há 5 dias");

// classeStaleness
t("null → stale-sem", classeStaleness(null) === "stale-sem");
t("agora → stale-fresh", classeStaleness(agora) === "stale-fresh");
t("30s → stale-fresh", classeStaleness(new Date(Date.now() - 30000).toISOString()) === "stale-fresh");
t("2min → stale-warn", classeStaleness(new Date(Date.now() - 120000).toISOString()) === "stale-warn");
t("10min → stale-stale", classeStaleness(new Date(Date.now() - 600000).toISOString()) === "stale-stale");

console.log(`\n${pass} ok · ${fail} fail`);
process.exit(fail ? 1 : 0);
