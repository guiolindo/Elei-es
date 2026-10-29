"""Testes extras dos BUs do 2º turno, sempre comparados com a eleição de referência.

    python scripts/validacao_2t/auditoria_extra.py PASTA 2026 [--ref 2022]

Complementa o auditoria_bu.py. A ideia central: entre o 1º e o 2º turno o país
inteiro se move (votos dos outros candidatos migram, o comparecimento muda),
então uma seção só é estranha se se move MUITO diferente das vizinhas. Para
cada seção calculamos o "resíduo": a mudança dela menos a mudança mediana da
própria zona eleitoral.

  A. Virada brusca: participação do candidato A entre os dois finalistas no
     1T × 2T (ex.: 30/70 → 50/50), resíduo em relação à zona. Contagem por
     faixa e por lado, e as maiores.
  B. Comparecimento e brancos+nulos: mesmo resíduo; comparecimento ≥ 98%.
  C. Eleitor liberado sem biometria (só onde o campo existe): parcela por
     seção no 1T e no 2T, saltos, e se o salto anda junto com ganho de algum
     candidato.
  D. Fechamento tarde: resíduo médio das urnas que fecharam depois das 17h e
     das 18h contra as da MESMA cidade que fecharam no horário.
  E. Chegada do BU ao TSE: atraso entre encerramento e recebimento, e se os
     BUs atrasados pendem para um lado.
"""
import csv, json, statistics as st, sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from auditoria_bu import hora, finalistas  # noqa: E402


def ler(caminho):
    out = {}
    with open(caminho) as f:
        for r in csv.DictReader(f):
            if r["cargo"] != "1":
                continue
            r["votos"] = {k: int(v) for k, v in json.loads(r["votos_json"]).items()}
            r["aptos"] = int(r["aptos"]); r["comparecimento"] = int(r["comparecimento"])
            sb = r.get("sem_biometria", "")
            r["sb"] = int(sb) if sb.isdigit() else None
            out[(r["uf"], int(r["municipio"]), int(r["zona"]), int(r["secao"]))] = r
    return out


def fusos(secoes):
    por_mun = defaultdict(list)
    for k, r in secoes.items():
        ab = hora(r.get("abertura", ""))
        if ab:
            por_mun[k[:2]].append(ab.hour + ab.minute / 60)
    return {m: round(8 - st.median(h)) for m, h in por_mun.items()}


def residuos(itens):
    """itens: {secao: valor}. Devolve {secao: valor − mediana da zona} (zonas com 5+ seções)."""
    zona = defaultdict(list)
    for k, v in itens.items():
        zona[k[:3]].append(v)
    med = {z: st.median(vs) for z, vs in zona.items() if len(vs) >= 5}
    return {k: v - med[k[:3]] for k, v in itens.items() if k[:3] in med}


def resumo(xs):
    q = st.quantiles(xs, n=1000)
    return f"desvio {st.pstdev(xs)*100:.2f}pp · 0,1% {q[0]*100:+.1f} · 99,9% {q[-1]*100:+.1f}"


def media(xs):
    if len(xs) < 2:
        return "—"
    m = st.mean(xs); ep = st.pstdev(xs) / len(xs) ** 0.5
    return f"{m*100:+.2f}pp (±{1.96*ep*100:.2f}; n={len(xs):,})".replace(",", ".")


