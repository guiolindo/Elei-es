"""Cálculo de eleitos em pleitos proporcionais (Deputado Federal/Estadual).

Regras vigentes em 2026 (Código Eleitoral + Lei 14.211/2021 + jurisprudência STF):

1. **Quociente Eleitoral (QE)** = int(votos_validos / vagas).
   Votos válidos = votos nominais + votos de legenda.

2. **Quociente Partidário (QP)** = int(votos_da_unidade / QE).
   "Unidade" = partido isolado ou federação partidária (contam como um).

3. **Barreira nas vagas do QP** (art. 108 do CE, red. Lei 13.165/2015):
   Candidato só se elege se tiver ≥ 10% do QE em votos nominais.
   Se um partido tem 3 vagas mas só 2 candidatos passam do 10%, ganha 2 e
   a 3ª vaga volta ao pool de sobras.

4. **Sobras — Fase 1 (Regra 80/20)** (art. 109 §2º CE, red. Lei 14.211/2021):
   Só concorrem à distribuição de vagas remanescentes:
     - Partidos/federações com votos ≥ 80% do QE, E
     - Candidatos com votos ≥ 20% do QE.
   Distribuição por maiores médias (D'Hondt): média = votos / (vagas+1).

5. **Sobras — Fase 2 (Residual)** (STF ADI 7228/7263, 2024):
   Se sobrarem vagas após a Fase 1 (nenhum partido preenche 80/20), a
   distribuição continua por maiores médias entre TODOS os partidos com
   candidatos disponíveis, ignorando o corte de 80%. Sem essa fase, vagas
   podem ficar sem preenchimento — o STF derrubou essa possibilidade.

6. **Federações partidárias** (art. 11-A LO Partidos, red. Lei 14.208/2021):
   Federação de 2+ partidos age como um só partido pra todos os efeitos
   proporcionais: soma votos, compete a vagas em bloco, distribui
   internamente pelos candidatos mais votados. Os partidos membros
   preservam registro e estrutura próprios.

Nota sobre relatórios: `ResultadoPartido.votos_partido` traz os votos
específicos daquele partido (útil pra relatórios de desempenho por
legenda), enquanto `votos_unidade` traz o total da unidade (partido isolado
ou federação inteira), que é o que efetivamente entra no cálculo do QP.

Referências:
- Código Eleitoral (Lei 4.737/1965), arts. 106-113.
- Lei 14.211/2021 — regra 80/20.
- STF ADI 7228 e ADI 7263 (2024) — fase residual.
- Lei 14.208/2021 + EC 97/2017 — federações.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable


@dataclass(frozen=True)
class CandidatoProporcional:
    sq_candidato: str
    nome_urna: str
    numero: int
    partido_numero: int
    votos: int


@dataclass
class ResultadoCandidato:
    sq_candidato: str
    nome_urna: str
    partido: int
    votos: int
    status: str          # "eleito", "suplente", "nao_atingiu_barreira", "partido_sem_vaga"
    posicao_no_partido: int
    federacao: str | None = None


@dataclass
class ResultadoPartido:
    partido: int
    federacao: str | None
    votos_partido: int   # votos daquela legenda específica (nominais+legenda desse partido)
    votos_unidade: int   # votos da unidade (partido isolado ou federação inteira)
    vagas_qp: int        # vagas por quociente partidário
    vagas_sobras: int    # vagas ganhas nas sobras (Fase 1 + Fase 2)
    total_vagas: int
    passou_qe: bool
    passou_80_qe: bool   # elegível pra Fase 1 das sobras (Lei 14.211/2021)


@dataclass
class ResultadoProporcional:
    qe: int
    votos_validos: int
    vagas: int
    barreira_absoluta: int   # 10% do QE em votos
    candidatos: list[ResultadoCandidato]
    partidos: list[ResultadoPartido]


# Federações 2026 (padrão histórico 2022 — pode ajustar via arg)
FEDERACOES_2026_DEFAULT = {
    "F_BRASIL_ESPERANCA": {13, 65, 43},  # PT + PCdoB + PV
    "F_PSOL_REDE": {50, 18},              # PSOL + REDE
}


def _federacao_de(partido: int, federacoes: dict[str, set[int]]) -> str | None:
    for nome, membros in federacoes.items():
        if partido in membros:
            return nome
    return None


def calcular_eleitos_proporcional(
    candidatos: Iterable[CandidatoProporcional],
    vagas: int,
    votos_legenda_por_partido: dict[int, int] | None = None,
    federacoes: dict[str, set[int]] | None = None,
) -> ResultadoProporcional:
    """Calcula quem se elege num pleito proporcional.

    Args:
        candidatos: todos os candidatos daquele cargo/UF com seus votos nominais
        vagas: número de cadeiras em disputa
        votos_legenda_por_partido: opcional; votos de legenda (voto no número
            do partido só). Somam ao total do partido pro cálculo do QP.
        federacoes: mapa {nome: {numeros_partido}}; default = federações 2022

    Returns:
        ResultadoProporcional com QE, listas de candidatos (com status) e
        listas de partidos (com vagas ganhas).
    """
    cands = list(candidatos)
    if not cands or vagas <= 0:
        return ResultadoProporcional(0, 0, vagas, 0, [], [])

    federacoes = federacoes if federacoes is not None else FEDERACOES_2026_DEFAULT
    votos_legenda = votos_legenda_por_partido or {}

    # 1) Agrupa candidatos por "unidade eleitoral" (partido isolado OU federação)
    #    e também totaliza VOTOS POR PARTIDO individualmente (não misturados
    #    com a federação) — necessário pro ResultadoPartido correto.
    def unidade_de(part: int) -> str:
        fed = _federacao_de(part, federacoes)
        return fed if fed else f"P{part}"

    votos_por_partido: dict[int, int] = {}
    votos_por_unidade: dict[str, int] = {}
    for c in cands:
        votos_por_partido[c.partido_numero] = votos_por_partido.get(c.partido_numero, 0) + c.votos
        u = unidade_de(c.partido_numero)
        votos_por_unidade[u] = votos_por_unidade.get(u, 0) + c.votos
    for part, votos in votos_legenda.items():
        votos_por_partido[part] = votos_por_partido.get(part, 0) + votos
        u = unidade_de(part)
        votos_por_unidade[u] = votos_por_unidade.get(u, 0) + votos

    # 2) QE e barreiras
    votos_validos = sum(votos_por_unidade.values())
    qe = votos_validos // vagas if vagas > 0 else 0
    barreira_qp = qe // 10              # 10% do QE — barreira nas vagas diretas do QP
    barreira_sobra_cand = int(qe * 0.20)  # 20% do QE — barreira do candidato nas sobras
    corte_80_qe = int(qe * 0.80)          # 80% do QE — barreira da unidade nas sobras (Fase 1)

    vagas_por_unidade: dict[str, int] = {}
    for u, v in votos_por_unidade.items():
        vagas_por_unidade[u] = v // qe if qe > 0 else 0

    # Aliases pra compat com trechos abaixo
    barreira = barreira_qp

    # 3) Distribuição por unidade (candidatos ordenados internamente por votos,
    # respeitando a barreira). Se um partido levou 5 vagas mas só 3 candidatos
    # passam da barreira, ganha 3 — as outras 2 voltam pro pool de sobras.
    cands_por_unidade: dict[str, list[CandidatoProporcional]] = {}
    for c in cands:
        u = unidade_de(c.partido_numero)
        cands_por_unidade.setdefault(u, []).append(c)
    for u in cands_por_unidade:
        cands_por_unidade[u].sort(key=lambda c: c.votos, reverse=True)

    vagas_efetivas_por_unidade: dict[str, int] = {}
    for u, vagas_teoricas in vagas_por_unidade.items():
        candidatos_u = cands_por_unidade.get(u, [])
        passam_barreira = sum(1 for c in candidatos_u if c.votos >= barreira)
        vagas_efetivas_por_unidade[u] = min(vagas_teoricas, passam_barreira)

    vagas_usadas = sum(vagas_efetivas_por_unidade.values())
    vagas_sobras_por_unidade: dict[str, int] = {u: 0 for u in vagas_por_unidade}

    # 4) Sobras — Lei 14.211/2021 + STF ADI 7228/7263 (2024).
    vagas_restantes = vagas - vagas_usadas

    def media_dhondt(u: str) -> float:
        total_atual = vagas_efetivas_por_unidade[u] + vagas_sobras_por_unidade[u]
        return votos_por_unidade[u] / (total_atual + 1)

    # ---- Fase 1: Regra 80/20 ----
    # Só concorrem partidos/federações com votos ≥ 80% do QE, cujos
    # candidatos disponíveis tenham ≥ 20% do QE.
    while vagas_restantes > 0:
        elegiveis: list[str] = []
        for u, v_total in votos_por_unidade.items():
            if v_total < corte_80_qe:
                continue  # unidade não atingiu 80% do QE
            total_ja = vagas_efetivas_por_unidade[u] + vagas_sobras_por_unidade[u]
            candidatos_u = cands_por_unidade.get(u, [])
            # Precisa ter candidato ainda disponível E que passe da barreira 20% QE
            passam_20 = sum(1 for c in candidatos_u if c.votos >= barreira_sobra_cand)
            if passam_20 > total_ja:
                elegiveis.append(u)
        if not elegiveis:
            break  # ninguém preenche Fase 1 → cai pra Fase 2
        vencedor = max(elegiveis, key=media_dhondt)
        vagas_sobras_por_unidade[vencedor] += 1
        vagas_restantes -= 1

    # ---- Fase 2: Residual (STF ADI 7228/7263, 2024) ----
    # Se ainda sobram vagas, distribuir por maiores médias entre todos os
    # partidos com candidatos disponíveis, ignorando o corte de 80% e
    # aplicando só a barreira original de 10% do QE.
    while vagas_restantes > 0:
        elegiveis = []
        for u in votos_por_unidade:
            total_ja = vagas_efetivas_por_unidade[u] + vagas_sobras_por_unidade[u]
            candidatos_u = cands_por_unidade.get(u, [])
            passam_barreira = sum(1 for c in candidatos_u if c.votos >= barreira_qp)
            if passam_barreira > total_ja:
                elegiveis.append(u)
        if not elegiveis:
            break  # não há mais candidatos válidos
        vencedor = max(elegiveis, key=media_dhondt)
        vagas_sobras_por_unidade[vencedor] += 1
        vagas_restantes -= 1

    # 5) Monta o resultado — determina status de cada candidato
    resultado_cands: list[ResultadoCandidato] = []
    for u, candidatos_u in cands_por_unidade.items():
        total_vagas_u = vagas_efetivas_por_unidade[u] + vagas_sobras_por_unidade[u]
        eleitos_indices = set()
        # Pega os N mais votados que passam da barreira
        eleitos_count = 0
        for i, c in enumerate(candidatos_u):
            if eleitos_count >= total_vagas_u:
                break
            if c.votos >= barreira:
                eleitos_indices.add(i)
                eleitos_count += 1
        for i, c in enumerate(candidatos_u):
            if i in eleitos_indices:
                status = "eleito"
            elif c.votos < barreira:
                status = "nao_atingiu_barreira"
            elif vagas_por_unidade[u] == 0:
                status = "partido_sem_vaga"
            else:
                status = "suplente"
            fed = u if not u.startswith("P") else None
            resultado_cands.append(ResultadoCandidato(
                sq_candidato=c.sq_candidato,
                nome_urna=c.nome_urna,
                partido=c.partido_numero,
                votos=c.votos,
                status=status,
                posicao_no_partido=i + 1,
                federacao=fed,
            ))

    # Resultado por partido — mantém DUAS métricas separadas: os votos
    # específicos daquela legenda e os votos da unidade eleitoral
    # (partido isolado ou federação inteira). Antes tudo ficava misturado
    # no mesmo campo — QA apontou que distorcia relatórios individuais.
    resultado_partidos: list[ResultadoPartido] = []
    partidos_ja_registrados = set()
    for c in cands:
        p_num = c.partido_numero
        if p_num in partidos_ja_registrados:
            continue
        partidos_ja_registrados.add(p_num)
        u = unidade_de(p_num)
        v_partido = votos_por_partido.get(p_num, 0)
        v_unidade = votos_por_unidade.get(u, 0)
        resultado_partidos.append(ResultadoPartido(
            partido=p_num,
            federacao=u if not u.startswith("P") else None,
            votos_partido=v_partido,
            votos_unidade=v_unidade,
            vagas_qp=vagas_por_unidade.get(u, 0),
            vagas_sobras=vagas_sobras_por_unidade.get(u, 0),
            total_vagas=vagas_efetivas_por_unidade.get(u, 0) + vagas_sobras_por_unidade.get(u, 0),
            passou_qe=vagas_por_unidade.get(u, 0) >= 1,
            passou_80_qe=v_unidade >= corte_80_qe,
        ))

    return ResultadoProporcional(
        qe=qe,
        votos_validos=votos_validos,
        vagas=vagas,
        barreira_absoluta=barreira,
        candidatos=sorted(resultado_cands, key=lambda x: x.votos, reverse=True),
        partidos=resultado_partidos,
    )


# Número de vagas por UF (fonte: TSE / TCU / Res. TSE 23.660/2022)
VAGAS_DEP_FEDERAL = {
    "AC": 8, "AL": 9, "AM": 8, "AP": 8, "BA": 39, "CE": 22, "DF": 8,
    "ES": 10, "GO": 17, "MA": 18, "MG": 53, "MS": 8, "MT": 8, "PA": 17,
    "PB": 12, "PE": 25, "PI": 10, "PR": 30, "RJ": 46, "RN": 8, "RO": 8,
    "RR": 8, "RS": 31, "SC": 16, "SE": 8, "SP": 70, "TO": 8,
}


def vagas_dep_estadual(uf: str) -> int:
    """Deputado Estadual/Distrital: fórmula do art. 4º do ADCT.
    df <= 12: est = 3 × df
    df >  12: est = 36 + (df − 12)
    """
    df = VAGAS_DEP_FEDERAL.get(uf.upper(), 0)
    return (3 * df) if df <= 12 else (36 + (df - 12))
