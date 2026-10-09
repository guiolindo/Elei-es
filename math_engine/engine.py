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
    # Idade em anos completos na data da eleição. Opcional — só usada
    # pra desempate no 2º turno (art. 110 Código Eleitoral: "em caso de
    # empate haver-se-á por eleito o mais idoso"). Se não fornecida, o
    # motor NÃO tenta desempatar e mantém a eleição em disputa.
    idade_anos: int | None = None
    # Situação do candidato ('ativo', 'renunciou', 'cancelado',
    # 'indeferido_sem_recurso', 'cassado'). Candidatos não-ativos ainda
    # podem receber votos (TSE publica), mas o motor os EXCLUI do
    # cálculo de "eleito" e "2º turno" porque Lei 9.504/97 art. 175 §3º
    # trata esses votos como nulos. Default 'ativo' pra compat.
    situacao: str = "ativo"


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
    """2º turno matematicamente definido — **duas** condições estritas:

    1. O 1º colocado NÃO consegue mais vencer no 1º turno (i.e., não
       atinge > 50% dos válidos no melhor cenário pra ele).
    2. O 3º colocado NÃO consegue mais ultrapassar o 2º.

    Faltava (1) na versão anterior — era possível declarar "2º turno
    definido" quando o líder ainda podia disparar acima de 50% e vencer
    no primeiro turno, invalidando o próprio conceito. Bug relatado pelo
    QA e coberto pelo test_segundo_turno_nao_definido_lider_pode_vencer_1t.
    """
    if len(candidatos) < 3:
        return False
    a, b, c = candidatos[0], candidatos[1], candidatos[2]
    restantes = votos_restantes_max(totais)
    total_validos_max = totais.qt_votos_validos + restantes
    # Cond. 1: no MELHOR cenário pro líder (ele leva todos os restantes),
    # ainda assim não ultrapassa 50% dos válidos possíveis?
    lider_pode_vencer_1t = (a.votos + restantes) * 2 > total_validos_max
    if lider_pode_vencer_1t:
        return False
    # Cond. 2: 3º não alcança 2º, mesmo levando tudo
    return (c.votos + restantes) < b.votos


def eleito_majoritario(
    candidatos: Sequence[CandidatoResumo],
    totais: TotaisResumo,
    exige_maioria_absoluta: bool = False,
) -> bool:
    """Cargo majoritário de 1 vaga (Governador, Prefeito >200k, ou Senador
    em ano de 1/3).

    Duas famílias de regra na CF:
    - **Maioria simples** (Senador — art. 46 CF; Prefeito de município
      ≤200k eleitores — art. 29): eleito quando 1º é inalcançável pelo 2º.
    - **Maioria absoluta** (Governador — art. 28 CF remete ao art. 77 §2º;
      Prefeito >200k): além de inalcançável, o líder precisa ter GARANTIA
      matemática de terminar com > 50% dos votos válidos. Se pode ficar
      com ≤ 50%, vai a 2º turno.

    `exige_maioria_absoluta=True` habilita a segunda regra.

    Bug histórico: versão anterior tratava governador igual a senador —
    declarava eleito no 1T mesmo quando ele ainda podia terminar com <50%
    e ir a 2T. Coberto por test_governador_precisa_maioria_absoluta_1t.
    """
    if len(candidatos) < 2:
        return len(candidatos) == 1 and votos_restantes_max(totais) == 0
    a = candidatos[0]
    b = candidatos[1]
    restantes = votos_restantes_max(totais)
    # Condição base — inalcançável pelo 2º (vale pra ambas as famílias)
    if not (b.votos + restantes < a.votos):
        return False
    if exige_maioria_absoluta:
        # Pior cenário do líder: mantém votos atuais mas TODOS os restantes
        # viram válidos (denominador cresce, numerador não). Precisa que
        # 2 × a.votos > validos_finais_max
        total_validos_max = totais.qt_votos_validos + restantes
        return a.votos * 2 > total_validos_max
    return True


# Cargos que exigem maioria absoluta no 1º turno (senão vai a 2T).
# Ver CF art. 77 §2º (Presidente), art. 28 (Governador), art. 29 XII (Prefeito >200k).
CARGO_EXIGE_MAIORIA_ABSOLUTA = {
    1: True,   # Presidente
    3: True,   # Governador
    5: False,  # Senador — art. 46 CF, maioria simples
    # 4: True,   # Prefeito >200k (não no escopo — este app é federal/estadual)
}


