"""Horário previsto para 99% das seções apuradas, pelo ritmo da apuração.

Puro, sem I/O. Supõe que o ritmo cai junto com o que falta: a fração que
falta R(t) diminui como R0·e^(−k·t), com k medido nos últimos ~15 minutos.

Validação com boletins de urna reais de 2022 (horário de recebimento de
cada urna, scripts/validacao_2t): a partir de 90% apurado o erro médio
foi de 10 min nos 12 segundos turnos de governador (pior +20) e de 8 min
no de presidente; com 80% o erro médio era 27 min, por isso só a partir
de 90%. O alvo é 99% e não 100%: em 2022 os 99% vieram às 20h00 e os
100% só à 0h17 (poucas urnas atrasadas, sem padrão previsível).
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta

FRACAO_MIN = 0.90      # só mostra a partir daqui (validação acima)
ALVO = 0.99
JANELA_MIN = 15.0      # minutos para medir o ritmo
JANELA_MIN_ACEITA = 8.0
HORIZONTE_MAX = timedelta(hours=6)


def prever_horario_99(pontos: list[tuple[datetime, int, int]]) -> datetime | None:
    """pontos: (instante, seções totalizadas, seções no total), em ordem.

    None quando ainda não dá para prever: menos de 90% ou já 99% apurado,
    sem ponto de ~15 min atrás, ritmo parado ou previsão absurda."""
    if not pontos:
        return None
    t, tot, total = pontos[-1]
    if total <= 0:
        return None
    f = tot / total
    if f < FRACAO_MIN or f >= ALVO:
        return None
    alvo_t = t - timedelta(minutes=JANELA_MIN)
    anteriores = [p for p in pontos[:-1] if p[0] <= alvo_t]
    if not anteriores:
        return None
    t0, tot0, total0 = anteriores[-1]
    if total0 <= 0:
        return None
    minutos = (t - t0).total_seconds() / 60
    if minutos < JANELA_MIN_ACEITA:
        return None
    r, r0 = 1 - f, 1 - tot0 / total0
    if r0 <= r or r <= 0:
        return None
    k = math.log(r0 / r) / minutos
    falta = math.log(r / (1 - ALVO)) / k
    eta = t + timedelta(minutes=falta)
    if eta - t > HORIZONTE_MAX:
        return None
    return eta
