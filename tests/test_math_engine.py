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


def test_segundo_turno_nao_definido_lider_pode_vencer_1t():
    """QA bug #1: 2º turno era declarado definido só olhando 3º vs 2º,
    ignorando a possibilidade de o líder ainda vencer no 1º turno.
    Cenário: A=450k (45%), B=300k (30%), C=50k (5%), restantes=200k.
    - 3º NÃO alcança 2º (50k+200k=250k < 300k) → check antigo passava
    - MAS: A pode ir a 650k dos 1200k válidos máximos → maioria absoluta
      no 1º turno é possível → não pode dizer que vai pra 2º turno."""
    # apto=1200, apto_tz=1000, restantes=200 (dado direto)
    t = totais(100, 70, 1200, 1000, 800)
    cands = [
        CandidatoResumo("A", 450),
        CandidatoResumo("B", 300),
        CandidatoResumo("C", 50),
    ]
    # A pode chegar a 650 dos 1000 válidos máximos (800+200) → 650*2=1300 > 1000
    # → líder ainda pode vencer no 1º turno, então NÃO é 2º turno definido
    assert segundo_turno_definido(cands, t) is False


def test_segundo_turno_definido_apos_1t_impossivel():
    """Complemento do teste acima: quando o líder também não pode mais
    fechar 1º turno E o 3º está eliminado do top-2, aí sim é 2t definido."""
    # Agora líder tem 450 dos 900 apurados; restantes só 60
    # A+60=510, dobrando=1020, válidos_max=900+60=960 → 1020>960 SIM pode vencer
    # Precisa forçar líder pra impossibilitar 1t:
    # Ex.: A=400, B=350, C=50, validos=900, restantes=50 → A_max=450, max_validos=950
    # 450*2=900, não > 950 → não pode vencer 1t. 3º: 50+50=100 < 350 → não alcança 2º.
    t = totais(100, 90, 1000, 950, 900)
    cands = [
        CandidatoResumo("A", 400),
        CandidatoResumo("B", 350),
        CandidatoResumo("C", 50),
    ]
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


def test_governador_precisa_maioria_absoluta_1t():
    """Governador é regido pelo art. 28 + 77 §2º CF: precisa de maioria
    absoluta dos válidos no 1T ou vai a 2º turno. Antes o motor tratava
    governador igual a senador (só inalcançabilidade)."""
    from math_engine.engine import eleito_majoritario, avaliar_apuracao
    # A=40%, B=20%, C=10% dos válidos, restantes muito pequenos.
    # A é inalcançável pelo 2º (900-20=880 vs 200+? → depende).
    # Mas A não tem maioria absoluta e nem consegue → deve ir a 2T.
    t = totais(100, 95, 1000, 950, 950)
    cands = [
        CandidatoResumo("A", 400),
        CandidatoResumo("B", 200),
        CandidatoResumo("C", 100),
    ]
    # Sem exigir MA: 200 + 50 = 250 < 400 → inalcançável → seria eleito
    assert eleito_majoritario(cands, t, exige_maioria_absoluta=False) is True
    # Exigindo MA: 400 * 2 = 800, validos_max = 950 + 50 = 1000 → 800 > 1000? NÃO
    # Portanto não tem maioria absoluta garantida → não eleito
    assert eleito_majoritario(cands, t, exige_maioria_absoluta=True) is False
    # avaliar_apuracao com cargo=3 (governador) NÃO deve emitir ELEITO_MAJORITARIO
    ev = avaliar_apuracao(cands, t, cod_cargo=3)
    tipos = [e["tipo"] for e in ev]
    assert "ELEITO_MAJORITARIO" not in tipos


def test_governador_com_maioria_absoluta_garantida_1t():
    """Se o líder do governador tem maioria absoluta MATEMATICAMENTE
    garantida (2 × votos_lider > validos_max), aí sim ganha em 1T."""
    from math_engine.engine import eleito_majoritario, avaliar_apuracao
    t = totais(100, 90, 1000, 900, 900)
    cands = [
        CandidatoResumo("A", 600),   # 600 * 2 = 1200 > validos_max=1000
        CandidatoResumo("B", 200),
    ]
    assert eleito_majoritario(cands, t, exige_maioria_absoluta=True) is True
    ev = avaliar_apuracao(cands, t, cod_cargo=3)
    assert any(e["tipo"] == "ELEITO_MAJORITARIO" for e in ev)


def test_2t_presidente_eleito_emite_ELEITO_2T():
    """No 2º turno só há 2 candidatos e quem tiver mais votos vence.
    Motor deve emitir ELEITO_2T (não ELEITO_1T) e NÃO deve emitir
    SEGUNDO_TURNO_DEFINIDO (não existe 3T)."""
    from math_engine.engine import avaliar_apuracao
    # apto=1000, apto_tz=950 → restantes = 50
    t = totais(100, 95, 1000, 950, 900)
    cands = [
        CandidatoResumo("A", 500),
        CandidatoResumo("B", 400),
    ]
    # A vence: 400 + 50 = 450 < 500 → matematicamente inalcançável (estrito)
    ev = avaliar_apuracao(cands, t, cod_cargo=1, turno=2)
    tipos = [e["tipo"] for e in ev]
    assert "ELEITO_2T" in tipos, f"Faltou ELEITO_2T em {tipos}"
    assert "ELEITO_1T" not in tipos, "2T não pode emitir ELEITO_1T"
    assert "SEGUNDO_TURNO_DEFINIDO" not in tipos, "Não existe 3T"
    e2t = next(e for e in ev if e["tipo"] == "ELEITO_2T")
    assert e2t["sq_candidato_a"] == "A"
    assert e2t["detalhes"]["turno"] == 2


