from math_engine.projecao import Estrato, projetar_2t


def e(E, frac, share_a, prior=None, secoes=10_000, turnout=0.8):
    """Estrato com `frac` do eleitorado apurado e `share_a` de A nos válidos."""
    ec = int(E * frac)
    v = int(ec * turnout)
    return Estrato(E, ec, v, int(v * share_a), secoes, int(secoes * frac), prior)


def test_nao_projeta_abaixo_de_10pct_nem_com_100pct():
    assert projetar_2t([e(1_000_000, 0.05, 0.55)]) is None
    assert projetar_2t([e(1_000_000, 1.0, 0.55)]) is None
    assert projetar_2t([e(1_000_000, 0.0, 0.55)]) is None


def test_pcts_somam_100_e_intervalos_sao_complementares():
    p = projetar_2t([e(5_000_000, 0.4, 0.53, 0.52), e(3_000_000, 0.2, 0.45, 0.46)])
    assert abs(p.pct_a + p.pct_b - 100) < 1e-9
    assert abs(p.ic95_a[0] - (100 - p.ic95_b[1])) < 1e-9
    assert abs(p.p_vitoria_a + p.p_vitoria_b - 1) < 1e-12
    assert p.ic95_a[0] <= p.pct_a <= p.ic95_a[1]


def test_simetria_trocando_candidatos():
    a = projetar_2t([e(5_000_000, 0.4, 0.53, 0.52), e(3_000_000, 0.2, 0.45, 0.46)])
    b = projetar_2t([e(5_000_000, 0.4, 0.47, 0.48), e(3_000_000, 0.2, 0.55, 0.54)])
    assert abs(a.pct_a - b.pct_b) < 0.05
    assert abs(a.p_vitoria_a - b.p_vitoria_b) < 0.01


def test_corrige_vies_de_ordem_regional_estilo_2022():
    """Sul/Sudeste (B forte) quase todo apurado, Nordeste (A forte) mal
    começou. Nacionalmente B lidera agora, mas o eleitorado que falta é
    majoritariamente de A — a projeção tem que apontar A."""
    sul = e(40_000_000, 0.85, 0.40, prior=0.41)
    nordeste = e(40_000_000, 0.20, 0.68, prior=0.67)
    q_atual = (sul.votos_a + nordeste.votos_a) / (sul.validos + nordeste.validos)
    assert q_atual < 0.5  # B lidera na contagem parcial
    p = projetar_2t([sul, nordeste])
    assert p.pct_a > 50
    assert p.p_vitoria_a > 0.9


def test_probabilidade_so_exibida_a_partir_de_50pct():
    assert projetar_2t([e(1_000_000, 0.35, 0.55, 0.55)]).exibir_probabilidade is False
    assert projetar_2t([e(1_000_000, 0.49, 0.55, 0.55)]).exibir_probabilidade is False
    assert projetar_2t([e(1_000_000, 0.55, 0.55, 0.55)]).exibir_probabilidade is True


def test_estrato_unico_usa_o_1t_sem_contar_o_parcial_duas_vezes():
    """Governador (um estrato só): o swing δ só sairia do próprio estrato e
    p+δ = q — o 1º turno era anulado e a margem contava duas fontes. Agora
    a projeção fica entre o parcial (53,7%) e o 1T (52%), e a margem é mais
    larga que a da combinação ingênua."""
    import math
    from math_engine import projecao as PM
    p = projetar_2t([e(10_000_000, 0.5, 0.537, 0.52)])
    assert 52.0 < p.pct_a < 53.7
    vo = PM._s_w(5_000, 5_000, PM.DRIFT_A) ** 2
    sd_ingenuo = math.sqrt(1 / (1 / vo + 1 / PM.TAU_P ** 2))  # por eleitor restante
    sd_novo = math.sqrt(1 / (1 / vo + 1 / (PM.TAU_P ** 2 + PM.TAU_SWING ** 2)))
    assert sd_novo > sd_ingenuo


def test_varios_estratos_mantem_o_swing_nacional():
    """Presidente: com outros estratos o comportamento é o validado (δ entra)."""
    a = projetar_2t([e(10_000_000, 0.5, 0.537, 0.52), e(10_000_000, 0.5, 0.537, 0.52)])
    assert abs(a.pct_a - 53.7) < 0.05  # q = p+δ em todos → projeta o observado


def test_chance_usa_incerteza_mais_larga_que_o_ic95():
    """A chance usa sd × FATOR_SD_PROB; o IC95 continua com o sd puro."""
    from math_engine import projecao as PM
    p = projetar_2t([e(10_000_000, 0.6, 0.515, 0.51), e(8_000_000, 0.6, 0.52, 0.51)])
    S, sd = p.pct_a / 100, p.sd_pp / 100
    assert abs(p.p_vitoria_a - PM._phi((S - 0.5) / (sd * PM.FATOR_SD_PROB))) < 1e-12
    assert abs((p.ic95_a[1] - p.ic95_a[0]) / 2 - 196 * sd) < 1e-6
    assert p.p_vitoria_a < PM._phi((S - 0.5) / sd)


def test_intervalo_estreita_com_mais_apurado():
    sds = [projetar_2t([e(10_000_000, f, 0.52, 0.52)]).sd_pp for f in (0.15, 0.4, 0.7, 0.95)]
    assert sds == sorted(sds, reverse=True)


def test_empate_tecnico_da_probabilidade_perto_de_meio():
    p = projetar_2t([e(10_000_000, 0.6, 0.5, 0.5)])
    assert 0.45 < p.p_vitoria_a < 0.55


def test_uf_sem_dados_usa_prior_do_1t():
    apurada = e(10_000_000, 0.5, 0.50, prior=0.50)
    sem_dados = Estrato(10_000_000, 0, 0, 0, 10_000, 0, 0.70)
    p = projetar_2t([apurada, sem_dados])
    assert p.pct_a > 55


def test_deriva_observada_so_alarga_a_banda():
    agora = [e(10_000_000, 0.6, 0.52, 0.52), e(8_000_000, 0.5, 0.47, 0.47)]
    antes = [Estrato(10_000_000, 3_600_000, 2_880_000, int(2_880_000 * 0.56), 10_000, 3_600, 0.52),
             Estrato(8_000_000, 2_400_000, 1_920_000, int(1_920_000 * 0.43), 10_000, 3_000, 0.47)]
    assert projetar_2t(agora, antes).sd_pp >= projetar_2t(agora).sd_pp
