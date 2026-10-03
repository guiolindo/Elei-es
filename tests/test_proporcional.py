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


def test_barreira_10pct_qe_com_fase_1_80_20():
    """Barreira do QP (10% QE) + Regra 80/20 na sobra (Lei 14.211/2021).

    Cenário: QE=4525, barreira QP=452, corte 80% QE=3620, barreira sobra
    candidato=905 (20% QE).
    - PT ('1', '2'): 5050 votos totais. QP=1 → cand.1 (5000v) eleito;
      cand.2 tem 50v < 452 (não passa barreira) e < 905 (não elege na sobra).
    - PL ('3'): 4000 votos, sem QP direto (4000 < 4525) mas 4000 >= 3620
      (passa 80% do QE) e o candidato tem 4000 >= 905 (passa 20% QE).
      Elegível na Fase 1 das sobras → leva a vaga sobrante.
    Antes da Lei 14.211/2021 esse candidato não elegia — regra atual sim."""
    cands = [
        c("1", "A", 1300, 13, 5000),
        c("2", "B", 1301, 13, 50),     # < 10% QE
        c("3", "C", 2200, 22, 4000),   # sem QP direto, mas passa 80/20
    ]
    r = calcular_eleitos_proporcional(cands, vagas=2, federacoes={})
    status = {rc.sq_candidato: rc.status for rc in r.candidatos}
    assert status["1"] == "eleito"
    assert status["2"] == "nao_atingiu_barreira"
    assert status["3"] == "eleito"  # Fase 1 da sobra (Lei 14.211/2021)


def test_fase_2_residual_stf_2024():
    """Fase 2 residual (STF ADI 7228/7263, 2024): quando ninguém preenche
    80/20, vagas restantes vão pra maiores médias entre todos.

    Aqui todos ficam abaixo de 80% do QE, mas há candidatos válidos:
    2 vagas, 4 candidatos de 3 partidos, votos baixos e distribuídos."""
    cands = [
        c("1", "A", 1300, 13, 500),
        c("2", "B", 1301, 13, 100),
        c("3", "C", 2200, 22, 400),
        c("4", "D", 4500, 45, 300),
    ]
    r = calcular_eleitos_proporcional(cands, vagas=2, federacoes={})
    # votos_validos=1300, QE=650, corte 80%=520, barreira 10%=65, sobra=130.
    # Ninguém tem QP (todos <650). Ninguém tem votos >= 520 (80% QE) →
    # Fase 1 vazia. Fase 2 distribui: maiores médias entre unidades com
    # candidatos válidos (>= 65v).
    # PT: 600/1=600, PL: 400/1=400, PSDB: 300/1=300. PT leva 1ª → PT: 600/2=300.
    # Depois: PL 400 > PT 300 e PSDB 300 → PL leva 2ª.
    status = {rc.sq_candidato: rc.status for rc in r.candidatos}
    # PT candidato 1 (mais votado do PT) e PL candidato 3 eleitos
    assert status["1"] == "eleito"
    assert status["3"] == "eleito"


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


# ============ Testes de arredondamento do QE (TSE Res. 23.677 art. 100) ============
# Regra: fração <= 0.5 descarta; fração > 0.5 arredonda pra cima.

def test_qe_frac_exatamente_meio_descarta():
    """1000/16 = 62.5 → fração 0.5 descarta → QE = 62."""
    cands = [CandidatoProporcional(sq_candidato='X', nome_urna='X', numero=131,
                                    partido_numero=13, votos=1000)]
    r = calcular_eleitos_proporcional(cands, vagas=16)
    assert r.qe == 62


def test_qe_frac_acima_de_meio_arredonda():
    """1001/16 = 62.5625 → fração > 0.5 arredonda → QE = 63."""
    cands = [CandidatoProporcional(sq_candidato='X', nome_urna='X', numero=131,
                                    partido_numero=13, votos=1001)]
    r = calcular_eleitos_proporcional(cands, vagas=16)
    assert r.qe == 63


def test_qe_frac_abaixo_de_meio_descarta():
    """999/16 = 62.4375 → fração < 0.5 descarta → QE = 62."""
    cands = [CandidatoProporcional(sq_candidato='X', nome_urna='X', numero=131,
                                    partido_numero=13, votos=999)]
    r = calcular_eleitos_proporcional(cands, vagas=16)
    assert r.qe == 62


def test_qe_exato_sem_fracao():
    """960/16 = 60 exato → QE = 60."""
    cands = [CandidatoProporcional(sq_candidato='X', nome_urna='X', numero=131,
                                    partido_numero=13, votos=960)]
    r = calcular_eleitos_proporcional(cands, vagas=16)
    assert r.qe == 60


# ============ Filtragem por situacao (Lei 9.504/97 art. 175 §3º) ============

def test_cassado_nao_puxa_vagas_pro_partido():
    """Candidato não-ativo tem votos descontados: partido pode perder vaga.
    Caso real: um deputado 'puxador de votos' é cassado → suas vagas de
    sobras devem ir pra OUTRO partido, não ao mesmo partido dele.
    """
    from math_engine.proporcional import (
        CandidatoProporcional, calcular_eleitos_proporcional
    )
    # Partido A: 1 candidato gigante (cassado) + 1 pequeno. Sem o cassado,
    # o partido A fica com votos muito menores que B.
    cands = [
        CandidatoProporcional("A1", "GIGANTE", 1111, 11, votos=100000, situacao="cassado"),
        CandidatoProporcional("A2", "PEQUENO", 1112, 11, votos=5000,  situacao="ativo"),
        CandidatoProporcional("B1", "FORTE",   2211, 22, votos=40000, situacao="ativo"),
        CandidatoProporcional("B2", "MEDIO",   2212, 22, votos=30000, situacao="ativo"),
    ]
    r = calcular_eleitos_proporcional(cands, vagas=2, federacoes={})
    # Votos válidos considerados: 5k + 40k + 30k = 75k (gigante não conta)
    assert r.votos_validos == 75_000
    eleitos = [c.sq_candidato for c in r.candidatos if c.status == "eleito"]
    # Partido B deve levar as 2 vagas; partido A fica sem (só 5k vs 70k do B)
    assert "A1" not in eleitos  # cassado nunca entra
    assert set(eleitos) == {"B1", "B2"}


def test_candidato_renunciado_removido_do_calculo():
    from math_engine.proporcional import (
        CandidatoProporcional, calcular_eleitos_proporcional
    )
    cands = [
        CandidatoProporcional("X", "RENUNCIOU", 1111, 11, votos=99999,
                              situacao="renunciou"),
        CandidatoProporcional("Y", "ATIVO",     1112, 11, votos=100,
                              situacao="ativo"),
    ]
    r = calcular_eleitos_proporcional(cands, vagas=1, federacoes={})
    assert r.votos_validos == 100  # só o ativo
    assert all(c.sq_candidato != "X" for c in r.candidatos)


def test_todos_cassados_resultado_vazio():
    from math_engine.proporcional import (
        CandidatoProporcional, calcular_eleitos_proporcional
    )
    cands = [
        CandidatoProporcional("X", "A", 1111, 11, votos=100, situacao="cassado"),
        CandidatoProporcional("Y", "B", 2222, 22, votos=100, situacao="renunciou"),
    ]
    r = calcular_eleitos_proporcional(cands, vagas=5, federacoes={})
    assert r.candidatos == []
    assert r.votos_validos == 0
