"""Teste de viés da estimativa do 2T (não altera o motor).

Usa o simulador (sim.py, nesta pasta) e o motor de produção
(math_engine/projecao.py). Em cada ponto da apuração a projeção vê só o
snapshot daquele instante, um snapshot anterior e a base do 1T. O
resultado final só é usado pra pontuar.

Cenários regionais novos: o erro da base do 1T (migração dos eleitores
dos eliminados) tem um componente por REGIÃO, comum a todos os estados
da região — o que o motor não modela (ele supõe erro independente por
estado + swing nacional).

Convenção: A = candidato forte no Nordeste/Norte (geografia Lula 2022);
B = forte no Sul/Centro-Oeste. Sul e Sudeste apuram primeiro no sim.
"""
import sys, os, numpy as np
AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(AQUI, "..", "..")); sys.path.insert(0, AQUI)
import sim
from math_engine import projecao as P

REG_NOME = {u: sim.UFS[u][2] for u in sim.NAMES}
_gen_orig = sim.gen_election

# efeito regional na relação 2T real × base 1T (positivo = A melhor que a base)
REGIONAL = {
    "base": None, "hard": None, "adverso": None,
    # sinal aleatório por região a cada eleição, desvio 3 pts
    "regional_aleatorio": ("aleatorio", "base", 0.03),
    "adverso_regional": ("aleatorio", "adverso", 0.03),
    # dirigido: o ajuste medido cedo (Sul/Sudeste/CO) não vale pro N/NE
    "dirigido_pro_A": ("fixo", "base", {"S": -0.02, "SE": -0.02, "CO": -0.02, "NE": +0.02, "N": +0.02, "EX": 0}),
    "dirigido_pro_B": ("fixo", "base", {"S": +0.02, "SE": +0.02, "CO": +0.02, "NE": -0.02, "N": -0.02, "EX": 0}),
}

def base_params(scen):
    r = REGIONAL[scen]
    return sim.SCEN[scen if r is None else r[1]]

def gen(rng, Pp, scen):
    u, E, T, A, V, prior = _gen_orig(rng, Pp)
    r = REGIONAL[scen]
    if r is not None:
        if r[0] == "aleatorio":
            eff = {g: rng.normal(0, r[2]) for g in ("S", "SE", "CO", "NE", "N")}; eff["EX"] = 0.0
        else:
            eff = r[2]
        for i, nome in enumerate(sim.NAMES):
            prior[i] = float(np.clip(prior[i] - eff[REG_NOME[nome]], .01, .99))
    return u, E, T, A, V, prior

def conv(lst, espelho=False):
    out = []
    for d in lst:
        va, vv, pr = int(d["votos_a"]), int(d["validos"]), d["prior_a"]
        if espelho:
            va = vv - va; pr = None if pr is None else 1 - pr
        out.append(P.Estrato(int(d["eleitorado"]), int(d["eleitorado_tot"]), vv, va,
                             int(d["secoes"]), int(d["secoes_tot"]), pr))
    return out

CPS = [10, 20, 30, 50, 70, 90]

def run(n, seed, scen):
    Pp = base_params(scen); rng = np.random.default_rng(seed)
    R = {c: dict(err=[], cov=[], p=[], y=[], exib=[], espelho_dif=[]) for c in CPS}
    for _ in range(n):
        u, E, T, A, V, prior = gen(rng, Pp, scen)
        snaps, tot = sim.snapshots(u, E, T, A, V, Pp["step"])
        sim.TOT_E = tot["E"]; sim.TOT_S = tot["S"]
        truth = tot["A"].sum() / tot["V"].sum(); St = tot["S"].sum()
        pcts = np.array([sim.nat(s)["S"] * 100 / St for s in snaps])
        for c in CPS:
            j = int(np.searchsorted(pcts, c)); s = snaps[j]
            jb = int(np.searchsorted(pcts, 0.6 * pcts[j]))
            ea = sim.estratos(s, prior, True)
            eb = sim.estratos(snaps[jb], prior, True) if jb < j else None
            r = P.projetar_2t(conv(ea), conv(eb) if eb else None)
            if r is None: continue
            rm = P.projetar_2t(conv(ea, True), conv(eb, True) if eb else None)
            d = R[c]
            d["err"].append(r.pct_a - truth * 100)
            d["cov"].append(r.ic95_a[0] <= truth * 100 <= r.ic95_a[1])
            d["p"].append(min(max(r.p_vitoria_a, .01), .99)); d["y"].append(float(truth > .5))
            d["exib"].append(r.exibir_probabilidade)
            d["espelho_dif"].append(abs((r.pct_a + rm.pct_a) - 100) + abs(r.p_vitoria_a - rm.p_vitoria_b) * 100)
    return R