def eleitos_majoritario_multivaga(
    candidatos: Sequence[CandidatoResumo], totais: TotaisResumo, vagas: int,
) -> list[CandidatoResumo]:
    """Majoritário com N vagas (Senador em ano de 2/3 = 2 vagas por UF em 2026).

    Retorna a lista dos top-N candidatos SOMENTE se todos os N estão
    matematicamente garantidos — ou seja, o N-ésimo colocado tem margem
    estrita sobre o (N+1)-ésimo levando em conta os restantes. Se ainda
    houver possibilidade de troca no top-N, retorna [].

    QA apontou: em 2026 elege-se 2 senadores por estado. A versão anterior
    tratava senador como 1 vaga só (eleito_majoritario), o que declarava
    eleito o líder mesmo com margem estreita sobre o 2º — mas em 2026 o 2º
    também é eleito, então "eleição definida" precisa envolver o 3º.
    """
    if vagas < 1 or not candidatos:
        return []
    if len(candidatos) <= vagas:
        return list(candidatos) if votos_restantes_max(totais) == 0 else []
    restantes = votos_restantes_max(totais)
    n_esimo = candidatos[vagas - 1]
    primeiro_suplente = candidatos[vagas]
    # Caso normal: N-ésimo é estritamente inalcançável pelo suplente
    if n_esimo.votos > primeiro_suplente.votos + restantes:
        return list(candidatos[:vagas])
    # Empate exato no fechamento (100% apurado): art. 110 CE manda eleger
    # o mais idoso. Só decide se as duas idades são conhecidas e diferentes.
    if (restantes == 0
            and n_esimo.votos == primeiro_suplente.votos
            and n_esimo.idade_anos is not None
            and primeiro_suplente.idade_anos is not None
            and n_esimo.idade_anos != primeiro_suplente.idade_anos):
        if n_esimo.idade_anos > primeiro_suplente.idade_anos:
            return list(candidatos[:vagas])  # N-ésimo é mais velho → eleito
        # Suplente é mais velho → ocupa a última vaga, N-ésimo sai
        return list(candidatos[:vagas - 1]) + [primeiro_suplente]
    return []


