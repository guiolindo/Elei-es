"""Motor matemático de definição de resultado.

Módulo puro, sem dependências externas: recebe totais e candidatos ordenados
por votação e decide se um resultado já está matematicamente fechado usando o
total de votos que ainda podem entrar como limite superior. Todas as
desigualdades são estritas — enquanto empate exato ainda for possível, o
resultado é considerado em disputa.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence


APURACAO_MIN_PCT = 0.20  # motor só corre com >=20% das seções totalizadas


@dataclass(frozen=True)
class CandidatoResumo:
    sq_candidato: str
    votos: int


@dataclass(frozen=True)
class TotaisResumo:
    qt_secoes_total: int
    qt_secoes_totalizadas: int
    qt_eleitorado_apto: int
    qt_eleitorado_apto_totalizadas: int
    qt_votos_validos: int


def _clamp_nao_negativo(n: int) -> int:
    return n if n > 0 else 0


def votos_restantes_max(totais: TotaisResumo) -> int:
    """Limite superior de votos que ainda podem entrar na apuração.

    Baseado no eleitorado apto das seções ainda não totalizadas. Se o TSE
    reportar valores inconsistentes (totalizadas > apto), tratamos como 0
    para não gerar limites negativos.
    """
    return _clamp_nao_negativo(
        totais.qt_eleitorado_apto - totais.qt_eleitorado_apto_totalizadas
    )


def pct_apurado(totais: TotaisResumo) -> float:
    if totais.qt_secoes_total <= 0:
        return 0.0
    return totais.qt_secoes_totalizadas / totais.qt_secoes_total


def eleito_1t_presidencial(candidatos: Sequence[CandidatoResumo], totais: TotaisResumo) -> bool:
    """Presidencial: eleito no 1º turno se mesmo no pior cenário (todos os
    votos restantes viram válidos e vão para adversários) o líder mantém
    mais da metade dos válidos.
    """
    if not candidatos:
        return False
    lider = candidatos[0]
    restantes = votos_restantes_max(totais)
    total_validos_max = totais.qt_votos_validos + restantes
    # estrito: se lider.votos == metade, empate técnico ainda é possível
    return lider.votos * 2 > total_validos_max


def segundo_turno_definido(candidatos: Sequence[CandidatoResumo], totais: TotaisResumo) -> bool:
    """2º turno matematicamente definido: 2º colocado tem vantagem sobre o 3º
    maior que qualquer soma de votos restantes que ainda possam ir ao 3º.
    """
    if len(candidatos) < 3:
        return False
    b = candidatos[1]
    c = candidatos[2]
    restantes = votos_restantes_max(totais)
    # estrito: c.votos + restantes < b.votos
    return c.votos + restantes < b.votos


def eleito_majoritario(candidatos: Sequence[CandidatoResumo], totais: TotaisResumo) -> bool:
    """Governador/Senador/Prefeito (majoritário simples): eleito quando 1º
    colocado é inalcançável pelo 2º, mesmo se todos os votos restantes forem
    para ele.
    """
    if len(candidatos) < 2:
        return len(candidatos) == 1 and votos_restantes_max(totais) == 0
    a = candidatos[0]
    b = candidatos[1]
    restantes = votos_restantes_max(totais)
    return b.votos + restantes < a.votos


def avaliar_apuracao(
    candidatos: Sequence[CandidatoResumo],
    totais: TotaisResumo,
    cod_cargo: int,
) -> list[dict]:
    """Retorna eventos matemáticos disparados por este snapshot.

    Só executa se >= APURACAO_MIN_PCT das seções foram totalizadas — antes
    disso o limite superior é gigante e nenhuma desigualdade fecha.
    Cargo 1 = Presidente. Demais majoritários (3=Governador, 5=Senador)
    usam a regra maioria simples.
    """
    if pct_apurado(totais) < APURACAO_MIN_PCT:
        return []
    ordenados = sorted(candidatos, key=lambda c: c.votos, reverse=True)
    eventos: list[dict] = []
    if cod_cargo == 1:
        if eleito_1t_presidencial(ordenados, totais):
            eventos.append({
                "tipo": "ELEITO_1T",
                "sq_candidato_a": ordenados[0].sq_candidato,
                "detalhes": {"votos": ordenados[0].votos},
            })
        elif segundo_turno_definido(ordenados, totais):
            eventos.append({
                "tipo": "SEGUNDO_TURNO_DEFINIDO",
                "sq_candidato_a": ordenados[0].sq_candidato,
                "sq_candidato_b": ordenados[1].sq_candidato,
                "detalhes": {
                    "votos_a": ordenados[0].votos,
                    "votos_b": ordenados[1].votos,
                },
            })
    else:
        if eleito_majoritario(ordenados, totais):
            eventos.append({
                "tipo": "ELEITO_MAJORITARIO",
                "sq_candidato_a": ordenados[0].sq_candidato,
                "detalhes": {"votos": ordenados[0].votos, "cod_cargo": cod_cargo},
            })
    return eventos
