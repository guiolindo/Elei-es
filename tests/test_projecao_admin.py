"""Modo admin: projeção desde o 1º boletim, com chance; público mantém os limites."""
from math_engine.projecao import Estrato, projetar_2t


def _estratos(fracao):
    return [Estrato(1_000_000, int(1_000_000 * fracao), int(800_000 * fracao), int(440_000 * fracao),
                    2_000, int(2_000 * fracao), 0.52)]


def test_publico_nao_projeta_abaixo_de_10():
    assert projetar_2t(_estratos(0.05)) is None


def test_admin_projeta_com_5_por_cento_e_mostra_chance():
    p = projetar_2t(_estratos(0.05), sem_limites=True)
    assert p is not None and p.exibir_probabilidade and not p.probabilidade_previa


def test_publico_com_20_por_cento_nao_mostra_chance():
    p = projetar_2t(_estratos(0.20))
    assert p is not None and not p.exibir_probabilidade
