"""Cálculo de eleitos em pleitos proporcionais (Deputado Federal/Estadual).

Regras (Lei 4.737/1965, alterada pela 13.165/2015 e EC 97/2017):

1. **Quociente Eleitoral (QE)** = int(votos_validos / vagas).
   Votos válidos incluem votos nominais + votos de legenda.

2. **Quociente Partidário (QP)** de cada partido/federação = int(votos_do_partido / QE).
   É quantas vagas iniciais o partido leva.

3. **Cláusula de barreira** (art. 108 do CE após 2015):
   Candidato só se elege se tiver ≥ 10% do QE em votos nominais.
   Se um partido tem 3 vagas mas só 2 candidatos passam do 10%, ganha só 2.
   A terceira vaga volta ao pool de sobras.

4. **Sobras** — distribuídas por D'Hondt (maior média):
   Média = votos_partido / (vagas_atual + 1).
   Só concorre a sobras o partido que atingiu o QE original.
   Vaga vai pro candidato mais votado do partido que ainda esteja
   acima da cláusula de barreira.

5. **Federações** (EC 97/2017 + lei 14.208/2021):
   Federação de 3+ partidos age como um só partido — soma votos,
   compete a vagas em bloco, distribui internamente entre os partidos
   membros pela ordem dos mais votados.

Referências:
- CE arts. 106-113 (proporcional)
- CE art. 108 (barreira 10% QE)
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
    votos_totais: int
    vagas_qp: int        # vagas por quociente partidário
    vagas_sobras: int    # vagas ganhas nas sobras
    total_vagas: int
    passou_qe: bool


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
    def unidade_de(part: int) -> str:
        fed = _federacao_de(part, federacoes)
        return fed if fed else f"P{part}"

    votos_por_unidade: dict[str, int] = {}
    for c in cands:
        u = unidade_de(c.partido_numero)
        votos_por_unidade[u] = votos_por_unidade.get(u, 0) + c.votos
    for part, votos in votos_legenda.items():
        u = unidade_de(part)
        votos_por_unidade[u] = votos_por_unidade.get(u, 0) + votos

    # 2) QE e QP
    votos_validos = sum(votos_por_unidade.values())
    qe = votos_validos // vagas if vagas > 0 else 0
    barreira = qe // 10  # 10% do QE

    vagas_por_unidade: dict[str, int] = {}
    for u, v in votos_por_unidade.items():
        vagas_por_unidade[u] = v // qe if qe > 0 else 0

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

    # 4) Sobras — método D'Hondt (maior média). Só concorrem quem atingiu QE.
    concorrentes_sobras = [u for u, v in vagas_por_unidade.items() if v >= 1]
    vagas_restantes = vagas - vagas_usadas
    while vagas_restantes > 0 and concorrentes_sobras:
        # Média = votos / (vagas_efetivas + sobras_ja_dadas + 1)
        def media(u):
            total_atual = vagas_efetivas_por_unidade[u] + vagas_sobras_por_unidade[u]
            return votos_por_unidade[u] / (total_atual + 1)

        # Filtra os que ainda têm candidatos disponíveis passando na barreira
        elegiveis = []
        for u in concorrentes_sobras:
            total_ja = vagas_efetivas_por_unidade[u] + vagas_sobras_por_unidade[u]
            candidatos_u = cands_por_unidade.get(u, [])
            passam_barreira = sum(1 for c in candidatos_u if c.votos >= barreira)
            if passam_barreira > total_ja:
                elegiveis.append(u)
        if not elegiveis:
            break

        vencedor = max(elegiveis, key=media)
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

    resultado_partidos: list[ResultadoPartido] = []
    partidos_ja_registrados = set()
    for c in cands:
        u = unidade_de(c.partido_numero)
        chave = (c.partido_numero, u)
        if chave in partidos_ja_registrados:
            continue
        partidos_ja_registrados.add(chave)
        # Nota: se for federação, mostramos as vagas totais da federação
        # (nem sempre é a mesma pra cada partido membro)
        resultado_partidos.append(ResultadoPartido(
            partido=c.partido_numero,
            federacao=u if not u.startswith("P") else None,
            votos_totais=votos_por_unidade.get(u, 0),
            vagas_qp=vagas_por_unidade.get(u, 0),
            vagas_sobras=vagas_sobras_por_unidade.get(u, 0),
            total_vagas=vagas_efetivas_por_unidade.get(u, 0) + vagas_sobras_por_unidade.get(u, 0),
            passou_qe=vagas_por_unidade.get(u, 0) >= 1,
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
