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


def matematicamente_eliminado(
    candidato: CandidatoResumo,
    candidatos: Sequence[CandidatoResumo],
    totais: TotaisResumo,
    posicoes_relevantes: int = 2,
) -> bool:
    """True se o candidato NÃO PODE chegar entre os `posicoes_relevantes`
    primeiros nem com todos os votos restantes.

    Para Presidente (cargo=1), posicoes_relevantes=2 (top 2 vai pro 2T).
    Para majoritários (Gov, Sen), posicoes_relevantes=1 (só ganha 1).
    """
    if candidato not in candidatos:
        return False
    ordenados = sorted(candidatos, key=lambda c: c.votos, reverse=True)
    restantes = votos_restantes_max(totais)
    max_final_cand = candidato.votos + restantes
    # Precisa ficar melhor que o `posicoes_relevantes`-ésimo colocado
    # já contando com o cenário em que ninguém à frente dele muda.
    pos_alvo = ordenados[posicoes_relevantes - 1] if len(ordenados) >= posicoes_relevantes else None
    if pos_alvo is None or pos_alvo.sq_candidato == candidato.sq_candidato:
        return False
    # Está eliminado se mesmo somando tudo, ainda fica ATRÁS do alvo (estrito)
    return max_final_cand < pos_alvo.votos


def virada_iminente(
    candidatos: Sequence[CandidatoResumo],
    totais: TotaisResumo,
    limite_pct: float = 0.10,
) -> tuple[bool, float]:
    """Detecta se a distância entre 1º e 2º é menor que `limite_pct` dos
    votos restantes — ou seja, virada possível em qualquer novo snapshot.

    Retorna (é_iminente, razao) onde razao = diferença / restantes.
    """
    if len(candidatos) < 2:
        return False, 0.0
    ordenados = sorted(candidatos, key=lambda c: c.votos, reverse=True)
    diff = ordenados[0].votos - ordenados[1].votos
    restantes = votos_restantes_max(totais)
    if restantes <= 0:
        return False, 0.0
    razao = diff / restantes
    return razao < limite_pct, razao


def margem_de_seguranca(
    candidatos: Sequence[CandidatoResumo],
    totais: TotaisResumo,
) -> float:
    """Quantos pontos percentuais o líder pode perder e ainda vencer.
    Retorna 0 se está no fio, 100 se já é 100% garantido, negativo se
    já perdeu. Útil pra gauge de "probabilidade matemática" na UI.
    """
    if len(candidatos) < 2:
        return 100.0
    ordenados = sorted(candidatos, key=lambda c: c.votos, reverse=True)
    a, b = ordenados[0], ordenados[1]
    restantes = votos_restantes_max(totais)
    # Cenário pior pro líder: tudo vira pro 2º
    # Ele mantém vitória se a.votos > b.votos + restantes
    # Margem = (a.votos - (b.votos + restantes)) / max(a.votos, 1) * 100
    if a.votos == 0:
        return 0.0
    margem = (a.votos - (b.votos + restantes)) / a.votos * 100
    return max(-100.0, min(100.0, margem))


def projecao_final(
    candidato: CandidatoResumo,
    totais: TotaisResumo,
) -> int:
    """Projeção linear simples do total final de votos: extrapola pelo
    % apurado. Só faz sentido depois de 20-30% apurado; antes disso
    varia muito. NÃO é preditivo, é aritmético.
    """
    pct = pct_apurado(totais)
    if pct <= 0:
        return candidato.votos
    return int(candidato.votos / pct)


def detectar_viradas(
    candidatos_atual: Sequence[CandidatoResumo],
    candidatos_anterior: Sequence[CandidatoResumo],
) -> list[dict]:
    """Detecta ultrapassagens entre snapshots consecutivos.

    Retorna eventos {'tipo': 'VIRADA', 'sq_candidato_a': ..., 'sq_candidato_b': ...}
    onde A passou a estar à frente de B.
    """
    if not candidatos_atual or not candidatos_anterior:
        return []
    pos_anterior = {c.sq_candidato: i for i, c in
                    enumerate(sorted(candidatos_anterior, key=lambda x: x.votos, reverse=True))}
    pos_atual = {c.sq_candidato: i for i, c in
                 enumerate(sorted(candidatos_atual, key=lambda x: x.votos, reverse=True))}
    eventos = []
    # Só reporta viradas entre top-5 (evita ruído nos deputados)
    top = sorted(candidatos_atual, key=lambda c: c.votos, reverse=True)[:5]
    for c in top:
        sq = c.sq_candidato
        if sq not in pos_anterior or sq not in pos_atual:
            continue
        if pos_atual[sq] < pos_anterior[sq]:
            # Subiu — descobre quem ele passou
            for outro in candidatos_atual:
                if outro.sq_candidato == sq:
                    continue
                if (pos_anterior.get(outro.sq_candidato, -1) < pos_anterior[sq] and
                    pos_atual.get(outro.sq_candidato, -1) > pos_atual[sq]):
                    eventos.append({
                        "tipo": "VIRADA",
                        "sq_candidato_a": sq,
                        "sq_candidato_b": outro.sq_candidato,
                        "detalhes": {
                            "pos_nova": pos_atual[sq] + 1,
                            "pos_antiga": pos_anterior[sq] + 1,
                        },
                    })
    return eventos


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

    # Reporta MATEMATICAMENTE_ELIMINADO só se ninguém foi eleito ainda
    # (senão vira ruído — óbvio que todos os outros estão eliminados quando
    # tem eleito). Só olha candidatos que ainda apareciam como contenders
    # (top 5) e que não são já 1º ou 2º colocado.
    if not eventos:
        pos_relevantes = 2 if cod_cargo == 1 else 1
        for c in ordenados[pos_relevantes:5]:
            if matematicamente_eliminado(c, ordenados, totais, pos_relevantes):
                eventos.append({
                    "tipo": "MATEMATICAMENTE_ELIMINADO",
                    "sq_candidato_a": c.sq_candidato,
                    "detalhes": {
                        "votos_max": c.votos + votos_restantes_max(totais),
                        "alvo_top": pos_relevantes,
                    },
                })
    return eventos