def test_2t_governador_emite_ELEITO_MAJORITARIO_com_turno_2():
    """Governador no 2T: emite ELEITO_MAJORITARIO com detalhes.turno=2."""
    from math_engine.engine import avaliar_apuracao
    t = totais(100, 95, 1000, 950, 900)
    cands = [
        CandidatoResumo("A", 500),
        CandidatoResumo("B", 400),
    ]
    ev = avaliar_apuracao(cands, t, cod_cargo=3, turno=2)
    tipos = [e["tipo"] for e in ev]
    assert "ELEITO_MAJORITARIO" in tipos
    assert "ELEITO_2T" not in tipos  # ELEITO_2T é exclusivo do presidente
    e = next(x for x in ev if x["tipo"] == "ELEITO_MAJORITARIO")
    assert e["detalhes"]["turno"] == 2


def test_2t_no_fio_nao_declara_vencedor():
    """Se o 2º ainda pode alcançar o líder no 2T, ninguém é declarado."""
    from math_engine.engine import avaliar_apuracao
    t = totais(100, 85, 1000, 850, 850)
    cands = [
        CandidatoResumo("A", 450),
        CandidatoResumo("B", 400),   # +150 restantes = 550 > 450 → pode virar
    ]
    ev = avaliar_apuracao(cands, t, cod_cargo=1, turno=2)
    tipos = [e["tipo"] for e in ev]
    assert "ELEITO_2T" not in tipos
    assert "ELEITO_1T" not in tipos


def test_2t_empate_desempate_por_idade_art_110_ce():
    """Art. 110 do Código Eleitoral: em caso de empate no 2T (100%
    apurado, mesmo número de votos), vence o mais idoso. Motor só
    decide se as idades forem fornecidas em CandidatoResumo."""
    from math_engine.engine import avaliar_apuracao
    # 100% apurado, empate exato
    t = totais(100, 100, 1000, 1000, 900)
    cands = [
        CandidatoResumo("A", 450, idade_anos=68),
        CandidatoResumo("B", 450, idade_anos=55),
    ]
    ev = avaliar_apuracao(cands, t, cod_cargo=1, turno=2)
    tipos = [e["tipo"] for e in ev]
    assert "ELEITO_2T" in tipos
    e = next(x for x in ev if x["tipo"] == "ELEITO_2T")
    assert e["sq_candidato_a"] == "A", "Mais velho (68) deveria vencer"
    assert e["detalhes"]["criterio_desempate"] == "idade_art_110_ce"
    assert e["detalhes"]["margem"] == 0


def test_2t_empate_sem_idade_nao_decide():
    """Se as idades não foram fornecidas, o motor não presume e deixa
    em disputa. TSE faz o desempate formalmente."""
    from math_engine.engine import avaliar_apuracao
    t = totais(100, 100, 1000, 1000, 900)
    cands = [
        CandidatoResumo("A", 450),
        CandidatoResumo("B", 450),
    ]
    ev = avaliar_apuracao(cands, t, cod_cargo=1, turno=2)
    assert ev == [], "Sem idade não pode decidir empate"


def test_2t_empate_com_mesma_idade_nao_decide():
    """Se as duas idades são iguais (raríssimo mas possível), o motor
    também não decide."""
    from math_engine.engine import avaliar_apuracao
    t = totais(100, 100, 1000, 1000, 900)
    cands = [
        CandidatoResumo("A", 450, idade_anos=60),
        CandidatoResumo("B", 450, idade_anos=60),
    ]
    ev = avaliar_apuracao(cands, t, cod_cargo=1, turno=2)
    assert ev == []


def test_2t_senador_nao_faz_sentido():
    """Senador não tem 2º turno. Se por algum motivo alguém chamar
    avaliar_apuracao com cargo=5 e turno=2, retorna vazio."""
    from math_engine.engine import avaliar_apuracao
    t = totais(100, 90, 1000, 900, 900)
    cands = [CandidatoResumo("A", 500), CandidatoResumo("B", 300)]
    ev = avaliar_apuracao(cands, t, cod_cargo=5, turno=2)
    assert ev == []


