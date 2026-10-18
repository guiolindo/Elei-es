"""Monte Carlo simulator of a Brazilian national 2nd round count.
usage: python sim.py [n_elections] [seed] [scenario]"""
import sys, math
import numpy as np
sys.path.insert(0, __file__.rsplit("/", 1)[0])
import projecao_ref as ref
import os
for _k in ("DRIFT_A","TAU_NAT","TAU_P"):
    if _k in os.environ: setattr(ref, _k, float(os.environ[_k]))

# UF: (eleitorado 2022 M, Lula 2T share 2022, region)
UFS = {
 "SP": (34.7, .448, "SE"), "MG": (16.3, .502, "SE"), "RJ": (12.8, .435, "SE"),
 "ES": (2.9, .419, "SE"), "BA": (11.3, .721, "NE"), "PE": (7.0, .669, "NE"),
 "CE": (6.8, .700, "NE"), "MA": (5.0, .711, "NE"), "PB": (3.1, .666, "NE"),
 "RN": (2.6, .651, "NE"), "AL": (2.3, .587, "NE"), "PI": (2.6, .769, "NE"),
 "SE": (1.7, .672, "NE"), "RS": (8.6, .437, "S"), "PR": (8.5, .376, "S"),
 "SC": (5.5, .307, "S"), "GO": (4.9, .413, "CO"), "MT": (2.5, .349, "CO"),
 "MS": (2.0, .406, "CO"), "DF": (2.2, .412, "CO"), "PA": (6.1, .548, "N"),
 "AM": (2.6, .511, "N"), "RO": (1.2, .293, "N"), "TO": (1.1, .514, "N"),
 "AC": (0.6, .297, "N"), "AP": (0.55, .459, "N"), "RR": (0.37, .239, "N"),
 "ZZ": (0.70, .500, "EX"),   # exterior: residual stratum (no per-UF snapshot)
}
NAMES = list(UFS)
NU = len(NAMES)
REG_ORDER = {"S": -0.30, "SE": -0.20, "CO": -0.10, "NE": 0.25, "N": 0.40, "EX": 0.6}
REG_EPS = {"S": 360, "SE": 370, "CO": 340, "NE": 310, "N": 280, "EX": 500}
REG_TURN = {"S": .82, "SE": .79, "CO": .79, "NE": .79, "N": .78, "EX": .30}
SECOES_POR_BLOCO = 20

SCEN = {
 "base": dict(gamma_sd=0.06, gamma_nat=0.03, het_sd=0.30, ord_noise=0.10, order_scale=0.5,
              within_t_sd=0.35, prior_sd=0.025, swing_mu=-0.01, swing_sd=0.02,
              step=0.67),
 # misspecified: 2x stronger within-UF ordering bias, noisier priors, finer polls
 # NUNCA usado em ajuste: viés capital×interior 3x, comparecimento ligado à
 # ordem, 1T pior como guia, swing nacional grande.
 "adverso": dict(gamma_sd=0.18, gamma_nat=0.09, het_sd=0.45, ord_noise=0.20, order_scale=1.0,
              within_t_sd=0.45, prior_sd=0.05, swing_mu=-0.02, swing_sd=0.05,
              step=0.30),
 "hard": dict(gamma_sd=0.12, gamma_nat=0.06, het_sd=0.40, ord_noise=0.15, order_scale=0.8,
              within_t_sd=0.35, prior_sd=0.04, swing_mu=-0.01, swing_sd=0.03,
              step=0.30),
}


def logit(p): return np.log(p / (1 - p))
def expit(x): return 1 / (1 + np.exp(-x))


