from math_engine import (
    CandidatoResumo,
    TotaisResumo,
    votos_restantes_max,
    eleito_1t_presidencial,
    segundo_turno_definido,
    eleito_majoritario,
    avaliar_apuracao,
)


def totais(sec_tot, sec_tz, apto, apto_tz, validos):
    return TotaisResumo(
        qt_secoes_total=sec_tot,
        qt_secoes_totalizadas=sec_tz,
        qt_eleitorado_apto=apto,
        qt_eleitorado_apto_totalizadas=apto_tz,
        qt_votos_validos=validos,
    )


def test_votos_restantes_max_basico():
    t = totais(100, 50, 1000, 500, 400)
    assert votos_restantes_max(t) == 500


def test_votos_restantes_max_bug_tse_negativo_clampeado():
    t = totais(100, 100, 1000, 1100, 900)
    assert votos_restantes_max(t) == 0


def test_apuracao_zerada_nao_dispara_nada():
    t = totais(100, 0, 1000, 0, 0)
    cands = [CandidatoResumo("a", 0), CandidatoResumo("b", 0)]
    assert avaliar_apuracao(cands, t, cod_cargo=1) == []


def test_apuracao_abaixo_minimo_silenciada():
    # 10% apurado — não roda
    t = totais(100, 10, 1000, 100, 100)
    cands = [CandidatoResumo("a", 100), CandidatoResumo("b", 0)]
    assert avaliar_apuracao(cands, t, cod_cargo=3) == []


def test_eleito_1t_presidencial_confirmado():
    # 80% apurado, líder tem 60% dos válidos, restantes muito pequenos
    t = totais(100, 80, 1000, 800, 800)
    cands = [
        CandidatoResumo("a", 600),
        CandidatoResumo("b", 150),
        CandidatoResumo("c", 50),
    ]
    # pior cenário: 200 restantes vão pro adversário → 800+200=1000 válidos
    # líder tem 600. 600*2=1200 > 1000 → eleito
    assert eleito_1t_presidencial(cands, t) is True


def test_eleito_1t_presidencial_empate_no_fio():
    # líder tem exatamente metade dos válidos possíveis — empate ainda viável
    t = totais(100, 90, 1000, 900, 900)
    cands = [
        CandidatoResumo("a", 500),
        CandidatoResumo("b", 400),
    ]
    # 100 restantes → válidos_max=1000, metade=500. 500 > 500 é falso → não eleito
    assert eleito_1t_presidencial(cands, t) is False


def test_segundo_turno_definido():
    t = totais(100, 90, 1000, 900, 900)
    cands = [
        CandidatoResumo("a", 400),
        CandidatoResumo("b", 300),
        CandidatoResumo("c", 100),
    ]
    # 100 restantes. c+restantes=200 < b=300 → 2t definido
    assert segundo_turno_definido(cands, t) is True


def test_segundo_turno_nao_definido_no_fio():
    t = totais(100, 90, 1000, 900, 900)
    cands = [
        CandidatoResumo("a", 400),
        CandidatoResumo("b", 300),
        CandidatoResumo("c", 200),
    ]
    # 100 restantes. c+restantes=300 == b=300 → empate técnico → NÃO definido
    assert segundo_turno_definido(cands, t) is False


def test_eleito_majoritario_governador():
    t = totais(100, 85, 1000, 850, 850)
    cands = [
        CandidatoResumo("a", 600),
        CandidatoResumo("b", 200),
    ]
    # 150 restantes. b+restantes=350 < a=600 → eleito
    assert eleito_majoritario(cands, t) is True


def test_eleito_majoritario_no_fio_nao_eleito():
    t = totais(100, 85, 1000, 850, 850)
    cands = [
        CandidatoResumo("a", 600),
        CandidatoResumo("b", 450),
    ]
    # 150 restantes. b+restantes=600 == a → empate técnico → não eleito
    assert eleito_majoritario(cands, t) is False


def test_avaliar_apuracao_gera_evento_eleito_1t():
    t = totais(100, 80, 1000, 800, 800)
    cands = [
        CandidatoResumo("a", 600),
        CandidatoResumo("b", 150),
        CandidatoResumo("c", 50),
    ]
    ev = avaliar_apuracao(cands, t, cod_cargo=1)
    assert len(ev) == 1
    assert ev[0]["tipo"] == "ELEITO_1T"
    assert ev[0]["sq_candidato_a"] == "a"


def test_avaliar_apuracao_governador():
    t = totais(100, 85, 1000, 850, 850)
    cands = [
        CandidatoResumo("a", 600),
        CandidatoResumo("b", 200),
    ]
    ev = avaliar_apuracao(cands, t, cod_cargo=3)
    assert len(ev) == 1
    assert ev[0]["tipo"] == "ELEITO_MAJORITARIO"


def test_avaliar_apuracao_segundo_turno():
    t = totais(100, 90, 1000, 900, 900)
    cands = [
        CandidatoResumo("a", 400),
        CandidatoResumo("b", 300),
        CandidatoResumo("c", 100),
    ]
    ev = avaliar_apuracao(cands, t, cod_cargo=1)
    assert len(ev) == 1
    assert ev[0]["tipo"] == "SEGUNDO_TURNO_DEFINIDO"
    assert ev[0]["sq_candidato_a"] == "a"
    assert ev[0]["sq_candidato_b"] == "b"


