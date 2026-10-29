"""Baixa e decodifica os BUs do 2º turno 2026 (pleito 3221) seção a seção.

Uso: python scripts/validacao_2t/baixar_bu_secoes.py SAIDA_DIR UF [UF ...]
Grava SAIDA_DIR/2t_{uf}.csv no formato de baixar_bu.py. Retoma de onde parou
(seções já gravadas são puladas).
"""
import asyncio, csv, json, os, sys
import httpx

BASE = "https://resultados.tse.jus.br/oficial/ele2026/arquivo-urna/3221"
H = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Accept": "*/*", "Referer": "https://resultados.tse.jus.br/",
}
COLS = ["cargo", "uf", "municipio", "zona", "secao", "recebido", "encerramento", "aptos", "comparecimento", "votos_json",
        "abertura", "emissao", "tipo_urna", "agregadas", "sem_biometria"]


def tlv(b, i):
    t = b[i]; i += 1
    if t & 0x1f == 0x1f:
        while b[i] & 0x80: i += 1
        i += 1
    l = b[i]; i += 1
    if l & 0x80:
        n = l & 0x7f; l = int.from_bytes(b[i:i + n], "big"); i += n
    return t, i, l


def arvore(b, i=0, end=None):
    """Lista de (tag, valor) onde valor é lista (construído) ou bytes."""
    end = len(b) if end is None else end
    out = []
    while i < end:
        t, s, l = tlv(b, i)
        out.append((t, arvore(b, s, s + l) if t & 0x20 else b[s:s + l]))
        i = s + l
    return out


def num(v): return int.from_bytes(v, "big", signed=True)
def txt(v): return v.decode("latin-1")


def hora(s):  # 20261025T170233 -> 2026-10-25 17:02:33
    s = txt(s); return f"{s[0:4]}-{s[4:6]}-{s[6:8]} {s[9:11]}:{s[11:13]}:{s[13:15]}"


def decodifica(dat):
    env = arvore(dat)[0][1]
    conteudo = [v for t, v in env if t == 0x04][-1]
    bu = arvore(conteudo)[0][1]
    emissao = abertura = encerramento = ""; comp_total = None; ident = []; resultados = None
    for t, v in bu:
        if t == 0x1b and emissao == "": emissao = hora(v)
        elif t == 0xa0 and len(v) == 2 and all(x[0] == 0x1b for x in v):
            abertura, encerramento = hora(v[0][1]), hora(v[1][1])
        elif t == 0x02: comp_total = num(v)
        elif t == 0xa1: ident = [num(x[1]) for x in v]
        elif t == 0x30 and emissao and resultados is None: resultados = v
    out = []
    for t, eleicao in resultados or []:
        ints = [num(x[1]) for x in eleicao if x[0] == 0x02]
        aptos = ints[1]
        for _, rv in [x for x in eleicao if x[0] == 0x30][0][1]:
            comp = [num(x[1]) for x in rv if x[0] == 0x02][0]
            for _, tvc in [x for x in rv if x[0] == 0x30][0][1]:
                cargo = num([x for x in tvc if x[0] == 0x81][0][1])
                votos = {}
                for _, vv in [x for x in tvc if x[0] == 0x30][0][1]:
                    tipo = num([x for x in vv if x[0] == 0x81][0][1])
                    q = num([x for x in vv if x[0] == 0x82][0][1])
                    if tipo == 1:
                        cod = [x for x in vv if x[0] == 0xa3][0][1]
                        k = str(num(cod[1][1]))
                    else:
                        k = {2: "95", 3: "96"}.get(tipo, f"t{tipo}")
                    votos[k] = votos.get(k, 0) + q
                out.append((cargo, aptos, comp, votos))
    return dict(emissao=emissao, abertura=abertura, encerramento=encerramento,
                comp_total=comp_total, ident=ident, cargos=out)


async def get(cli, url, binario=False):
    for tent in range(8):
        try:
            r = await cli.get(url)
            if r.status_code == 200:
                return r.content if binario else r.json()
            if r.status_code == 404:
                return None
            if r.status_code == 429:
                await asyncio.sleep(10 + 10 * tent); continue
        except Exception:
            pass
        await asyncio.sleep(1 + 2 * tent)
    raise RuntimeError(f"falhou {url}")


async def secao(cli, sem, uf, mu, zn, ns, w, f, erros):
    async with sem:
        try:
            pre = f"{BASE}/dados/{uf}/{mu}/{zn}/{ns}"
            aux = await get(cli, f"{pre}/p003221-{uf}-m{mu}-z{zn}-s{ns}-aux.json")
            if not aux or not aux.get("hashes"):
                erros.append((uf, mu, zn, ns, "sem aux")); return
            h = aux["hashes"][-1]
            nm = next((a["nm"] for a in h.get("arq", []) if a.get("tp") == "bu" or a["nm"].endswith("-bu.dat")), None)
            if not nm:
                erros.append((uf, mu, zn, ns, f"sem bu ({h.get('st')})")); return
            dat = await get(cli, f"{pre}/{h['hash']}/{nm}", binario=True)
            d = decodifica(dat)
            dr = h.get("dr", ""); hr = h.get("hr", "")
            rec = f"{dr[6:10]}-{dr[3:5]}-{dr[0:2]} {hr}" if dr else ""
            sb = d["ident"][2] if len(d["ident"]) >= 3 else ""
            for cargo, aptos, comp, votos in d["cargos"]:
                w.writerow([cargo, uf.upper(), int(mu), int(zn), int(ns), rec, d["encerramento"], aptos, comp,
                            json.dumps(votos, separators=(",", ":")), d["abertura"], d["emissao"],
                            "Apurada", "#NULO#", sb])
            f.flush()
        except Exception as e:
            erros.append((uf, mu, zn, ns, repr(e)[:120]))


async def main(saida, ufs):
    lim = httpx.Limits(max_connections=48, max_keepalive_connections=48)
    async with httpx.AsyncClient(headers=H, timeout=20, limits=lim, http2=True) as cli:
        for uf in ufs:
            cs = await get(cli, f"{BASE}/config/{uf}/{uf}-p003221-cs.json")
            alvo = os.path.join(saida, f"2t_{uf}.csv")
            feitas = set()
            if os.path.exists(alvo):
                for r in csv.DictReader(open(alvo)):
                    feitas.add((int(r["municipio"]), int(r["zona"]), int(r["secao"])))
            novo = not os.path.exists(alvo)
            f = open(alvo, "a", newline=""); w = csv.writer(f)
            if novo: w.writerow(COLS)
            sem = asyncio.Semaphore(48); erros = []; tarefas = []
            for a in cs["abr"]:
                for m in a["mu"]:
                    for z in m["zon"]:
                        for s in z["sec"]:
                            if (int(m["cd"]), int(z["cd"]), int(s["ns"])) in feitas: continue
                            tarefas.append(secao(cli, sem, uf, m["cd"], z["cd"], s["ns"], w, f, erros))
            print(uf, "seções a baixar:", len(tarefas), "já feitas:", len(feitas), flush=True)
            for i in range(0, len(tarefas), 2000):
                await asyncio.gather(*tarefas[i:i + 2000])
                print(uf, min(i + 2000, len(tarefas)), "/", len(tarefas), "erros", len(erros), flush=True)
            f.close()
            with open(os.path.join(saida, f"erros_{uf}.json"), "w") as fe:
                json.dump(erros, fe)


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1], [u.lower() for u in sys.argv[2:]]))