def relatorio(scen, R, n):
    print(f"\n=== {scen} ({n} eleições) ===")
    print(" apur | estim.A>real | estim.B>real | erro assinado A (IC95)  | erro abs | IC95 cobre | espelho")
    for c in CPS:
        d = R[c]; e = np.array(d["err"])
        if not len(e): continue
        se = e.std(ddof=1) / np.sqrt(len(e))
        print(f" {c:3d}% | {np.mean(e > 0)*100:10.1f}% | {np.mean(e < 0)*100:10.1f}% | {e.mean():+6.2f} pp ({e.mean()-1.96*se:+.2f} a {e.mean()+1.96*se:+.2f}) | {np.abs(e).mean():5.2f} pp | {np.mean(d['cov'])*100:6.1f}% | {max(d['espelho_dif']):.1e}")
    # probabilidade: só onde o site mostra (>=50% apurado)
    p = np.concatenate([np.array(R[c]["p"])[np.array(R[c]["exib"], bool)] for c in CPS if R[c]["p"]])
    y = np.concatenate([np.array(R[c]["y"])[np.array(R[c]["exib"], bool)] for c in CPS if R[c]["p"]])
    if not len(p): return
    fav = np.maximum(p, 1 - p); hit = np.where(p >= .5, y, 1 - y)
    print(f" chance (pontos >=50% apurado, n={len(p)}): prob. média do favorito {fav.mean()*100:.1f}% x acerto real {hit.mean()*100:.1f}%  -> excesso de confiança {(fav.mean()-hit.mean())*100:+.1f} pts")
    for nome, m in (("A favorito", p >= .5), ("B favorito", p < .5)):
        if m.sum(): print(f"   {nome}: n={m.sum():4d} prob. média {fav[m].mean()*100:5.1f}% | acerto real {hit[m].mean()*100:5.1f}% | diferença {(fav[m].mean()-hit[m].mean())*100:+5.1f}")
    for lo, hi in ((.5, .7), (.7, .9), (.9, .99), (.99, 1.01)):
        m = (fav >= lo) & (fav < hi)
        if m.sum():
            ob = hit[m].mean(); se = np.sqrt(max(ob*(1-ob), 1e-9) / m.sum())
            print(f"   faixa {int(lo*100)}–{min(int(hi*100),99)}%: previsto {fav[m].mean()*100:5.1f}% | real {ob*100:5.1f}% ±{1.96*se*100:.1f} | n={m.sum()}" + ("  <- confiante demais" if fav[m].mean() - ob > 1.96*se else ""))

if __name__ == "__main__":
    # python scripts/validacao_2t/vies.py 2000 2610 base,adverso,regional_aleatorio
    if os.environ.get("SEM_COMPARECIMENTO_ORDEM") == "1":
        # Desliga só o comparecimento menor nas seções tardias do N/NE.
        import inspect, textwrap
        src = inspect.getsource(sim.gen_election).replace(' - 0.1 * z * (reg in ("N", "NE"))', "")
        exec(textwrap.dedent(src), sim.__dict__)
        _gen_orig = sim.gen_election
    n = int(sys.argv[1]); seed = int(sys.argv[2])
    for scen in sys.argv[3].split(","):
        relatorio(scen, run(n, seed, scen), n)