def rodar(pasta, ano, n_top=15):
    s1 = ler(f"{pasta}/{ano}_1t.csv"); s2 = ler(f"{pasta}/{ano}_2t.csv")
    (a, b), _ = finalistas(s2)
    off = fusos(s2)
    P = lambda *x: print(*x, flush=True)
    P(f"\n================ {ano} · testes extras (A = {a}, B = {b}) ================")

    sh1, sh2, ds, dc, dbn, comps = {}, {}, {}, {}, {}, {}
    for k, r2 in s2.items():
        r1 = s1.get(k)
        if not r1:
            continue
        v1 = r1["votos"].get(a, 0) + r1["votos"].get(b, 0)
        v2 = r2["votos"].get(a, 0) + r2["votos"].get(b, 0)
        if v1 < 30 or v2 < 30 or r1["aptos"] < 50:
            continue
        sh1[k] = r1["votos"].get(a, 0) / v1; sh2[k] = r2["votos"].get(a, 0) / v2
        ds[k] = sh2[k] - sh1[k]
        dc[k] = r2["comparecimento"] / r2["aptos"] - r1["comparecimento"] / r1["aptos"]
        bn = lambda r: (r["votos"].get("95", 0) + r["votos"].get("96", 0)) / max(r["comparecimento"], 1)
        dbn[k] = bn(r2) - bn(r1)
        comps[k] = r2["comparecimento"] / r2["aptos"]
    rs, rc, rbn = residuos(ds), residuos(dc), residuos(dbn)
    P("seções comparadas (30+ votos nos finalistas nos dois turnos, zona com 5+ seções): " + f"{len(rs):,}".replace(",", "."))

    # A
    P("\nA) Virada brusca na participação de A entre os finalistas (1T → 2T)")
    P(f"   mudança bruta: média {st.mean(ds.values())*100:+.2f}pp · {resumo(list(ds.values()))}")
    P(f"   resíduo (descontada a mudança da zona): {resumo(list(rs.values()))}")
    for lim in (0.10, 0.15, 0.20, 0.30):
        pa = sum(1 for v in rs.values() if v >= lim); pb = sum(1 for v in rs.values() if v <= -lim)
        P(f"   resíduo ≥ {lim*100:.0f}pp: {pa+pb:>5} seções · para A {pa} · para B {pb}")
    vir_a = sum(1 for k in rs if sh1[k] <= 0.35 and sh2[k] >= 0.50)
    vir_b = sum(1 for k in rs if sh1[k] >= 0.65 and sh2[k] <= 0.50)
    P(f"   viradas tipo 35/65 → empate ou mais: para A {vir_a} · para B {vir_b}")
    top = sorted(rs, key=lambda k: -abs(rs[k]))[:n_top]
    P("   maiores resíduos (UF mun zona seção: A no 1T → 2T, resíduo, aptos):")
    for k in top:
        P(f"     {k[0]} {k[1]} {k[2]} {k[3]}: {sh1[k]*100:.0f}% → {sh2[k]*100:.0f}% ({rs[k]*100:+.0f}pp), aptos {s2[k]['aptos']}")

    # B
    P("\nB) Comparecimento e brancos+nulos")
    P(f"   resíduo do comparecimento: {resumo(list(rc.values()))}")
    P(f"   resíduo de brancos+nulos: {resumo(list(rbn.values()))}")
    alto = [k for k, c in comps.items() if c >= 0.98 and s2[k]["aptos"] >= 50]
    P(f"   seções com comparecimento ≥ 98% (50+ aptos): {len(alto)}")
    c_rs = [rs[k] for k in rc if rc[k] >= 0.15 and k in rs]
    P(f"   seções cujo comparecimento subiu 15pp+ acima da zona: {len(c_rs)} · resíduo médio de A nelas: {media(c_rs)}")

    # C
    P("\nC) Eleitores liberados sem biometria")
    com = [k for k in rs if s2[k]["sb"] is not None and s1[k]["sb"] is not None]
    if not com:
        P("   campo não disponível nesta eleição")
    else:
        p1 = {k: s1[k]["sb"] / max(s1[k]["comparecimento"], 1) for k in com}
        p2 = {k: s2[k]["sb"] / max(s2[k]["comparecimento"], 1) for k in com}
        tot1 = sum(s1[k]["sb"] for k in com); tot2 = sum(s2[k]["sb"] for k in com)
        P(f"   total sem biometria: 1T {tot1:,} · 2T {tot2:,} ({tot2/sum(s2[k]['comparecimento'] for k in com)*100:.2f}% do comparecimento)".replace(",", "."))
        P(f"   parcela por seção no 2T: mediana {st.median(p2.values())*100:.1f}% · 99% {st.quantiles(list(p2.values()), n=100)[-1]*100:.1f}%")
        rsb = residuos({k: p2[k] - p1[k] for k in com})
        P(f"   resíduo do salto (2T − 1T, descontada a zona): {resumo(list(rsb.values()))}")
        for lim in (0.10, 0.20, 0.30):
            n = [k for k, v in rsb.items() if v >= lim]
            P(f"   salto ≥ {lim*100:.0f}pp acima da zona: {len(n)} seções · resíduo médio de A nelas: {media([rs[k] for k in n])}")
        xs = [rsb[k] for k in rsb]; ys = [rs[k] for k in rsb]
        P(f"   correlação salto sem biometria × resíduo de A: {st.correlation(xs, ys):+.3f}")
        alta = [k for k in com if p2[k] >= 0.5 and s2[k]["comparecimento"] >= 50]
        P(f"   seções com metade ou mais sem biometria no 2T: {len(alta)} · resíduo médio de A: {media([rs[k] for k in alta])}")
        for k in sorted(rsb, key=lambda k: -rsb[k])[:8]:
            P(f"     {k[0]} {k[1]} {k[2]} {k[3]}: sem biometria {p1[k]*100:.0f}% → {p2[k]*100:.0f}%, A {sh1[k]*100:.0f}% → {sh2[k]*100:.0f}% ({rs[k]*100:+.0f}pp)")

    # D
    P("\nD) Urnas que fecharam tarde × mesma cidade no horário")
    enc = {}
    for k in rs:
        e = hora(s2[k]["encerramento"])
        if e:
            e = e + timedelta(hours=off.get(k[:2], 0))
            enc[k] = e.hour * 60 + e.minute
    for corte, nome in ((17 * 60 + 15, "depois das 17h15"), (18 * 60, "depois das 18h"), (19 * 60, "depois das 19h")):
        cid = defaultdict(lambda: ([], []))
        for k, m in enc.items():
            cid[k[:2]][0 if m >= corte else 1].append(k)
        t, n_, tc, nc = [], [], [], []
        for tarde, cedo in cid.values():
            if tarde and cedo:
                t += [rs[k] for k in tarde]; n_ += [rs[k] for k in cedo]
                tc += [rc[k] for k in tarde if k in rc]; nc += [rc[k] for k in cedo if k in rc]
        if t:
            P(f"   {nome}: resíduo de A {media(t)} × no horário {media(n_)} · resíduo do comparecimento {media(tc)} × {media(nc)}")

    # E
    P("\nE) Tempo entre o fechamento da urna e a chegada do BU ao TSE")
    atraso = {}
    for k in rs:
        e, rcb = hora(s2[k]["encerramento"]), hora(s2[k]["recebido"])
        if e and rcb:
            atraso[k] = (rcb - (e + timedelta(hours=off.get(k[:2], 0)))).total_seconds() / 3600
    if atraso:
        q = st.quantiles(atraso.values(), n=100)
        P(f"   mediana {st.median(atraso.values()):.1f} h · 90% {q[89]:.1f} h · 99% {q[98]:.1f} h · negativo (chegou antes de fechar): {sum(v < 0 for v in atraso.values())}")
        for lim in (3, 6, 24):
            n = [k for k, v in atraso.items() if v >= lim]
            P(f"   chegaram {lim}h+ depois: {len(n)} · resíduo médio de A: {media([rs[k] for k in n])}")


if __name__ == "__main__":
    pasta, ano = sys.argv[1], sys.argv[2]
    rodar(pasta, ano)
    if "--ref" in sys.argv:
        rodar(pasta, sys.argv[sys.argv.index("--ref") + 1])
