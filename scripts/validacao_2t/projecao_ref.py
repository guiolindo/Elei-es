"""Reference implementation (pure stdlib) — stratified 2nd-round projection
with probability of victory and confidence interval.

Portable to app/api.py: each "estrato" is one per-UF snapshot (cargo 1, UF,
SAME turno) plus one residual stratum = BR minus sum(UFs) (exterior, ZZ).
For Governador the strata would be municipalities (or just 1 stratum -> it
degrades gracefully to a linear-by-eleitorado projection with a wide band).

Model, per stratum u (2 candidates A, B; valid = A + B in 2T):
    f_u   = E_c / E                       (fraction of ELEITORADO counted)
    r_u   = V_c / E_c                     (valid votes per counted elector)
    R_u   = r_u * (E - E_c)               (projected remaining valid votes)
    q_u   = A_c / V_c                     (observed share of A)
    s_w^2 = DRIFT_A^2 + DRIFT_C^2/S_c + DRIFT_B^2/(S - S_c)   (S = secoes)
    prior_u (optional) = A/(A+B) in the 1T in that stratum
    delta = sum(V_c*(q_u-prior_u)) / sum(V_c)   (national 1T->2T swing)
    remaining-share estimate m_u = precision-weighted mix of
        q_u                  with var  s_w(f_u)^2  (within-stratum drift)
        prior_u + delta      with var  TAU_P^2
    posterior var v_u = 1 / (1/s_w^2 + 1/TAU_P^2)
    S   = (sum A_c + sum R_u m_u) / (sum V_c + sum R_u)
    Var = [sum R_u^2 v_u + (sum R_u * wp_u)^2 * var_delta
           + (TAU_NAT * sum R_u)^2] / Vtot^2
          wp_u = prior weight in m_u; TAU_NAT = correlated drift across strata
    P(A wins) = Phi((S - 0.5)/sd);  CI95 = S +- 1.96 sd (clipped to [0,1]);
    B's numbers are the complement (sum = 100% by construction).
"""
from __future__ import annotations

import math

# Fitted in the simulator (see sim.py). Shares as fractions (0.01 = 1 pp).
DRIFT_A = 0.028   # systematic drift sd (early vs late sections differ)
DRIFT_C = 0.37    # sampling term: sd ~ DRIFT_C / sqrt(secoes counted)
DRIFT_B = 0.12    # small-remainder term: sd ~ DRIFT_B / sqrt(secoes left)
TAU_P = 0.025     # sd of (true 2T share - (1T prior + national swing)) per UF
TAU_NO_PRIOR = 0.10  # sd when a stratum has no data and no prior
TAU_NAT = 0.010   # correlated (all strata move together) residual drift


def s_w(n_cnt: float, n_rem: float) -> float:
    """sd of (share of not-yet-counted sections - counted share)."""
    v = DRIFT_A ** 2
    v += DRIFT_C ** 2 / max(n_cnt, 1.0)
    v += DRIFT_B ** 2 / max(n_rem, 1.0)
    return math.sqrt(v)


