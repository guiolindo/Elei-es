"""PROTÓTIPO — não usado pelo site. Cópia de math_engine.projecao.projetar_2t
com o erro da base do 1T dividido em parte independente por UF e parte comum
à região:

    TAU_P² = (1 − ρ)·TAU_P² + ρ·TAU_P²
             independente      comum à região

A variância de cada UF sozinha não muda (nada é contado duas vezes); só
passa a existir covariância entre UFs da mesma região. Com ρ = 0 o
resultado é idêntico ao do motor (conferido em vies2.py).

A parte da base na projeção da UF u é wp_u·(erro da base). Com pesos de
precisão, v_u = wo²·vo + wp²·vp; separando:
    obs:   Σ R_u² wo_u² vo_u
    base:  Σ R_u² wp_u² (1−ρ) TAU_P²  +  Σ_g (Σ_{u∈g} R_u wp_u)² ρ TAU_P²
"""
import math
from math_engine import projecao as P


def projetar_2t_regional(estratos, regioes, antes=None, rho=0.0):
    soma_e = sum(e.eleitorado for e in estratos if e.eleitorado > 0)
    soma_ec = sum(min(e.eleitorado_tot, e.eleitorado) for e in estratos if e.eleitorado > 0)
    soma_vc = sum(e.validos for e in estratos)
    if soma_e <= 0 or soma_ec <= 0 or soma_vc <= 0:
        return None
    fracao = soma_ec / soma_e
    if fracao < P.FRACAO_MIN_PROJECAO or fracao >= 1.0:
        return None
    drift_a, tau_nat = P.DRIFT_A, P.TAU_NAT
    if antes and len(antes) == len(estratos):
        da, tn = P.estimar_deriva(antes, estratos)
        drift_a, tau_nat = max(drift_a, da), max(tau_nat, tn)
    soma_ac = sum(e.votos_a for e in estratos)
    q_nat = soma_ac / soma_vc
    r_nat = soma_vc / soma_ec
    com_prior = [e for e in estratos if e.prior_a is not None and e.validos > 0]
    den = sum(e.validos for e in com_prior)
    num_delta = sum(e.validos * (e.votos_a / e.validos - e.prior_a) for e in com_prior)
    delta = num_delta / den if den else 0.0
    if den:
        n_eff = 1.0 / sum((e.validos / den) ** 2 for e in com_prior)
        var_delta = P.TAU_P ** 2 / n_eff
    else:
        var_delta = P.TAU_P ** 2
    proj_a, proj_v = float(soma_ac), float(soma_vc)
    var_obs = var_base_ind = corr_prior = soma_r = 0.0
    var_outros = 0.0
    por_regiao = {}
    for e, g in zip(estratos, regioes):
        if e.eleitorado <= 0:
            continue
        restante = max(e.eleitorado - e.eleitorado_tot, 0)
        if restante == 0:
            continue
        r = e.validos / e.eleitorado_tot if e.eleitorado_tot > 0 and e.validos > 0 else r_nat
        R = r * restante
        p = e.prior_a
        wp_base = 0.0  # peso da base do 1T (para a parte regional)
        if e.validos > 0:
            q = e.votos_a / e.validos
            vo = P._s_w(e.secoes_tot, e.secoes - e.secoes_tot, drift_a) ** 2
            if p is not None:
                vp = P.TAU_P ** 2
                wo = (1 / vo) / (1 / vo + 1 / vp)
                if den - e.validos > 0:
                    m = wo * q + (1 - wo) * (p + delta)
                    wp = 1 - wo
                    var_obs += R * R * wo * wo * vo
                    var_base_ind += R * R * wp * wp * vp * (1 - rho)
                    wp_base = wp
                else:
                    vp2 = P.TAU_P ** 2 + P.TAU_SWING ** 2
                    wo2 = (1 / vo) / (1 / vo + 1 / vp2)
                    m = wo2 * q + (1 - wo2) * p
                    var_outros += R * R / (1 / vo + 1 / vp2)
                    wp = 0.0
            else:
                m, wp = q, 0.0
                var_outros += R * R * vo
        elif p is not None:
            m, wp = p + delta, 1.0
            var_base_ind += R * R * P.TAU_P ** 2 * (1 - rho)
            wp_base = 1.0
        else:
            m, wp = q_nat, 0.0
            var_outros += R * R * P.TAU_SEM_PRIOR ** 2
        m = min(max(m, 0.0), 1.0)
        proj_a += R * m
        proj_v += R
        corr_prior += R * wp
        soma_r += R
        por_regiao[g] = por_regiao.get(g, 0.0) + R * wp_base
    var_reg = sum(x * x for x in por_regiao.values()) * rho * P.TAU_P ** 2
    S = proj_a / proj_v
    var = (var_obs + var_base_ind + var_reg + var_outros + corr_prior ** 2 * var_delta
           + (tau_nat * soma_r) ** 2) / proj_v ** 2
    sd = math.sqrt(var) * P.fator_sd(fracao)
    pa = P._phi((S - 0.5) / (sd * P.FATOR_SD_PROB)) if sd > 0 else (1.0 if S > 0.5 else 0.0)
    return dict(pct_a=100 * S, sd_pp=100 * sd,
                ic95_a=(100 * max(0.0, S - 1.96 * sd), 100 * min(1.0, S + 1.96 * sd)),
                p_vitoria_a=pa, exibir=fracao >= P.FRACAO_MIN_PROBABILIDADE)