def test_governador_2_turno_definido():
    """Governador segue a mesma regra do Presidente (CF art. 28 → 77).
    Se o líder não pode fechar 1T e o 3º está eliminado do top-2,
    o motor DEVE emitir SEGUNDO_TURNO_DEFINIDO — igual pra presidente.
    Antes esse evento só saía pra cargo=1."""
    from math_engine.engine import avaliar_apuracao
    # A=400, B=350, C=50, restantes=50. A_max=450, validos_max=950.
    # 450*2=900 < 950 → líder não pode fechar 1T.
    # C+50=100 < 350 → 3º fora.
    t = totais(100, 90, 1000, 950, 900)
    cands = [
        CandidatoResumo("A", 400),
        CandidatoResumo("B", 350),
        CandidatoResumo("C", 50),
    ]
    ev = avaliar_apuracao(cands, t, cod_cargo=3)   # Governador
    tipos = [e["tipo"] for e in ev]
    assert "SEGUNDO_TURNO_DEFINIDO" in tipos, \
        f"Governador deveria emitir 2T definido, emitiu {tipos}"
    # Verifica que A vs B foram nomeados
    e2t = next(e for e in ev if e["tipo"] == "SEGUNDO_TURNO_DEFINIDO")
    assert {e2t["sq_candidato_a"], e2t["sq_candidato_b"]} == {"A", "B"}


def test_senador_1_vaga_maioria_simples():
    """Senador segue art. 46 CF — maioria simples. Não exige maioria
    absoluta. (Regra hipotética pra ano de renovação 1/3; em 2026 são
    2 vagas e cai no eleitos_majoritario_multivaga)."""
    from math_engine.engine import eleito_majoritario
    t = totais(100, 95, 1000, 950, 950)
    cands = [
        CandidatoResumo("A", 400),
        CandidatoResumo("B", 200),
    ]
    # Sem exigir MA (regra correta de senador): inalcançável → eleito
    assert eleito_majoritario(cands, t, exige_maioria_absoluta=False) is True


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


def test_senador_2026_precisa_de_2_vagas():
    """QA bug #3: senador em 2026 elege 2 por UF (renovação 2/3), não 1.
    O 2º colocado deve ser considerado eleito também."""
    from math_engine.engine import eleitos_majoritario_multivaga
    # 3 candidatos, top-2 muito à frente do 3º, restantes pequenos → 2 eleitos
    t = totais(100, 90, 1000, 900, 900)
    cands = [
        CandidatoResumo("A", 400),
        CandidatoResumo("B", 300),
        CandidatoResumo("C", 100),
    ]
    eleitos = eleitos_majoritario_multivaga(cands, t, vagas=2)
    assert len(eleitos) == 2
    assert eleitos[0].sq_candidato == "A"
    assert eleitos[1].sq_candidato == "B"


def test_senador_2026_top2_no_fio_nao_declara():
    """Se o 3º ainda pode alcançar o 2º, não fecha ninguém em senador (2 vagas)."""
    from math_engine.engine import eleitos_majoritario_multivaga
    t = totais(100, 90, 1000, 900, 900)
    cands = [
        CandidatoResumo("A", 400),
        CandidatoResumo("B", 300),
        CandidatoResumo("C", 200),  # +100 restantes = 300 = empate técnico
    ]
    assert eleitos_majoritario_multivaga(cands, t, vagas=2) == []


def test_avaliar_apuracao_senador_2026_declara_top_2():
    """avaliar_apuracao pra senador (cargo 5) usa 2 vagas por padrão em 2026."""
    from math_engine.engine import avaliar_apuracao
    t = totais(100, 90, 1000, 900, 900)
    cands = [
        CandidatoResumo("A", 500),
        CandidatoResumo("B", 250),
        CandidatoResumo("C", 100),
    ]
    ev = avaliar_apuracao(cands, t, cod_cargo=5)
    tipos = [e["tipo"] for e in ev]
    # Deve emitir 2 ELEITO_MAJORITARIO (para A e B)
    assert tipos.count("ELEITO_MAJORITARIO") == 2
    sq_eleitos = {e["sq_candidato_a"] for e in ev if e["tipo"] == "ELEITO_MAJORITARIO"}
    assert sq_eleitos == {"A", "B"}


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


def test_detectar_viradas_sem_votos_nao_emite():
    """Pré-apuração todos têm 0 votos — ordem é arbitrária, não deve
    emitir virada fantasma."""
    from math_engine.engine import detectar_viradas, CandidatoResumo
    a = [CandidatoResumo("A", 0), CandidatoResumo("B", 0), CandidatoResumo("C", 0)]
    b = [CandidatoResumo("B", 0), CandidatoResumo("A", 0), CandidatoResumo("C", 0)]
    assert detectar_viradas(a, b) == []
    assert detectar_viradas(b, a) == []


def test_detectar_viradas_com_votos_emite():
    """Com votos reais, virada legítima é emitida."""
    from math_engine.engine import detectar_viradas, CandidatoResumo
    antes = [CandidatoResumo("A", 100), CandidatoResumo("B", 50)]
    agora = [CandidatoResumo("B", 150), CandidatoResumo("A", 100)]
    evs = detectar_viradas(agora, antes)
    assert any(e["tipo"] == "VIRADA" and e["sq_candidato_a"] == "B"
               and e["sq_candidato_b"] == "A" for e in evs)