def gen_election(rng, P):
    common = rng.normal(0, 0.025)
    uf_idx, E, T, A, V = [], [], [], [], []
    ufE = np.zeros(NU); ufS = np.zeros(NU); prior = np.zeros(NU)
    gnat = rng.normal(0, P["gamma_nat"])
    for i, u in enumerate(NAMES):
        el, p, reg = UFS[u]
        p_true = float(np.clip(p + common + rng.normal(0, 0.02), .05, .95))
        nb = max(3, int(round(el * 1e6 / (REG_EPS[reg] * SECOES_POR_BLOCO))))
        e = REG_EPS[reg] * SECOES_POR_BLOCO * rng.lognormal(0, 0.15, nb)
        z = rng.normal(0, 1, nb)
        tmean = P["order_scale"] * REG_ORDER[reg] + rng.normal(0, P["ord_noise"])
        if u == "SP": tmean -= 0.1
        t = tmean + P["within_t_sd"] * z + 0.10 * rng.normal(0, 1, nb)
        gam = gnat + rng.normal(0, P["gamma_sd"])
        sh = expit(logit(p_true) + gam * z + rng.normal(0, P["het_sd"], nb))
        tu0 = REG_TURN[reg] + rng.normal(0, 0.02)
        tu = expit(logit(tu0) + rng.normal(0, 0.25, nb) - 0.1 * z * (reg in ("N", "NE")))
        valid = np.round(e * tu * 0.954)
        a = np.round(valid * sh)
        uf_idx.append(np.full(nb, i)); E.append(np.round(e)); T.append(t); A.append(a); V.append(valid)
    uf_idx = np.concatenate(uf_idx); E = np.concatenate(E); T = np.concatenate(T)
    A = np.concatenate(A); V = np.concatenate(V)
    # 1T-based prior per UF: true UF share - national swing + noise
    swing = rng.normal(P["swing_mu"], P["swing_sd"])
    for i in range(NU):
        m = uf_idx == i
        prior[i] = A[m].sum() / V[m].sum() - swing + rng.normal(0, P["prior_sd"])
    return uf_idx, E, T, A, V, prior


def snapshots(uf_idx, E, T, A, V, step):
    o = np.argsort(T)
    uf_idx, E, A, V = uf_idx[o], E[o], A[o], V[o]
    secs = np.full(len(E), SECOES_POR_BLOCO, float)
    oh = np.zeros((len(E), NU)); oh[np.arange(len(E)), uf_idx] = 1
    cE = np.cumsum(oh * E[:, None], 0); cA = np.cumsum(oh * A[:, None], 0)
    cV = np.cumsum(oh * V[:, None], 0); cS = np.cumsum(oh * secs[:, None], 0)
    tot = dict(E=cE[-1], A=cA[-1], V=cV[-1], S=cS[-1])
    S_all = cS[-1].sum(); cs_nat = cS.sum(1)
    cuts = []
    pct = step
    while pct < 100:
        k = int(np.searchsorted(cs_nat, pct / 100 * S_all))
        if k < len(E) and (not cuts or k > cuts[-1]):
            cuts.append(k)
        pct += step
    snaps = [dict(E=cE[k], A=cA[k], V=cV[k], S=cS[k]) for k in cuts]
    return snaps, tot


# ---------------- methods ----------------
def nat(s):
    return {k: s[k].sum() for k in s}

def m_linear(s, tot):              # (a)/(b): % = current share
    n = nat(s); return n["A"] / n["V"]

def votes_linear_secoes(s, tot):
    n = nat(s); return n["A"] * tot["S"].sum() / n["S"]

def votes_linear_eleit(s, tot):
    n = nat(s); return n["A"] * tot["E"].sum() / n["E"]

def m_tendencia(snaps, j, tot):   # (c) faithful replica of app/api.py
    s = nat(snaps[j]); St = tot["S"].sum()
    pct = s["S"] * 100 / St
    if pct < 30 or pct >= 100: return None
    w = snaps[max(0, j - 14): j + 1]
    if len(w) < 10: return None
    b = nat(w[0]); pb = b["S"] * 100 / St; dp = pct - pb
    if dp < 1: return None
    falt = 100 - pct
    Bc, Bb = s["V"] - s["A"], b["V"] - b["A"]
    tv = (s["V"] - b["V"]) / dp
    pv = max(s["V"], int(s["V"] + tv * falt))
    out = []
    for c, cb in ((s["A"], b["A"]), (Bc, Bb)):
        pj = int(c + (c - cb) / dp * falt)
        lin = int(c * St / s["S"])
        pj = max(c, min(pj, 2 * lin))
        out.append(pj / pv)
    return out  # [pctA, pctB] (fractions)