# Vagas majoritárias por cargo/ano — Senador varia (2026: 2 vagas por UF)
VAGAS_MAJORITARIO_PADRAO = {
    1: 1,   # Presidente (2º turno se ninguém tiver maioria)
    3: 1,   # Governador (2º turno se ninguém tiver maioria; 1 eleito)
    5: 2,   # Senador em 2026 (renovação de 2/3). Em 2018/2022 era 1.
}


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
    # Se `candidatos` já é a lista ordenada, evita re-sort (fast path).
    if all(candidatos[i].votos >= candidatos[i+1].votos for i in range(len(candidatos)-1)):
        ordenados = list(candidatos)
    else:
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
    # Fast path: se já vem ordenado, evita nova ordenação
    if candidatos[0].votos >= candidatos[1].votos:
        a, b = candidatos[0], candidatos[1]
    else:
        ordenados = sorted(candidatos, key=lambda c: c.votos, reverse=True)
        a, b = ordenados[0], ordenados[1]
    diff = a.votos - b.votos
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
    if candidatos[0].votos >= candidatos[1].votos:
        a, b = candidatos[0], candidatos[1]
    else:
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
    # Exclui candidatos não-ativos (retirados/cassados) — votos deles são
    # nulos (art. 175 §3º) e não constituem virada legítima.
    candidatos_atual = [c for c in candidatos_atual if c.situacao == "ativo"]
    candidatos_anterior = [c for c in candidatos_anterior if c.situacao == "ativo"]
    if not candidatos_atual or not candidatos_anterior:
        return []
    # Pré-apuração todos os candidatos têm 0 votos — a ordem fica arbitrária
    # (vem do TSE conforme ele lista) e muda entre snapshots sem significado.
    # Comparar essas ordens emitia "FULANO passou SICRANO" fantasma na timeline
    # com 0% apurado. Só compara se há algum voto de verdade dos dois lados.
    if (sum(c.votos for c in candidatos_atual) == 0
            or sum(c.votos for c in candidatos_anterior) == 0):
        return []
    # Mapas de VOTOS por sq (não só posição) — pra ter critério objetivo
    # de "A está à frente de B": A.votos > B.votos. Posição com empate é
    # ambígua e varia conforme ordem de inserção.
    votos_ant = {c.sq_candidato: c.votos for c in candidatos_anterior}
    votos_now = {c.sq_candidato: c.votos for c in candidatos_atual}
    pos_anterior = {c.sq_candidato: i for i, c in
                    enumerate(sorted(candidatos_anterior, key=lambda x: x.votos, reverse=True))}
    pos_atual = {c.sq_candidato: i for i, c in
                 enumerate(sorted(candidatos_atual, key=lambda x: x.votos, reverse=True))}
    eventos = []
    # Só reporta viradas entre top-5 (evita ruído nos deputados)
    top = sorted(candidatos_atual, key=lambda c: c.votos, reverse=True)[:5]
    # Sentinel = tamanho da lista (posição imaginária "atrás de todos");
    # candidatos que não existiam no anterior ficam com essa posição e nunca
    # são contados como "estavam à frente". Antes usávamos -1, que fazia
    # `-1 < pos_anterior[sq]` retornar True e disparar viradas fantasma.
    LEN_A = len(pos_anterior)
    LEN_B = len(pos_atual)
    for c in top:
        sq = c.sq_candidato
        if sq not in pos_anterior or sq not in pos_atual:
            continue
        if pos_atual[sq] < pos_anterior[sq]:
            # Subiu — descobre quem ele passou
            for outro in candidatos_atual:
                if outro.sq_candidato == sq:
                    continue
                outro_sq = outro.sq_candidato
                # Validação ESTRITA por votos: só é virada legítima se
                # ANTES o outro tinha mais votos E AGORA eu tenho mais.
                # Empate (votos iguais) não é virada — proíbe ping-pong
                # fantasma quando dois candidatos têm exatamente a mesma
                # votação e a ordem oscila entre snapshots.
                if not (votos_ant.get(outro_sq, 0) > votos_ant.get(sq, 0)
                        and votos_now.get(sq, 0) > votos_now.get(outro_sq, 0)):
                    continue
                if (pos_anterior.get(outro_sq, LEN_A) < pos_anterior[sq] and
                    pos_atual.get(outro_sq, LEN_B) > pos_atual[sq]):
                    eventos.append({
                        "tipo": "VIRADA",
                        "sq_candidato_a": sq,
                        "sq_candidato_b": outro_sq,
                        "detalhes": {
                            "pos_nova": pos_atual[sq] + 1,
                            "pos_antiga": pos_anterior[sq] + 1,
                        },
                    })
    return eventos


