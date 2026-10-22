"""Aviso de eleito no 2º turno contra a definição, em milhares de cenários.

Definição (o mesmo "matematicamente eleito" da imprensa, sem suposição de
comparecimento): eleito se e só se votos do 2º + eleitores aptos das urnas
que faltam < votos do 1º, com pelo menos 20% das seções apuradas e totais
consistentes. Votos de candidato não ativo não contam para ninguém.
"""
import random

from math_engine.engine import CandidatoResumo, TotaisResumo, avaliar_apuracao

TIPOS_ELEITO = {"ELEITO_2T", "ELEITO_MAJORITARIO"}


def _eleito(ev):
    return [e["sq_candidato_a"] for e in ev if e["tipo"] in TIPOS_ELEITO]


def test_eleito_2t_bate_com_a_definicao_em_cenarios_aleatorios():
    rng = random.Random(20261025)
    for _ in range(20000):
        apto = rng.randint(1_000, 160_000_000)
        secoes = rng.randint(10, 500_000)
        tot_sec = rng.randint(0, secoes)
        apto_tot = min(apto, int(apto * tot_sec / secoes * rng.uniform(0.95, 1.05)))
        comp = int(apto_tot * rng.uniform(0.6, 0.9))
        a = rng.randint(0, comp)
        b = comp - a if rng.random() < 0.5 else rng.randint(0, comp - a)
        # Metade dos casos colados na fronteira b + r = a (±2 votos)
        r = apto - apto_tot
        if rng.random() < 0.5 and r < a:
            b = max(0, a - r + rng.randint(-2, 2))
        cargo = rng.choice([1, 3])
        cands = [CandidatoResumo("A", a), CandidatoResumo("B", b)]
        t = TotaisResumo(secoes, tot_sec, apto, apto_tot, a + b)
        ev = avaliar_apuracao(cands, t, cod_cargo=cargo, turno=2)

        lider, seg = ("A", "B") if a >= b else ("B", "A")
        va, vb = max(a, b), min(a, b)
        consistente = not (r == 0 and tot_sec < secoes)
        esperado = (tot_sec / secoes >= 0.20 and consistente and vb + r < va)
        if esperado:
            assert _eleito(ev) == [lider], (a, b, r, tot_sec, secoes)
        elif not (r == 0 and tot_sec == secoes and va == vb):
            assert _eleito(ev) == [], (a, b, r, tot_sec, secoes)


def test_fronteira_exata_nao_elege():
    # 2º + restantes == 1º: ainda pode empatar, ninguém eleito
    t = TotaisResumo(100, 90, 1_000, 900, 800)
    ev = avaliar_apuracao([CandidatoResumo("A", 450), CandidatoResumo("B", 350)], t, cod_cargo=1, turno=2)
    assert _eleito(ev) == []
    ev = avaliar_apuracao([CandidatoResumo("A", 451), CandidatoResumo("B", 350)], t, cod_cargo=1, turno=2)
    assert _eleito(ev) == ["A"]


def test_candidato_nao_ativo_nunca_e_eleito():
    t = TotaisResumo(100, 99, 1_000, 999, 900)
    cands = [CandidatoResumo("A", 800, situacao="cassado"), CandidatoResumo("B", 100)]
    assert "A" not in _eleito(avaliar_apuracao(cands, t, cod_cargo=1, turno=2))
