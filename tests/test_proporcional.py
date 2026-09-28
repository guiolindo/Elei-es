from math_engine.proporcional import (
    CandidatoProporcional, calcular_eleitos_proporcional,
    vagas_dep_estadual, VAGAS_DEP_FEDERAL,
)


def c(sq, nome, num, partido, votos):
    return CandidatoProporcional(sq, nome, num, partido, votos)


def test_qe_e_qp_basico():
    # Cenário simples: 3 vagas, 2 partidos
    cands = [
        c("1", "A", 1300, 13, 400),  # PT
        c("2", "B", 1301, 13, 200),  # PT
        c("3", "C", 2200, 22, 300),  # PL
        c("4", "D", 2201, 22, 100),  # PL
    ]
    # Sem federação, sem legenda. votos_validos=1000, QE=333
    r = calcular_eleitos_proporcional(cands, vagas=3, federacoes={})
    assert r.qe == 333
    assert r.votos_validos == 1000
    # PT: 600 votos → QP = 600/333 = 1 vaga
    # PL: 400 votos → QP = 400/333 = 1 vaga
    # Sobra 1 vaga → maior média: PT tem 600/(1+1)=300, PL tem 400/(1+1)=200 → PT
    votos_por_p = {p.partido: p.total_vagas for p in r.partidos}
    assert votos_por_p[13] == 2
    assert votos_por_p[22] == 1


def test_barreira_10pct_qe():
    # Candidato com poucos votos não elege mesmo se partido tem vaga
    cands = [
        c("1", "A", 1300, 13, 5000),   # passa
        c("2", "B", 1301, 13, 50),     # abaixo dos 10% do QE
        c("3", "C", 2200, 22, 4000),
    ]
    r = calcular_eleitos_proporcional(cands, vagas=2, federacoes={})
    # QE = 9050 / 2 = 4525; barreira = 452
    # PT: 5050 votos → QP = 1
    # PL: 4000 → QP = 0
    # Sobra 1 vaga → PT (única unidade com QE)
    # Mas o segundo candidato do PT (50 votos) < barreira 452 → não elege
    # A vaga sobra volta pro pool mas ninguém mais tem candidato passando
    status = {rc.sq_candidato: rc.status for rc in r.candidatos}
    assert status["1"] == "eleito"
    assert status["2"] == "nao_atingiu_barreira"
    assert status["3"] in {"partido_sem_vaga", "suplente"}


def test_federacao_soma_votos():
    # PT (13) + PC do B (65) formam Federação — competem juntos
    cands = [
        c("1", "L", 1300, 13, 400),
        c("2", "M", 6500, 65, 300),
        c("3", "N", 2200, 22, 350),
    ]
    r = calcular_eleitos_proporcional(cands, vagas=2)
    # Federação Brasil Esperança tem PT + PCdoB = 700 votos
    # PL: 350
    # QE = 1050/2 = 525
    # Fed: 700/525 = 1 vaga, PL: 350/525 = 0
    # Sobra 1 → maior média: Fed 700/(1+1)=350, PL 350/(0+1)=350. Empate — implementação prefere Fed pela ordem
    # No mínimo Fed deve ter 1 vaga
    eleitos = [rc for rc in r.candidatos if rc.status == "eleito"]
    assert len(eleitos) >= 1
    # O candidato mais votado da Fed é o Lula (400) — deve ser eleito
    assert eleitos[0].sq_candidato == "1"


def test_vagas_estaduais_por_uf():
    # SP tem 70 federal → 36 + 58 = 94 estadual
    assert vagas_dep_estadual("SP") == 94
    # MG tem 53 → 36 + 41 = 77
    assert vagas_dep_estadual("MG") == 77
    # AC tem 8 → 3×8 = 24
    assert vagas_dep_estadual("AC") == 24


def test_vagas_dep_federal_soma_513():
    # Total nacional deve ser 513
    assert sum(VAGAS_DEP_FEDERAL.values()) == 513


def test_sem_votos_retorna_vazio():
    r = calcular_eleitos_proporcional([], vagas=10, federacoes={})
    assert r.qe == 0
    assert r.candidatos == []


def test_dhondt_sobras_multi_partidos():
    # 3 partidos, 5 vagas. Testa que sobras usam D'Hondt corretamente
    cands = [
        c("A", "A1", 1300, 13, 900), c("B", "A2", 1301, 13, 500),
        c("C", "B1", 2200, 22, 700), c("D", "B2", 2201, 22, 300),
        c("E", "C1", 4500, 45, 500), c("F", "C2", 4501, 45, 100),
    ]
    r = calcular_eleitos_proporcional(cands, vagas=5, federacoes={})
    # votos_validos = 3000, QE = 600
    # PT: 1400/600 = 2 (400 sobra), PL: 1000/600 = 1 (400 sobra), PSDB: 600/600 = 1 (0 sobra)
    # Total QP = 4, sobra 1 vaga
    # Médias: PT 1400/3=467, PL 1000/2=500, PSDB 600/2=300 → PL leva
    votos_por_p = {p.partido: p.total_vagas for p in r.partidos}
    assert votos_por_p[13] == 2  # PT: 2 do QP
    assert votos_por_p[22] == 2  # PL: 1 QP + 1 sobra
    assert votos_por_p[45] == 1  # PSDB: 1 QP