def _avaliar_2_turno(
    candidatos: Sequence[CandidatoResumo],
    totais: TotaisResumo,
    cod_cargo: int,
) -> list[dict]:
    """Motor específico do 2º turno.

    Cenário: apenas 2 candidatos disputam. Vence quem tiver mais votos
    ao final — não existe 3T. Portanto:

    - Só faz sentido pra cargos com 2T (Presidente, Governador).
    - Emite ELEITO_2T (Pres) ou ELEITO_MAJORITARIO turno=2 (Gov) quando
      o 2º colocado é matematicamente inalcançável pelo 1º:
        b.votos + restantes_max < a.votos
      Que, com apenas 2 candidatos, equivale a "o líder já garantiu
      maioria absoluta dos válidos finais".
    - Emite MATEMATICAMENTE_ELIMINADO pro segundo colocado quando ele
      já não pode alcançar o 1º.
    - Não emite SEGUNDO_TURNO_DEFINIDO (não existe 3º turno).
    - Não emite VIRADA aqui — quem estava atrás pode virar e viraria
      via detectar_viradas (chamado à parte pelo poller).
    """
    if cod_cargo not in (1, 3):
        # Cargos sem 2T (Senador, Deputado) não deveriam nem chegar aqui
        return []
    ordenados = sorted(candidatos, key=lambda c: c.votos, reverse=True)
    if len(ordenados) < 2:
        return []
    a, b = ordenados[0], ordenados[1]
    restantes = votos_restantes_max(totais)
    eventos: list[dict] = []
    if b.votos + restantes < a.votos:
        # Líder inalcançável = 2º eliminado = eleição decidida.
        # Emite os DOIS eventos: vencedor + eliminado (relevância editorial).
        tipo_ganhador = "ELEITO_2T" if cod_cargo == 1 else "ELEITO_MAJORITARIO"
        eventos.append({
            "tipo": tipo_ganhador,
            "sq_candidato_a": a.sq_candidato,
            "detalhes": {
                "votos": a.votos,
                "cod_cargo": cod_cargo,
                "turno": 2,
                "margem": a.votos - b.votos,
            },
        })
        eventos.append({
            "tipo": "MATEMATICAMENTE_ELIMINADO",
            "sq_candidato_a": b.sq_candidato,
            "detalhes": {"votos_max": b.votos + restantes, "turno": 2,
                         "cod_cargo": cod_cargo},
        })
        return eventos

    # Caso raro: empate matemático quando 100% apurado (restantes==0).
    # Art. 110 do Código Eleitoral: em caso de empate, considera-se
    # eleito o mais idoso. Só aplicável se idade dos dois foi fornecida
    # em CandidatoResumo. Sem idade, motor NÃO decide — mantém em
    # disputa (TSE fará o desempate).
    if restantes == 0 and a.votos == b.votos:
        if a.idade_anos is not None and b.idade_anos is not None and a.idade_anos != b.idade_anos:
            mais_velho, mais_novo = (a, b) if a.idade_anos > b.idade_anos else (b, a)
            tipo_ganhador = "ELEITO_2T" if cod_cargo == 1 else "ELEITO_MAJORITARIO"
            eventos.append({
                "tipo": tipo_ganhador,
                "sq_candidato_a": mais_velho.sq_candidato,
                "detalhes": {
                    "votos": mais_velho.votos,
                    "cod_cargo": cod_cargo,
                    "turno": 2,
                    "margem": 0,
                    "criterio_desempate": "idade_art_110_ce",
                    "idade_vencedor": mais_velho.idade_anos,
                    "idade_perdedor": mais_novo.idade_anos,
                },
            })
            eventos.append({
                "tipo": "MATEMATICAMENTE_ELIMINADO",
                "sq_candidato_a": mais_novo.sq_candidato,
                "detalhes": {"votos_max": mais_novo.votos, "turno": 2,
                             "cod_cargo": cod_cargo,
                             "criterio_desempate": "idade_art_110_ce"},
            })
    return eventos