def test_matematicamente_eliminado_top2():
    # 80% apurado, restantes = 200 (apto=1000, apto_tz=800)
    # Presidencial: precisa top 2. Alvo = 2º colocado B (400).
    # D tem 30 + 200 = 230 < 400 → eliminado
    # C tem 250 + 200 = 450 > 400 → ainda tem chance
    t = totais(100, 80, 1000, 800, 800)
    cands = [
        CandidatoResumo("A", 500),
        CandidatoResumo("B", 400),
        CandidatoResumo("C", 250),
        CandidatoResumo("D", 30),
    ]
    from math_engine.engine import matematicamente_eliminado
    assert matematicamente_eliminado(cands[3], cands, t, 2) is True
    assert matematicamente_eliminado(cands[2], cands, t, 2) is False


def test_matematicamente_eliminado_lider_nunca_eliminado():
    t = totais(100, 90, 1000, 900, 900)
    cands = [CandidatoResumo("A", 500), CandidatoResumo("B", 300)]
    from math_engine.engine import matematicamente_eliminado
    assert matematicamente_eliminado(cands[0], cands, t, 1) is False


def test_virada_iminente_quando_diff_menor_que_restantes():
    from math_engine.engine import virada_iminente
    # Diff 100 vs 1000 restantes → razão 0.1 → iminente com limite 15%
    t = totais(100, 50, 2000, 1000, 900)
    cands = [CandidatoResumo("A", 500), CandidatoResumo("B", 400)]
    iminente, razao = virada_iminente(cands, t, limite_pct=0.15)
    assert iminente is True
    assert abs(razao - 0.1) < 0.01


def test_virada_nao_iminente_quando_lider_folgado():
    from math_engine.engine import virada_iminente
    # Diff 500 vs 100 restantes → líder folgado
    t = totais(100, 95, 1000, 900, 900)
    cands = [CandidatoResumo("A", 700), CandidatoResumo("B", 200)]
    iminente, razao = virada_iminente(cands, t, limite_pct=0.5)
    assert iminente is False
    assert razao > 0.5


def test_margem_de_seguranca_folgada():
    from math_engine.engine import margem_de_seguranca
    # A 700, B 200, restantes 100 → margem ≈ (700 - 300) / 700 * 100 ≈ 57%
    t = totais(100, 90, 1000, 900, 900)
    cands = [CandidatoResumo("A", 700), CandidatoResumo("B", 200)]
    m = margem_de_seguranca(cands, t)
    assert 50 < m < 65


def test_margem_de_seguranca_no_fio():
    from math_engine.engine import margem_de_seguranca
    # A 500, B 400, restantes 100 → margem = 0 (empate técnico)
    t = totais(100, 90, 1000, 900, 900)
    cands = [CandidatoResumo("A", 500), CandidatoResumo("B", 400)]
    m = margem_de_seguranca(cands, t)
    assert abs(m) < 5  # praticamente zero


def test_projecao_final_extrapola_linearmente():
    from math_engine.engine import projecao_final
    # 50% apurado, candidato tem 500 votos → projeção 1000
    t = totais(100, 50, 2000, 1000, 1000)
    cand = CandidatoResumo("A", 500)
    assert projecao_final(cand, t) == 1000


def test_projecao_final_zero_apurado_nao_quebra():
    from math_engine.engine import projecao_final
    t = totais(100, 0, 1000, 0, 0)
    cand = CandidatoResumo("A", 0)
    assert projecao_final(cand, t) == 0


def test_detectar_virada_ignora_candidato_novo_no_snapshot_atual():
    """Regressão: quando aparecia um candidato novo (SQ inédito) num snapshot,
    a versão antiga tratava a `pos_anterior` dele como -1 e reportava uma
    virada fantasma — o líder atual 'passou' um cara que nunca estava lá."""
    from math_engine.engine import detectar_viradas
    anterior = [CandidatoResumo("A", 500), CandidatoResumo("B", 400)]
    # Snapshot novo introduz "X" — não pode gerar virada A→X nem B→X
    atual = [CandidatoResumo("A", 500), CandidatoResumo("B", 400), CandidatoResumo("X", 10)]
    assert detectar_viradas(atual, anterior) == []


def test_detectar_virada_real():
    from math_engine.engine import detectar_viradas
    anterior = [CandidatoResumo("A", 500), CandidatoResumo("B", 400)]
    atual = [CandidatoResumo("A", 500), CandidatoResumo("B", 600)]  # B passou A
    ev = detectar_viradas(atual, anterior)
    assert len(ev) == 1
    assert ev[0]["sq_candidato_a"] == "B"
    assert ev[0]["sq_candidato_b"] == "A"


def test_snapshot_com_totalizadas_maior_que_apto_nao_quebra():
    # anomalia TSE: restantes clampeado a 0 → decisão fecha imediatamente
    t = totais(100, 100, 1000, 1200, 900)
    cands = [
        CandidatoResumo("a", 600),
        CandidatoResumo("b", 300),
    ]
    assert votos_restantes_max(t) == 0
    assert eleito_majoritario(cands, t) is True
