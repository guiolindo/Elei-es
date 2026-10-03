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

5. **Sobras — Fase 2 (Residual)** (art. 109, III CE + STF ADI 7228/7263, 2024):
   Se sobrarem vagas após a Fase 1 (nenhum partido preenche 80/20), a
   distribuição continua por maiores médias (D'Hondt) entre TODOS os
   partidos com candidatos disponíveis, sem exigir 80% da unidade e
   sem exigir mínimo do candidato (STF dispensou expressamente ambas
   barreiras nessa fase residual). Isso pode fazer com que um candidato
   com menos de 10% do QE se eleja, o que é intencional segundo a
   decisão — o próprio Alexandre de Moraes apontou que a regra anterior
   deixava vagas com bons candidatos vazias.

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
    # Situação do candidato pela Justiça Eleitoral. Pela Lei 9.504/97 art.
    # 175 §3º, votos em candidato que não seja 'ativo' são nulos — não
    # devem contar nem pro candidato nem pro partido/federação. O motor
    # exclui qualquer status != 'ativo' antes do cálculo do QE, QP,
    # barreira e sobras.
    situacao: str = "ativo"
    # Idade em anos completos no dia da eleição. Usado SÓ pra desempate
    # entre dois candidatos do MESMO partido com votação idêntica, por
    # art. 110 CE: "em caso de empate, haver-se-á por eleito o mais idoso".
    # Se None, o motor mantém a ordem recebida (não decide).
    idade_anos: int | None = None


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


# Federações partidárias registradas no TSE pra as Eleições 2026.
# Verificadas contra fontes primárias (Portal TSE + Agência Brasil + CNN)
# em 2026-09-29. Cinco federações constam do calendário:
#   1. Brasil da Esperança:  PT (13) + PCdoB (65) + PV (43)
#      (herdada de 2022, mantida)
#   2. PSDB Cidadania:       PSDB (45) + Cidadania (23)
#      (herdada de 2022, mantida)
#   3. PSOL Rede:            PSOL (50) + REDE (18)
#      (herdada de 2022, mantida)
#   4. União Progressista:   União Brasil (44) + Progressistas/PP (11)
#      (nova em 2026; TSE aprovou 26/03/2026 — maior bloco da Câmara)
#   5. Renovação Solidária:  Solidariedade (77) + PRD (25)
#      (nova em 2026; TSE aprovou em dez/2025)
#
# Fontes:
# - https://www.tse.jus.br/partidos/federacoes-registradas-no-tse
# - https://www.tse.jus.br/partidos/federacoes-registradas-no-tse/uniao-progressista
# - https://www.tse.jus.br/partidos/federacoes-registradas-no-tse/renovacao-solidaria
FEDERACOES_2026_DEFAULT = {
    "F_BRASIL_ESPERANCA":  {13, 65, 43},  # PT + PCdoB + PV
    "F_PSDB_CIDADANIA":    {45, 23},       # PSDB + Cidadania
    "F_PSOL_REDE":         {50, 18},       # PSOL + REDE
    "F_UNIAO_PROGRESSISTA": {44, 11},      # União Brasil + Progressistas (2026)
    "F_RENOVACAO_SOLIDARIA": {77, 25},     # Solidariedade + PRD (2026)
}


class _MediaKey:
    """Chave de comparação pra max()/sort de médias D'Hondt sem float.

    Compara `num_a/den_a` vs `num_b/den_b` por produto cruzado
    (`num_a * den_b` vs `num_b * den_a`) — resultado exato em inteiros.
    Em empate exato de média, desempata pela maior votação da unidade
    (Res. TSE 23.677/2021, art. 108 §3º).
    """
    __slots__ = ("num", "den", "votos_unidade")

    def __init__(self, num: int, den: int, votos_unidade: int):
        self.num = num
        self.den = den
        self.votos_unidade = votos_unidade

    def __lt__(self, other: "_MediaKey") -> bool:
        a = self.num * other.den
        b = other.num * self.den
        if a != b:
            return a < b
        # Empate de média → maior votação ganha (desempate legal)
        return self.votos_unidade < other.votos_unidade

    def __eq__(self, other: "_MediaKey") -> bool:
        return (self.num * other.den == other.num * self.den
                and self.votos_unidade == other.votos_unidade)


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
    # EXCLUSÃO LEGAL: candidatos com situação não-ativa (renunciou,
    # cancelado, cassado, indeferido_sem_recurso) têm votos considerados
    # nulos pela Lei 9.504/97 art. 175 §3º. Removê-los AQUI significa que
    # seus votos não entram nem no QE, nem no QP da legenda, nem na
    # barreira, nem no D'Hondt — exatamente como manda a lei. Importante:
    # isso pode fazer o partido/federação perder vagas pra outro, porque
    # votos nulos nunca "puxam" chapa.
    cands = [c for c in cands if c.situacao == "ativo"]
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
    # Regulação TSE: fração igual ou inferior a 0,5 é desprezada;
    # somente fração estritamente superior a 0,5 arredonda para cima.
    # Res. TSE 23.677/2021, art. 100 (consolidado p/ 2026 na Res. 23.748/2026).
    # Implementação sem ponto flutuante — compara `2*r > vagas` que é
    # exatamente "r/vagas > 0.5" sem imprecisão binária.
    votos_validos = sum(votos_por_unidade.values())
    if vagas > 0:
        q, r = divmod(votos_validos, vagas)
        qe = q + (1 if 2 * r > vagas else 0)
    else:
        qe = 0
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
        # Ordena por votos desc; empate → mais velho primeiro (art. 110 CE).
        # Candidato sem idade cai pro fim do empate (idade = -1 vira menor).
        cands_por_unidade[u].sort(
            key=lambda c: (c.votos, c.idade_anos if c.idade_anos is not None else -1),
            reverse=True,
        )

    vagas_efetivas_por_unidade: dict[str, int] = {}
    for u, vagas_teoricas in vagas_por_unidade.items():
        candidatos_u = cands_por_unidade.get(u, [])
        passam_barreira = sum(1 for c in candidatos_u if c.votos >= barreira)
        vagas_efetivas_por_unidade[u] = min(vagas_teoricas, passam_barreira)

    vagas_usadas = sum(vagas_efetivas_por_unidade.values())
    # Rastreamos SEPARADAMENTE as vagas ganhas em cada fase das sobras.
    # A Fase 2 (80/20) exige barreira do candidato de 20% QE.
    # A Fase 3 (residual, STF) NÃO exige barreira do candidato.
    vagas_sobra_8020_por_unidade: dict[str, int] = {u: 0 for u in vagas_por_unidade}
    vagas_sobra_residual_por_unidade: dict[str, int] = {u: 0 for u in vagas_por_unidade}

    # 4) Sobras — Lei 14.211/2021 + STF ADI 7228/7263 (2024).
    vagas_restantes = vagas - vagas_usadas

    def total_sobras(u: str) -> int:
        return vagas_sobra_8020_por_unidade[u] + vagas_sobra_residual_por_unidade[u]

    def media_dhondt_tupla(u: str) -> tuple[int, int]:
        """Média como par (numerador, denominador) pra comparação exata
        por produto cruzado em vez de float. Evita arredondamento binário
        que pode criar empate artificial ou inverter resultado em
        votações grandes com médias próximas.
        """
        total_atual = vagas_efetivas_por_unidade[u] + total_sobras(u)
        return (votos_por_unidade[u], total_atual + 1)

    def media_cmp_key(u: str):
        """Chave de ordenação determinística:
          1. Maior média (produto cruzado em inteiros)
          2. Em caso de empate exato, maior votação da unidade (desempate
             legal — Res. 23.677 art. 108 §3º).
        Python ordena tuplas lexicograficamente; invertemos sinal pra
        max() natural.
        """
        num, den = media_dhondt_tupla(u)
        # Pra max(): queremos maior média, maior votação.
        # Como média é num/den, não dá pra usar sinal direto como int.
        # Retorna um objeto que sabe comparar por produto cruzado:
        return _MediaKey(num, den, votos_por_unidade[u])

    # ---- Fase 2 das sobras: Regra 80/20 (Lei 14.211/2021, art. 109 II) ----
    # Só concorrem partidos/federações com ≥ 80% do QE, cujos candidatos
    # ainda disponíveis tenham ≥ 20% do QE.
    while vagas_restantes > 0:
        elegiveis: list[str] = []
        for u, v_total in votos_por_unidade.items():
            if v_total < corte_80_qe:
                continue
            total_ja = vagas_efetivas_por_unidade[u] + total_sobras(u)
            candidatos_u = cands_por_unidade.get(u, [])
            passam_20 = sum(1 for c in candidatos_u if c.votos >= barreira_sobra_cand)
            if passam_20 > total_ja:
                elegiveis.append(u)
        if not elegiveis:
            break
        vencedor = max(elegiveis, key=media_cmp_key)
        vagas_sobra_8020_por_unidade[vencedor] += 1
        vagas_restantes -= 1

    # ---- Fase 3 das sobras: Residual (art. 109 III + STF ADI 7228/7263) ----
    # Todos os partidos participam, sem 80% da unidade e SEM barreira do
    # candidato. Um candidato com <10% do QE pode se eleger aqui — é
    # intencional segundo a decisão do STF.
    while vagas_restantes > 0:
        elegiveis = []
        for u in votos_por_unidade:
            total_ja = vagas_efetivas_por_unidade[u] + total_sobras(u)
            candidatos_u = cands_por_unidade.get(u, [])
            if len(candidatos_u) > total_ja:
                elegiveis.append(u)
        if not elegiveis:
            break
        vencedor = max(elegiveis, key=media_cmp_key)
        vagas_sobra_residual_por_unidade[vencedor] += 1
        vagas_restantes -= 1

    # Alias legado (soma das duas fases das sobras)
    vagas_sobras_por_unidade = {u: total_sobras(u) for u in vagas_por_unidade}

    # 5) Preenche as vagas de cada unidade em duas passadas:
    #    - Vagas com barreira (QP + Fase 2 das sobras 80/20): só candidatos
    #      que passam 10% do QE, em ordem de votação.
    #    - Vagas residuais (Fase 3 STF): próximos mais votados sem exigência.
    resultado_cands: list[ResultadoCandidato] = []
    for u, candidatos_u in cands_por_unidade.items():
        vagas_com_barreira = vagas_efetivas_por_unidade[u] + vagas_sobra_8020_por_unidade[u]
        vagas_residuais = vagas_sobra_residual_por_unidade[u]
        eleitos_indices: set[int] = set()

        # Passada 1: preenche vagas com barreira (>= 10% QE) por candidatos
        # que atendem, em ordem de votação
        eleitos_count = 0
        for i, c in enumerate(candidatos_u):
            if eleitos_count >= vagas_com_barreira:
                break
            if c.votos >= barreira_qp:
                eleitos_indices.add(i)
                eleitos_count += 1

        # Passada 2: preenche vagas residuais pelos próximos candidatos
        # mais votados que ainda não foram eleitos (STF: sem barreira)
        for i, c in enumerate(candidatos_u):
            if vagas_residuais <= 0:
                break
            if i not in eleitos_indices:
                eleitos_indices.add(i)
                vagas_residuais -= 1

        for i, c in enumerate(candidatos_u):
            if i in eleitos_indices:
                status = "eleito"
            elif c.votos < barreira_qp:
                status = "nao_atingiu_barreira"
            elif vagas_por_unidade[u] == 0 and vagas_sobras_por_unidade[u] == 0:
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
