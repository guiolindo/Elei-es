import math
from datetime import datetime, timedelta, timezone

from math_engine.ritmo import prever_horario_99

T0 = datetime(2026, 10, 25, 21, 0, tzinfo=timezone.utc)
TOTAL = 100_000


def _serie(fracoes_por_minuto):
    return [(T0 + timedelta(minutes=m), int(f * TOTAL), TOTAL) for m, f in fracoes_por_minuto]


def test_queda_exponencial_acerta_o_horario():
    # Falta R(t) = 0.2·e^(−t/20): 80% em t=0. Chega a 1% em t = 20·ln(20) ≈ 59,9 min.
    k = 1 / 20
    pontos = _serie([(m, 1 - 0.2 * math.exp(-k * m)) for m in range(0, 40, 2)])
    eta = prever_horario_99(pontos)
    assert eta is not None
    esperado = T0 + timedelta(minutes=20 * math.log(20))
    assert abs((eta - esperado).total_seconds()) < 60


def test_abaixo_de_90_nao_preve():
    assert prever_horario_99(_serie([(0, 0.70), (15, 0.80), (20, 0.85)])) is None


def test_com_99_ou_mais_nao_preve():
    assert prever_horario_99(_serie([(0, 0.95), (15, 0.98), (20, 0.991)])) is None


def test_sem_ponto_de_15_min_atras_nao_preve():
    assert prever_horario_99(_serie([(10, 0.91), (14, 0.92), (20, 0.93)])) is None


def test_apuracao_parada_nao_preve():
    assert prever_horario_99(_serie([(0, 0.92), (15, 0.92), (20, 0.92)])) is None


def test_ritmo_muito_lento_nao_preve_horario_absurdo():
    assert prever_horario_99(_serie([(0, 0.9000), (15, 0.9001), (16, 0.9001)])) is None


def test_lista_vazia():
    assert prever_horario_99([]) is None