def _phi(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def projetar(estratos: list[dict]) -> dict | None:
    """estratos: [{"eleitorado": E, "eleitorado_tot": E_c, "validos": V_c,
                   "votos_a": A_c, "prior_a": float|None}, ...]
    Returns {"pct_a", "pct_b", "ic95_a": (lo, hi), "p_vitoria_a",
             "votos_a", "votos_b"} or None if nothing counted."""
    sum_vc = sum(e["validos"] for e in estratos)
    sum_ec = sum(e["eleitorado_tot"] for e in estratos)
    if sum_vc <= 0 or sum_ec <= 0:
        return None
    sum_ac = sum(e["votos_a"] for e in estratos)
    q_nat = sum_ac / sum_vc
    r_nat = sum_vc / sum_ec

    # national swing vs 1T prior, from strata that have both
    num = den = 0.0
    sq = 0.0
    for e in estratos:
        p = e.get("prior_a")
        if p is not None and e["validos"] > 0:
            d = e["votos_a"] / e["validos"] - p
            num += e["validos"] * d
            den += e["validos"]
    delta = num / den if den else 0.0
    # var of the swing estimate: between-UF spread / effective n
    n_eff_num = n_eff_den = 0.0
    for e in estratos:
        if e.get("prior_a") is not None and e["validos"] > 0:
            w = e["validos"] / den
            n_eff_num += w
            n_eff_den += w * w
    n_eff = (n_eff_num ** 2 / n_eff_den) if n_eff_den else 0.0
    var_delta = (TAU_P ** 2 / n_eff) if n_eff else TAU_P ** 2

    proj_a = float(sum_ac)
    proj_v = float(sum_vc)
    var_indep = 0.0
    corr_prior = 0.0
    sum_r = 0.0
    for e in estratos:
        E, Ec, Vc, Ac = (e["eleitorado"], e["eleitorado_tot"],
                         e["validos"], e["votos_a"])
        if E <= 0:
            continue
        restante = max(E - Ec, 0)
        if restante == 0:
            continue
        r = Vc / Ec if Ec > 0 and Vc > 0 else r_nat
        R = r * restante
        p = e.get("prior_a")
        if Vc > 0:
            q = Ac / Vc
            vo = s_w(e.get("secoes_tot", 1e9), e.get("secoes", 1e9) - e.get("secoes_tot", 0)) ** 2
            if p is not None:
                vp = TAU_P ** 2
                wo = (1 / vo) / (1 / vo + 1 / vp)
                m = wo * q + (1 - wo) * (p + delta)
                v = 1 / (1 / vo + 1 / vp)
                wp = 1 - wo
            else:
                m, v, wp = q, vo, 0.0
        elif p is not None:
            m, v, wp = p + delta, TAU_P ** 2, 1.0
        else:
            m, v, wp = q_nat, TAU_NO_PRIOR ** 2, 0.0
        m = min(max(m, 0.0), 1.0)
        proj_a += R * m
        proj_v += R
        var_indep += R * R * v
        corr_prior += R * wp
        sum_r += R
    if proj_v <= 0:
        return None
    S = proj_a / proj_v
    var = (var_indep + corr_prior ** 2 * var_delta
           + (TAU_NAT * sum_r) ** 2) / proj_v ** 2
    sd = math.sqrt(var)
    if sd == 0:
        pw = 1.0 if S > 0.5 else (0.0 if S < 0.5 else 0.5)
    else:
        pw = _phi((S - 0.5) / sd)
    lo, hi = max(0.0, S - 1.96 * sd), min(1.0, S + 1.96 * sd)
    return {
        "pct_a": 100 * S, "pct_b": 100 * (1 - S),
        "ic95_a": (100 * lo, 100 * hi), "ic95_b": (100 * (1 - hi), 100 * (1 - lo)),
        "sd_pp": 100 * sd,
        "p_vitoria_a": pw, "p_vitoria_b": 1 - pw,
        "votos_a": int(round(proj_a)), "votos_b": int(round(proj_v - proj_a)),
    }


def estimar_drift(antes: list[dict], agora: list[dict]) -> tuple[float, float]:
    """Data-adaptive drift from an EARLIER snapshot of the same strata
    (e.g. when national progress was ~60% of the current one).

    For each stratum, d_u = share(votes added since `antes`) - share(antes)
    is a direct sample of the 'remaining vs counted' drift. Returns
    (drift_a, tau_nat) estimates:
        drift_a^2 = weighted mean(d_u^2 - sampling var) over strata
        tau_nat   = |weighted mean d_u|   (common direction across strata)
    Callers use max(constant, estimate) so the band only widens."""
    num2 = num1 = den = 0.0
    for b, a in zip(antes, agora):
        dv = a["validos"] - b["validos"]
        if b["validos"] <= 0 or dv <= 0:
            continue
        d = (a["votos_a"] - b["votos_a"]) / dv - b["votos_a"] / b["validos"]
        ds = max(a.get("secoes_tot", 1e9) - b.get("secoes_tot", 0), 1.0)
        samp = DRIFT_C ** 2 / max(b.get("secoes_tot", 1e9), 1.0) + DRIFT_C ** 2 / ds
        num2 += dv * (d * d - samp)
        num1 += dv * d
        den += dv
    if den <= 0:
        return DRIFT_A, TAU_NAT
    return math.sqrt(max(num2 / den, 0.0)), abs(num1 / den)


def projetar_adaptativo(antes: list[dict] | None, agora: list[dict]) -> dict | None:
    """projetar() with drift constants widened by estimar_drift()."""
    global DRIFT_A, TAU_NAT
    if not antes:
        return projetar(agora)
    da, tn = estimar_drift(antes, agora)
    old = (DRIFT_A, TAU_NAT)
    try:
        DRIFT_A, TAU_NAT = max(old[0], da), max(old[1], tn)
        return projetar(agora)
    finally:
        DRIFT_A, TAU_NAT = old
