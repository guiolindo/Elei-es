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


def test_snapshot_com_totalizadas_maior_que_apto_nao_quebra():
    # anomalia TSE: restantes clampeado a 0 → decisão fecha imediatamente
    t = totais(100, 100, 1000, 1200, 900)
    cands = [
        CandidatoResumo("a", 600),
        CandidatoResumo("b", 300),
    ]
    assert votos_restantes_max(t) == 0
    assert eleito_majoritario(cands, t) is True
