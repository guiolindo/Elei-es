"""Margem com componente regional (protótipo, ρ em grade) e calibração da
chance contando ELEIÇÕES independentes (bootstrap por eleição).

    python scripts/validacao_2t/vies2.py 2000 2610 base,adverso,...
"""
import os, sys
import numpy as np
AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(AQUI, "..", "..")); sys.path.insert(0, AQUI)
import sim, vies
from math_engine import projecao as P
from projecao_regional import projetar_2t_regional

RHOS = [0.0, 0.25, 0.5, 0.75]
CPS = [10, 30, 50, 70, 90]
REGIOES = [sim.UFS[u][2] for u in sim.NAMES]


def run(n, seed, scen):
    Pp = vies.base_params(scen); rng = np.random.default_rng(seed)
    cob = {(c, r): [] for c in CPS for r in RHOS}
    larg = {(c, r): [] for c in CPS for r in RHOS}
    prob = []  # (eleicao, checkpoint, p_a, venceu_a) só onde o site mostra
    dif0 = 0.0
    for k in range(n):
        u, E, T, A, V, prior = vies.gen(rng, Pp, scen)
        snaps, tot = sim.snapshots(u, E, T, A, V, Pp["step"])
        sim.TOT_E = tot["E"]; sim.TOT_S = tot["S"]
        truth = 100 * tot["A"].sum() / tot["V"].sum(); St = tot["S"].sum()
        pcts = np.array([sim.nat(s)["S"] * 100 / St for s in snaps])
        for c in CPS:
            j = int(np.searchsorted(pcts, c))
            jb = int(np.searchsorted(pcts, 0.6 * pcts[j]))
            ea = vies.conv(sim.estratos(snaps[j], prior, True))
            eb = vies.conv(sim.estratos(snaps[jb], prior, True)) if jb < j else None
            ref = P.projetar_2t(ea, eb)
            if ref is None:
                continue
            for rho in RHOS:
                r = projetar_2t_regional(ea, REGIOES, eb, rho)
                if rho == 0:
                    dif0 = max(dif0, abs(r["pct_a"] - ref.pct_a), abs(r["sd_pp"] - ref.sd_pp))
                cob[(c, rho)].append(r["ic95_a"][0] <= truth <= r["ic95_a"][1])
                larg[(c, rho)].append(r["ic95_a"][1] - r["ic95_a"][0])
            if ref.exibir_probabilidade:
                prob.append((k, c, min(max(ref.p_vitoria_a, .01), .99), float(truth > 50)))
    return cob, larg, np.array(prob), dif0


def boot_freq(eleicao, acerto, n_boot=2000, seed=0):
    """IC95 da frequência de acerto reamostrando eleições inteiras."""
    ids, inv = np.unique(eleicao, return_inverse=True)
    soma = np.bincount(inv, weights=acerto); cont = np.bincount(inv)
    rng = np.random.default_rng(seed)
    w = rng.multinomial(len(ids), np.full(len(ids), 1 / len(ids)), size=n_boot)
    est = (w @ soma) / np.maximum(w @ cont, 1)
    a, b = np.percentile(est, [2.5, 97.5])
    if a == b:
        # Todas acertaram (ou todas erraram): bootstrap degenera. Wilson
        # com n = nº de eleições (cada eleição conta uma vez).
        f, ne, z = soma.sum() / cont.sum(), len(ids), 1.96
        c = (f + z * z / (2 * ne)) / (1 + z * z / ne)
        h = z * np.sqrt(f * (1 - f) / ne + z * z / (4 * ne * ne)) / (1 + z * z / ne)
        a, b = c - h, c + h
    return (a, b), len(ids)


def relatorio(scen, cob, larg, prob, dif0, n):
    print(f"\n=== {scen} ({n} eleições) — ρ=0 igual ao motor: dif máx {dif0:.1e} ===")
    print(" IC95: cobertura % / largura média pp")
    print(" apur | " + " | ".join(f"ρ={r:<4}" + " " * 9 for r in RHOS))
    for c in CPS:
        print(f" {c:3d}% | " + " | ".join(
            f"{np.mean(cob[(c, r)])*100:5.1f}% / {np.mean(larg[(c, r)]):4.2f}" for r in RHOS))
    if not len(prob):
        return
    k, c, p, y = prob.T
    fav = np.maximum(p, 1 - p); hit = np.where(p >= .5, y, 1 - y)
    print(f" Chance (só ≥50% apurado): {len(p)} previsões de {len(np.unique(k))} eleições")
    print("  faixa     | previsões | eleições | previsto | real (IC95 por eleição)")
    for lo, hi in ((.5, .6), (.6, .7), (.7, .8), (.8, .9), (.9, .99), (.99, 1.01)):
        m = (fav >= lo) & (fav < hi)
        if m.sum() < 5:
            continue
        (a, b), ne = boot_freq(k[m], hit[m])
        ob, pr = hit[m].mean(), fav[m].mean()
        marca = "  confiante demais" if pr > b else ("  cautelosa" if pr < a else "")
        print(f"  {int(lo*100):2d}–{min(int(hi*100), 99):2d}%    | {m.sum():9d} | {ne:8d} | {pr*100:6.1f}%  | {ob*100:5.1f}% ({a*100:.1f}–{b*100:.1f}){marca}")
    print("  por favorito | faixa | previsões | eleições | previsto | real (IC95)")
    for nome, mf in (("A", p >= .5), ("B", p < .5)):
        for lo, hi in ((.5, .7), (.7, .9), (.9, 1.01)):
            m = mf & (fav >= lo) & (fav < hi)
            if m.sum() < 5:
                continue
            (a, b), ne = boot_freq(k[m], hit[m])
            ob, pr = hit[m].mean(), fav[m].mean()
            marca = "  confiante demais" if pr > b else ("  cautelosa" if pr < a else "")
            print(f"   {nome} favorito | {int(lo*100)}–{min(int(hi*100), 99)}% | {m.sum():5d} | {ne:5d} | {pr*100:5.1f}% | {ob*100:5.1f}% ({a*100:.1f}–{b*100:.1f}){marca}")
    # uma previsão por eleição (só o ponto de 50%): amostras independentes
    m50 = c == 50
    if m50.sum():
        f50, h50 = fav[m50], hit[m50]
        print(f"  Só o ponto de 50% (1 previsão por eleição, n={m50.sum()}): previsto {f50.mean()*100:.1f}% x real {h50.mean()*100:.1f}%")


if __name__ == "__main__":
    n, seed = int(sys.argv[1]), int(sys.argv[2])
    for scen in sys.argv[3].split(","):
        relatorio(scen, *run(n, seed, scen), n)