def estratos(s, prior, use_prior, split_residual=True):
    return [dict(eleitorado=float(tE), eleitorado_tot=float(s["E"][i]),
                 validos=float(s["V"][i]), votos_a=float(s["A"][i]),
                 secoes=float(TOT_S[i]), secoes_tot=float(s["S"][i]),
                 prior_a=(float(prior[i]) if use_prior and NAMES[i] != "ZZ" else None))
            for i, tE in enumerate(TOT_E)]

def m_strat_simple(s, tot):        # (d) stratified, no prior, fallback = national share
    q_nat = s["A"].sum() / s["V"].sum(); r_nat = s["V"].sum() / s["E"].sum()
    pa = s["A"].sum(); pv = s["V"].sum()
    for i in range(NU):
        rest = tot["E"][i] - s["E"][i]
        if s["V"][i] > 0:
            R = s["V"][i] / s["E"][i] * rest; q = s["A"][i] / s["V"][i]
        else:
            R = r_nat * rest; q = q_nat
        pa += R * q; pv += R
    return pa / pv


ADAPT = os.environ.get('ADAPT') == '1'

def run(n, seed, scen):
    global TOT_E, TOT_S
    P = SCEN[scen]; rng = np.random.default_rng(seed)
    CPS = [10, 20, 30, 50, 70, 90]
    M = ["linear", "tendencia", "estrat", "estrat+prior"]
    err = {m: {c: [] for c in CPS} for m in M}
    win = {m: {c: [] for c in CPS} for m in M}
    na = {c: 0 for c in CPS}
    verr = {m: {c: [] for c in CPS} for m in ("lin_secoes", "lin_eleit", "estrat+prior")}
    cov = {k: {c: [] for c in CPS} for k in ("cov90", "cov95", "brier", "p", "y", "sd")}
    sum100 = []
    drift = []   # (f, remaining share - counted share) for fitting s_w
    for it in range(n):
        uf_idx, E, T, A, V, prior = gen_election(rng, P)
        snaps, tot = snapshots(uf_idx, E, T, A, V, P["step"])
        TOT_E = tot["E"]; TOT_S = tot["S"]
        truth = tot["A"].sum() / tot["V"].sum()
        leaderA = truth > 0.5
        true_votes_leader = tot["A"].sum() if leaderA else (tot["V"] - tot["A"]).sum()
        St = tot["S"].sum()
        pcts = np.array([nat(s)["S"] * 100 / St for s in snaps])
        for c in CPS:
            j = int(np.searchsorted(pcts, c))
            s = snaps[j]
            def rec(m, shareA):
                if shareA is None: return
                lead = shareA if leaderA else 1 - shareA
                tl = truth if leaderA else 1 - truth
                err[m][c].append(abs(lead - tl) * 100)
                win[m][c].append((shareA > 0.5) == leaderA)
            rec("linear", m_linear(s, tot))
            td = m_tendencia(snaps, j, tot)
            if td is None:
                na[c] += 1; rec("tendencia", m_linear(s, tot))  # app falls back to showing linear
            else:
                rec("tendencia", td[0]); sum100.append(100 * (td[0] + td[1]))
            rec("estrat", m_strat_simple(s, tot))
            r0 = ref.projetar(estratos(s, prior, True))
            rec("estrat+prior", r0["pct_a"] / 100)
            jb = int(np.searchsorted(pcts, 0.6 * pcts[j]))
            antes = estratos(snaps[jb], prior, True) if jb < j else None
            r = ref.projetar_adaptativo(antes, estratos(s, prior, True)) if ADAPT else r0
            # votes error for leader
            la = lambda va: va if leaderA else None
            if leaderA:
                verr["lin_secoes"][c].append(abs(votes_linear_secoes(s, tot) / true_votes_leader - 1) * 100)
                verr["lin_eleit"][c].append(abs(votes_linear_eleit(s, tot) / true_votes_leader - 1) * 100)
                verr["estrat+prior"][c].append(abs(r["votos_a"] / true_votes_leader - 1) * 100)
            lo, hi = r["ic95_a"]; sd = r["sd_pp"] / 100
            cov["cov95"][c].append(lo <= truth * 100 <= hi)
            cov["cov90"][c].append(abs(r["pct_a"] / 100 - truth) <= 1.645 * sd)
            cov["p"][c].append(r["p_vitoria_a"]); cov["y"][c].append(float(truth > 0.5))
            cov["brier"][c].append((r["p_vitoria_a"] - (truth > 0.5)) ** 2)
            cov["sd"][c].append(r["sd_pp"])
            for i in range(NU):
                if 0 < s["E"][i] < tot["E"][i] and s["V"][i] > 0:
                    rem_v = tot["V"][i] - s["V"][i]
                    if rem_v > 0:
                        drift.append((s["E"][i] / tot["E"][i],
                                      (tot["A"][i] - s["A"][i]) / rem_v - s["A"][i] / s["V"][i]))
    return CPS, M, err, win, na, verr, cov, sum100, drift


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 500
    seed = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    scen = sys.argv[3] if len(sys.argv) > 3 else "base"
    CPS, M, err, win, na, verr, cov, sum100, drift = run(n, seed, scen)
    print(f"scenario={scen} n={n} seed={seed}")
    print("MAE of leader final % (pp) | median | P(correct winner)")
    print("method        " + "".join(f"{c:>17}%" for c in CPS))
    for m in M:
        print(f"{m:13s} " + "".join(
            f"  {np.mean(err[m][c]):5.2f}/{np.median(err[m][c]):4.2f}/{np.mean(win[m][c])*100:4.0f}%" for c in CPS))
    print("tendencia n/a (gate) count:", na)
    print("leader VOTES abs rel err %:")
    for m in verr:
        print(f"{m:13s} " + "".join(f"{np.mean(verr[m][c]):8.2f}" for c in CPS))
    print("calibration of estrat+prior interval/probability:")
    for c in CPS:
        p = np.array(cov["p"][c]); y = np.array(cov["y"][c])
        print(f" {c:3d}%: cov90={np.mean(cov['cov90'][c])*100:5.1f} cov95={np.mean(cov['cov95'][c])*100:5.1f} "
              f"brier={np.mean(cov['brier'][c]):.4f} mean_sd={np.mean(cov['sd'][c]):.2f}pp")
    P = np.concatenate([cov["p"][c] for c in CPS]); Y = np.concatenate([cov["y"][c] for c in CPS])
    pw = np.maximum(P, 1 - P); yw = np.where(P >= .5, Y, 1 - Y)
    print("reliability (favourite prob bin -> observed win freq, n):")
    for lo, hi in ((.5, .7), (.7, .9), (.9, .97), (.97, .995), (.995, 1.01)):
        m = (pw >= lo) & (pw < hi)
        if m.sum(): print(f"  [{lo:.3f},{hi:.3f}) pred={pw[m].mean():.3f} obs={yw[m].mean():.3f} n={m.sum()}")
    s100 = np.array(sum100)
    print(f"tendencia sum of 2 pcts: min={s100.min():.2f} max={s100.max():.2f} frac|dev|>0.05pp={np.mean(abs(s100-100)>.05):.3f}")
    d = np.array(drift)
    for lo, hi in ((0, .1), (.1, .3), (.3, .5), (.5, .7), (.7, .9), (.9, 1)):
        m = (d[:, 0] >= lo) & (d[:, 0] < hi)
        if m.sum(): print(f"  drift f in [{lo},{hi}): sd={d[m,1].std()*100:.2f}pp  n={m.sum()}")