def avaliar_apuracao(
    candidatos: Sequence[CandidatoResumo],
    totais: TotaisResumo,
    cod_cargo: int,
    vagas_majoritario: int | None = None,
    turno: int = 1,
) -> list[dict]:
    """Retorna eventos matemáticos disparados por este snapshot.

    Só executa se >= APURACAO_MIN_PCT das seções foram totalizadas — antes
    disso o limite superior é gigante e nenhuma desigualdade fecha.

    Cargos:
      - 1 (Presidente):  1T = eleito 1T ou 2T definido; 2T = eleito 2T
      - 3 (Governador):  mesma regra do Presidente (CF art. 28 → art. 77)
      - 5 (Senador):     maioria simples; 2026 elege 2/UF (multi-vaga)
      - 6/7 (Dep):       proporcional, avaliar_apuracao não se aplica

    `turno`:
      - 1 (default): pode emitir ELEITO_1T, SEGUNDO_TURNO_DEFINIDO,
                     ELEITO_MAJORITARIO (com maioria_absoluta True/False)
      - 2:           só disputa entre 2 candidatos, quem tem mais vence.
                     Emite ELEITO_2T (Presidente) ou ELEITO_MAJORITARIO
                     com turno=2 (Governador). Não emite 2T definido.

    Nota matemática do 2T: com apenas 2 candidatos, "inalcançabilidade"
    e "maioria absoluta" colapsam na mesma condição (A > B + restantes),
    porque validos = A + B → A × 2 > A + B + restantes ⇔ A > B + restantes.

    `vagas_majoritario` sobrescreve o default do cargo (útil pra ano com
    renovação de 1/3 do Senado).
    """
    if pct_apurado(totais) < APURACAO_MIN_PCT:
        return []
    # EARLY RETURN pra cargos proporcionais (Dep Federal=6, Dep Estadual=7).
    # Esta função avaliar_apuracao() calcula apenas ELEITO/MATEMATICAMENTE_
    # ELIMINADO MAJORITÁRIO (quem tem mais votos ganha). Pra proporcional
    # (QE/QP/sobras/D'Hondt) o cálculo está em math_engine.proporcional e
    # é exposto via /api/apuracao/proporcional separado.
    #
    # Bug 05/10/2026 20:47 BRT em SP Dep Fed: engine aplicava lógica
    # majoritária com vagas=1 (default), marcando Sâmia Bomfim, Kim
    # Kataguiri e dezenas de outros TOP candidatos (que o motor proporcional
    # tinha corretamente marcado como "✓ ELEITO · FED") como MATEMATICAMENTE_
    # ELIMINADO porque não estavam no top-1. Resultado visual: candidato
    # com AMBAS as tarjas verde (eleito) e vermelha (sem chance) ao mesmo
    # tempo — contradição absoluta.
    if cod_cargo in (6, 7):
        return []
    # EXCLUSÃO LEGAL: candidatos com situação não-ativa recebem votos no
    # TSE mas por Lei 9.504/97 art. 175 §3º esses votos são considerados
    # nulos na apuração oficial. Motor os remove ANTES de qualquer
    # cálculo pra não emitir "eleito" num candidato cassado/retirado.
    votos_nao_ativos = sum(c.votos for c in candidatos if c.situacao != "ativo")
    candidatos = [c for c in candidatos if c.situacao == "ativo"]
    if not candidatos:
        return []
    # AJUSTE DE DENOMINADOR: qt_votos_validos vem do parser que soma TODOS
    # os cand.vap (ativos + sub judice/indeferidos) pra proteger contra o
    # TSE separar sub judice do v.vv (bug RJ Gov 05/10/2026). Mas quando
    # algum candidato vira CASSADO/CANCELADO definitivamente, seus votos
    # viram NULOS pela Lei 9.504 art. 175 §3º — precisa descontar do
    # denominador. Senão o pct de maioria absoluta fica subestimado e o
    # engine deixa de emitir ELEITO_1T quando devia.
    #
    # Caso real RJ Gov pós-julgamento Garotinho (09/10/2026): com Garotinho
    # ativo (sub judice), válidos = 8.669.038 → líder 49,27%, vai pra 2T.
    # Com Garotinho CANCELADO (recurso rejeitado), seus 274k votos saem do
    # denominador → válidos = 8.394.627 → líder 50,88% → ELEITO_1T.
    if votos_nao_ativos > 0:
        validos_ajustados = max(
            totais.qt_votos_validos - votos_nao_ativos,
            sum(c.votos for c in candidatos),
        )
        totais = TotaisResumo(
            qt_secoes_total=totais.qt_secoes_total,
            qt_secoes_totalizadas=totais.qt_secoes_totalizadas,
            qt_eleitorado_apto=totais.qt_eleitorado_apto,
            qt_eleitorado_apto_totalizadas=totais.qt_eleitorado_apto_totalizadas,
            qt_votos_validos=validos_ajustados,
        )
    # 2º turno é uma máquina separada — só faz sentido pra cargos que
    # exigem maioria absoluta no 1T (Presidente, Governador).
    if turno == 2:
        return _avaliar_2_turno(candidatos, totais, cod_cargo)
    # Otimização: ordena UMA vez. As funções internas trabalham em cima
    # do já-ordenado (Sequence).
    ordenados = sorted(candidatos, key=lambda c: c.votos, reverse=True)
    eventos: list[dict] = []

    exige_ma = CARGO_EXIGE_MAIORIA_ABSOLUTA.get(cod_cargo, False)
    vagas = vagas_majoritario if vagas_majoritario is not None else \
            VAGAS_MAJORITARIO_PADRAO.get(cod_cargo, 1)

    if exige_ma and vagas == 1:
        # Presidente OU Governador: mesma regra constitucional (art. 77 §2º
        # + art. 28). Bifurca em eleito 1T (maioria absoluta) ou 2T definido.
        # Os dois cargos usam as mesmas duas funções — a distinção anterior
        # (Presidente separado, Governador no bloco genérico) era artificial.
        if eleito_1t_presidencial(ordenados, totais):
            eventos.append({
                "tipo": "ELEITO_1T" if cod_cargo == 1 else "ELEITO_MAJORITARIO",
                "sq_candidato_a": ordenados[0].sq_candidato,
                "detalhes": {"votos": ordenados[0].votos, "cod_cargo": cod_cargo,
                             "maioria_absoluta": True},
            })
        elif segundo_turno_definido(ordenados, totais):
            eventos.append({
                "tipo": "SEGUNDO_TURNO_DEFINIDO",
                "sq_candidato_a": ordenados[0].sq_candidato,
                "sq_candidato_b": ordenados[1].sq_candidato,
                "detalhes": {
                    "votos_a": ordenados[0].votos,
                    "votos_b": ordenados[1].votos,
                    "cod_cargo": cod_cargo,
                },
            })
    elif vagas > 1:
        # Senador em ano de renovação 2/3 (2026 = 2 vagas por UF).
        # Maioria simples multi-vaga: top-N são eleitos quando o N-ésimo
        # é inalcançável pelo (N+1)-ésimo.
        eleitos = eleitos_majoritario_multivaga(ordenados, totais, vagas)
        for pos, e in enumerate(eleitos, start=1):
            eventos.append({
                "tipo": "ELEITO_MAJORITARIO",
                "sq_candidato_a": e.sq_candidato,
                "detalhes": {"votos": e.votos, "cod_cargo": cod_cargo,
                             "vagas": vagas, "posicao": pos},
            })
    else:
        # Maioria simples 1 vaga (Senador em ano de 1/3, etc)
        if eleito_majoritario(ordenados, totais, exige_maioria_absoluta=False):
            eventos.append({
                "tipo": "ELEITO_MAJORITARIO",
                "sq_candidato_a": ordenados[0].sq_candidato,
                "detalhes": {"votos": ordenados[0].votos, "cod_cargo": cod_cargo,
                             "maioria_absoluta": False},
            })

    # MATEMATICAMENTE_ELIMINADO — pos_relevantes é o tamanho do grupo
    # de "vagas de continuidade":
    #   - ELEITO_1T/MAJORITARIO (1 vaga): só o eleito continua
    #   - SEGUNDO_TURNO_DEFINIDO: top 2 continua pro 2T
    #   - Senador multivaga: top N são eleitos
    #   - Sem evento ainda: usa pos_relevantes do cargo
    #
    # Bug detectado 20:50 BRT em PR Governador 99.89%: Sérgio Moro foi
    # marcado ELEITO MATEMATICAMENTE mas o 2º colocado (Sandro Alex) e
    # o 3º (Requião Filho) ficavam sem tarja de eliminado — causa: o
    # loop estava dentro de `if not eventos`, pulava quando ELEITO era
    # emitido. Agora o loop roda SEMPRE, só muda pos_relevantes baseado
    # em qual evento majoritário foi emitido.
    tipos_eleito = {"ELEITO_1T", "ELEITO_MAJORITARIO"}
    emitiu_eleito = any(e["tipo"] in tipos_eleito for e in eventos)
    emitiu_2t = any(e["tipo"] == "SEGUNDO_TURNO_DEFINIDO" for e in eventos)
    if emitiu_eleito:
        # Eleição definida — todo mundo abaixo da(s) vaga(s) é eliminado
        pos_relevantes = vagas
    elif emitiu_2t:
        # 2T definido — só os 2 de cima continuam
        pos_relevantes = 2
    elif exige_ma and vagas == 1:
        # Pres/Gov sem evento ainda: top 2 pode continuar (via 2T futuro)
        pos_relevantes = 2
    else:
        # Majoritário multivaga sem eleito ainda, ou cargo com simples maioria
        pos_relevantes = vagas
    # Avalia TODOS os candidatos abaixo das posições relevantes, não
    # só os 3º-5º. Bug detectado 05/10/2026 em DF Senador: engine só
    # emitia MATEMATICAMENTE_ELIMINADO pros top-5, mesmo os candidatos
    # das posições 6-11 (com <0.5% dos votos e sem chance aritmética
    # alguma) ficavam sem tarja. O custo é O(n) por candidato × n
    # candidatos restantes = O(n²), mas com n < 50 por cargo/UF o
    # overhead é desprezível.
    for c in ordenados[pos_relevantes:]:
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
