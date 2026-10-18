"""Resume backtest_{ano}_{ordem}.json: Presidente por ano e Governadores
agregados (cada disputa é uma amostra independente; previsões da mesma
disputa não são).

    python scripts/validacao_2t/resumo_backtest.py DADOS backtest_2018_encerramento.json backtest_2022_recebido.json
"""
import json, os, sys
import numpy as np

CPS = [10, 20, 30, 50, 70, 90]


def boot(ids, val, n=4000, seed=0):
    ids = np.asarray(ids); val = np.asarray(val, float)
    u, inv = np.unique(ids, return_inverse=True)
    s = np.bincount(inv, weights=val); c = np.bincount(inv)
    w = np.random.default_rng(seed).multinomial(len(u), np.full(len(u), 1 / len(u)), size=n)
    est = (w @ s) / np.maximum(w @ c, 1)
    return np.percentile(est, [2.5, 97.5]), len(u)


def main():
    pasta = sys.argv[1]
    gov = []   # (disputa, linha)
    for arq in sys.argv[2:]:
        dados = json.load(open(os.path.join(pasta, arq)))
        rot = arq.replace("backtest_", "").replace(".json", "")
        p = dados["Presidente"]
        print(f"\n## Presidente {rot}: real A ({p['a']}) = {p['verdade']:.2f}%")
        print("  apur | erro A  | IC95 cobre | largura | chance A | comparec. apurado−faltante | erro válidos restantes")
        for l in p["linhas"]:
            if l["cp"] in CPS:
                ch = f"{l['p']*100:5.1f}%" if l["exibir"] else "  —  "
                cob = "sim" if l["lo"] <= l["real"] <= l["hi"] else "NÃO"
                print(f"  {l['cp']:3d}% | {l['erro']:+6.2f} | {cob:10s} | {l['hi']-l['lo']:5.2f}   | {ch}   | {l['dif_comp']:+5.2f} pp                   | {l['erro_validos_rest']:+6.2f}%")
        for nome, d in dados.items():
            if nome.startswith("Governador"):
                for l in d["linhas"]:
                    gov.append((f"{rot} {nome}", d, l))
    if not gov:
        return
    disputas = sorted({g[0] for g in gov})
    print(f"\n## Governadores ({len(disputas)} disputas independentes; A = líder do 1T)")
    print("  apur | disputas | erro assinado A (IC95)   | erro abs | IC95 cobre (IC95)       | largura | comparec. apurado−faltante")
    for cp in CPS:
        L = [(k, l) for k, _, l in gov if l["cp"] == cp]
        if not L:
            continue
        e = np.array([l["erro"] for _, l in L])
        cob = np.array([l["lo"] <= l["real"] <= l["hi"] for _, l in L], float)
        se = e.std(ddof=1) / np.sqrt(len(e)) if len(e) > 1 else 0
        (ca, cb), _ = boot([k for k, _ in L], cob)
        dc = np.array([l["dif_comp"] for _, l in L])
        print(f"  {cp:3d}% | {len(L):8d} | {e.mean():+5.2f} ({e.mean()-1.96*se:+.2f} a {e.mean()+1.96*se:+.2f}) | {np.abs(e).mean():5.2f}    | {cob.mean()*100:5.1f}% ({ca*100:.0f}–{cb*100:.0f}%) | {np.mean([l['hi']-l['lo'] for _, l in L]):5.2f}   | {dc.mean():+.2f} pp")
    # chance: Governadores + Presidentes, só onde o site mostra
    pts = [(k, l) for k, _, l in gov if l["exibir"]]
    for arq in sys.argv[2:]:
        d = json.load(open(os.path.join(pasta, arq)))["Presidente"]
        pts += [(arq + " Presidente", l) for l in d["linhas"] if l["exibir"]]
    k = [x[0] for x in pts]
    p = np.array([min(max(l["p"], .01), .99) for _, l in pts]); y = np.array([float(l["real"] > 50) for _, l in pts])
    fav = np.maximum(p, 1 - p); hit = np.where(p >= .5, y, 1 - y)
    print(f"\n## Chance (≥50% apurado): {len(p)} previsões de {len(set(k))} disputas")
    print("  faixa  | previsões | disputas | previsto | real (IC95 por disputa)")
    for lo, hi in ((.5, .7), (.7, .9), (.9, .99), (.99, 1.01)):
        m = (fav >= lo) & (fav < hi)
        if not m.sum():
            continue
        (a, b), nd = boot(np.array(k)[m], hit[m])
        print(f"  {int(lo*100)}–{min(int(hi*100), 99)}% | {m.sum():9d} | {nd:8d} | {fav[m].mean()*100:6.1f}%  | {hit[m].mean()*100:5.1f}% ({a*100:.0f}–{b*100:.0f}%)")
    erros = [(k_, l) for k_, l in pts if (l["p"] >= .5) != (l["real"] > 50)]
    print(f"  previsões com favorito errado: {len(erros)} em {len({x[0] for x in erros})} disputas")
    for k_, l in erros[:12]:
        print(f"    {k_} a {l['cp']}%: chance A {l['p']*100:.0f}%, real A {l['real']:.2f}%")


if __name__ == "__main__":
    main()
