"""Projeção estatística do 2º turno (2 candidatos) a partir da apuração parcial.

Puro: sem I/O. O chamador monta os ESTRATOS (Presidente: 27 UFs + exterior;
Governador: a própria UF) a partir dos snapshots do mesmo turno, com o
resultado do 1º turno de cada estrato como base (prior).

Por que estratificar: a apuração no Brasil tem viés de ordem (Sul/Sudeste
primeiro, Norte/Nordeste depois — em 2022 a liderança só virou com ~66%
apurado). Projetar pelo % nacional bruto erra o vencedor quase como cara
ou coroa no começo. Por estrato, cada UF projeta o próprio eleitorado
restante com a própria tendência, e a soma corrige o viés de ordem.

Modelo por estrato u (A e B; no 2T válidos = A + B):
    R_u = (V_c/E_c) · (E − E_c)          válidos restantes projetados
    q_u = A_c / V_c                      share observado de A
    prior_u + δ                          share do 1T ajustado pelo swing nacional
    m_u = mistura ponderada por precisão de q_u (var s_w²) e prior+δ (var τ_p²)
    S   = (ΣA_c + ΣR_u·m_u) / (ΣV_c + ΣR_u)
    Var = [ΣR_u²·v_u + (ΣR_u·wp_u)²·var_δ + (τ_nat·ΣR_u)²] / V_total²
    P(A vence) = Φ((S − 0,5)/sd);  IC95 = S ± 1,96·sd.  B = complemento.

Constantes ajustadas por simulação Monte Carlo (500 eleições com viés
regional de ordem de apuração calibrado em 2022). `FATOR_SD_*` alarga a
banda quando pouco foi apurado — a simulação mostrou que o modelo puro
fica confiante demais abaixo de ~30% em cenários adversos.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

DRIFT_A = 0.028       # deriva sistemática (seções tardias votam diferente)
DRIFT_C = 0.37        # ruído amostral ~ DRIFT_C / sqrt(seções apuradas)
DRIFT_B = 0.12        # ruído do restante ~ DRIFT_B / sqrt(seções restantes)
TAU_P = 0.025         # erro do prior (1T + swing nacional) por estrato
TAU_SEM_PRIOR = 0.10  # estrato sem dado e sem prior
TAU_NAT = 0.010       # deriva correlacionada entre todos os estratos

# Fator multiplicativo do desvio-padrão por fração do eleitorado apurada.
FATOR_SD_FAIXAS = ((0.30, 1.8), (0.50, 1.4), (0.80, 1.15), (1.01, 1.0))

# Swing δ "deixando o próprio estrato de fora" (leave-one-out), pra o share
# de um estado não entrar duas vezes na própria projeção (em q_u e em δ).
# Testado (val.py, sementes fora do ajuste): com 28 estratos o efeito é
# nulo dentro do erro de simulação — fica desligado pra não mexer no que
# está validado. O caso em que a contagem dupla importa (estrato único) é
# tratado abaixo, em projetar_2t.
DELTA_LOO = False
# Estrato único (Governador): δ só poderia sair do próprio estrato e aí
# p+δ = q — o 1º turno era anulado e a variância contava duas fontes.
# Usa o 1T sem swing, com a incerteza do swing somada à do prior.
# HEURÍSTICO (não calibrado em eleição real): ~ desvio do swing 1T→2T.
TAU_SWING = 0.04

FRACAO_MIN_PROJECAO = 0.10   # abaixo disso não projeta
FRACAO_MIN_PROBABILIDADE = 0.30
P_MAX_EXIBIDA = 0.99


@dataclass(frozen=True)
class Estrato:
    eleitorado: int
    eleitorado_tot: int
    validos: int
    votos_a: int
    secoes: int
    secoes_tot: int
    prior_a: float | None = None


@dataclass(frozen=True)
class Projecao:
    pct_a: float
    pct_b: float
    ic95_a: tuple[float, float]
    ic95_b: tuple[float, float]
    sd_pp: float
    p_vitoria_a: float
    p_vitoria_b: float
    votos_a: int
    votos_b: int
    fracao_apurada: float
    exibir_probabilidade: bool


def _phi(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _s_w(secoes_tot: int, secoes_rest: int, drift_a: float) -> float:
    v = drift_a ** 2
    v += DRIFT_C ** 2 / max(secoes_tot, 1)
    v += DRIFT_B ** 2 / max(secoes_rest, 1)
    return math.sqrt(v)


def fator_sd(fracao: float) -> float:
    for limite, fator in FATOR_SD_FAIXAS:
        if fracao < limite:
            return fator
    return 1.0


def estimar_deriva(antes: list[Estrato], agora: list[Estrato]) -> tuple[float, float]:
    """Deriva observada entre um snapshot anterior e o atual dos mesmos
    estratos: votos que entraram desde `antes` vs share que já havia.
    Retorna (drift_a, tau_nat) — o chamador usa max(constante, estimativa),
    então a banda só alarga."""
    num2 = num1 = den = 0.0
    for b, a in zip(antes, agora):
        dv = a.validos - b.validos
        if b.validos <= 0 or dv <= 0:
            continue
        d = (a.votos_a - b.votos_a) / dv - b.votos_a / b.validos
        ds = max(a.secoes_tot - b.secoes_tot, 1)
        amostral = DRIFT_C ** 2 / max(b.secoes_tot, 1) + DRIFT_C ** 2 / ds
        num2 += dv * (d * d - amostral)
        num1 += dv * d
        den += dv
    if den <= 0:
        return DRIFT_A, TAU_NAT
    return math.sqrt(max(num2 / den, 0.0)), abs(num1 / den)


def projetar_2t(estratos: list[Estrato], antes: list[Estrato] | None = None) -> Projecao | None:
    """None quando não há base suficiente (nada apurado, < FRACAO_MIN_PROJECAO
    ou 100% apurado — aí o resultado é o oficial, não projeção)."""
    soma_e = sum(e.eleitorado for e in estratos if e.eleitorado > 0)
    soma_ec = sum(min(e.eleitorado_tot, e.eleitorado) for e in estratos if e.eleitorado > 0)
    soma_vc = sum(e.validos for e in estratos)
    if soma_e <= 0 or soma_ec <= 0 or soma_vc <= 0:
        return None
    fracao = soma_ec / soma_e
    if fracao < FRACAO_MIN_PROJECAO or fracao >= 1.0:
        return None

    drift_a, tau_nat = DRIFT_A, TAU_NAT
    if antes and len(antes) == len(estratos):
        da, tn = estimar_deriva(antes, estratos)
        drift_a, tau_nat = max(drift_a, da), max(tau_nat, tn)

    soma_ac = sum(e.votos_a for e in estratos)
    q_nat = soma_ac / soma_vc
    r_nat = soma_vc / soma_ec

    # Swing nacional 1T→2T a partir dos estratos com prior e dados
    com_prior = [e for e in estratos if e.prior_a is not None and e.validos > 0]
    den = sum(e.validos for e in com_prior)
    num_delta = sum(e.validos * (e.votos_a / e.validos - e.prior_a) for e in com_prior)
    delta = num_delta / den if den else 0.0
    if den:
        pesos = [e.validos / den for e in com_prior]
        n_eff = 1.0 / sum(w * w for w in pesos)
        var_delta = TAU_P ** 2 / n_eff
    else:
        var_delta = TAU_P ** 2

    proj_a = float(soma_ac)
    proj_v = float(soma_vc)
    var_indep = corr_prior = soma_r = 0.0
    for e in estratos:
        if e.eleitorado <= 0:
            continue
        restante = max(e.eleitorado - e.eleitorado_tot, 0)
        if restante == 0:
            continue
        r = e.validos / e.eleitorado_tot if e.eleitorado_tot > 0 and e.validos > 0 else r_nat
        R = r * restante
        p = e.prior_a
        if e.validos > 0:
            q = e.votos_a / e.validos
            vo = _s_w(e.secoes_tot, e.secoes - e.secoes_tot, drift_a) ** 2
            if p is not None:
                vp = TAU_P ** 2
                wo = (1 / vo) / (1 / vo + 1 / vp)
                outros = den - e.validos
                if outros > 0:
                    d_u = delta
                    if DELTA_LOO:
                        d_u = (num_delta - e.validos * (q - p)) / outros
                    m = wo * q + (1 - wo) * (p + d_u)
                    v = 1 / (1 / vo + 1 / vp)
                    wp = 1 - wo
                else:  # único estrato com dado: 1T puro + incerteza do swing
                    vp2 = TAU_P ** 2 + TAU_SWING ** 2
                    wo2 = (1 / vo) / (1 / vo + 1 / vp2)
                    m = wo2 * q + (1 - wo2) * p
                    v = 1 / (1 / vo + 1 / vp2)
                    wp = 0.0
            else:
                m, v, wp = q, vo, 0.0
        elif p is not None:
            m, v, wp = p + delta, TAU_P ** 2, 1.0
        else:
            m, v, wp = q_nat, TAU_SEM_PRIOR ** 2, 0.0
        m = min(max(m, 0.0), 1.0)
        proj_a += R * m
        proj_v += R
        var_indep += R * R * v
        corr_prior += R * wp
        soma_r += R

    S = proj_a / proj_v
    var = (var_indep + corr_prior ** 2 * var_delta + (tau_nat * soma_r) ** 2) / proj_v ** 2
    sd = math.sqrt(var) * fator_sd(fracao)
    if sd > 0:
        pa = _phi((S - 0.5) / sd)
    else:
        pa = 1.0 if S > 0.5 else (0.0 if S < 0.5 else 0.5)
    lo, hi = max(0.0, S - 1.96 * sd), min(1.0, S + 1.96 * sd)
    return Projecao(
        pct_a=100 * S, pct_b=100 * (1 - S),
        ic95_a=(100 * lo, 100 * hi), ic95_b=(100 * (1 - hi), 100 * (1 - lo)),
        sd_pp=100 * sd,
        p_vitoria_a=pa, p_vitoria_b=1 - pa,
        votos_a=int(round(proj_a)), votos_b=int(round(proj_v - proj_a)),
        fracao_apurada=fracao,
        exibir_probabilidade=fracao >= FRACAO_MIN_PROBABILIDADE,
    )
