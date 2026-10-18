"""Regras puras do bot do Telegram (sem rede, sem banco)."""
from datetime import datetime, timezone

from notif import telegram_bot as tb


def test_assinatura_do_1t_recebe_eleito_do_2t():
    # Assinaturas criadas no 1º turno gravaram ELEITO_1T; o motor emite
    # ELEITO_2T pro Presidente no 2º turno. Tem que chegar.
    assert tb._deve_enviar(["ELEITO_1T", "SEGUNDO_TURNO_DEFINIDO", "VIRADA"], "ELEITO_2T", 2)
    assert tb._deve_enviar(["ELEITO_MAJORITARIO", "VIRADA"], "ELEITO_MAJORITARIO", 2)
    assert tb._deve_enviar(["ELEITO_MAJORITARIO"], "ELEITO_2T", 2)


def test_quem_nao_marcou_eleito_nao_recebe():
    assert not tb._deve_enviar(["VIRADA"], "ELEITO_2T", 2)
    assert not tb._deve_enviar([], "VIRADA", 2)
    assert not tb._deve_enviar(None, "ELEITO_2T", 2)


def test_eliminado_no_2t_nao_duplica_o_alerta_de_eleito():
    assert not tb._deve_enviar(["MATEMATICAMENTE_ELIMINADO"], "MATEMATICAMENTE_ELIMINADO", 2)
    assert tb._deve_enviar(["MATEMATICAMENTE_ELIMINADO"], "MATEMATICAMENTE_ELIMINADO", 1)


def test_opcao_eleito_grava_todos_os_tipos_de_vitoria():
    assert set(tb.OPCOES_ALERTA["ELEITO"][1]) == {"ELEITO_1T", "ELEITO_2T", "ELEITO_MAJORITARIO"}


def test_turno_vigente_vira_no_fechamento_do_1t():
    antes = datetime(2026, 10, 4, 19, 59, tzinfo=timezone.utc)   # 16h59 BRT
    depois = datetime(2026, 10, 4, 20, 0, tzinfo=timezone.utc)   # 17h00 BRT
    assert tb._turno_vigente(antes) == 1
    assert tb._turno_vigente(depois) == 2


def test_opcoes_do_2t():
    assert tb._opcoes_do_turno(2, cargo=1) == ["ELEITO", "VIRADA", "BOLETIM", "VIRADA_UF"]
    assert tb._opcoes_do_turno(2, cargo=3) == ["ELEITO", "VIRADA", "BOLETIM"]  # governador: sem "nos estados"
    assert "SEGUNDO_TURNO_DEFINIDO" in tb._opcoes_do_turno(1)


def test_marcos_do_boletim():
    assert tb._marco_cruzado(0.0, 0.001) == 0.0          # começou
    assert tb._marco_cruzado(0.0, 0.30) == 0.25          # pulou direto: só o maior marco
    assert tb._marco_cruzado(0.24, 0.26) == 0.25
    assert tb._marco_cruzado(0.26, 0.49) is None
    assert tb._marco_cruzado(0.49, 0.80) == 0.75         # 50 e 75 no mesmo ciclo: um boletim só
    assert tb._marco_cruzado(0.95, 1.0) == 1.0
    assert tb._marco_cruzado(1.0, 1.0) is None


def test_boletim_e_virada_uf_sao_familias_proprias():
    assert tb._deve_enviar(["BOLETIM"], "BOLETIM", 2)
    assert not tb._deve_enviar(["ELEITO_1T", "VIRADA"], "BOLETIM", 2)   # assinaturas antigas não recebem boletim
    assert not tb._deve_enviar(["VIRADA"], "VIRADA_UF", 2)


def test_parse_turno():
    assert tb._parse_turno(["governador", "DF", "1t"]) == 1
    assert tb._parse_turno(["2T"]) == 2
    assert tb._parse_turno(["2º", "turno"]) is None
    assert tb._parse_turno(["1", "SP"]) is None  # "1" é o cargo Presidente


def test_cargo_por_numero():
    assert tb._cargo_por_numero(13, "BR") == 1
    assert tb._cargo_por_numero(22, "DF") == 3
    assert tb._cargo_por_numero(131, "SP") == 5
    assert tb._cargo_por_numero(1313, "SP") == 6
    assert tb._cargo_por_numero(13131, "SP") == 7


def test_titulos_de_alerta():
    assert tb._titulo_alerta("ELEITO_2T", 2) == "Eleito no 2º turno"
    assert tb._titulo_alerta("ELEITO_MAJORITARIO", 2) == "Eleito no 2º turno"
    assert tb._titulo_alerta("ELEITO_MAJORITARIO", 1) == "Eleito"
    assert tb._titulo_alerta("ELEITO_1T", 1) == "Eleito no 1º turno"
    assert tb._titulo_alerta("VIRADA", 2) == "Virada"


def test_texto_evento():
    assert tb._texto_evento("VIRADA", "*A*", "*B*", 2) == "*A* passou *B*"
    assert tb._texto_evento("ELEITO_2T", "*A*", "", 2) == "*A* eleito(a) no 2º turno"
    assert tb._texto_evento("SEGUNDO_TURNO_DEFINIDO", "*A*", "*B*", 1) == "2º turno: *A* × *B*"


def test_teclado_de_alertas_marca_tipo_antigo_pela_familia():
    kb = tb._kb_tipos(["ELEITO_1T"], turno=2)
    textos = [linha[0]["text"] for linha in kb["inline_keyboard"][:-1]]
    assert textos[0].startswith("✅") and "eleito" in textos[0]
    assert textos[1].startswith("◻")


def test_df_e_distrito_federal_nao_deputado():
    # "/placar governador DF" lia DF como Dep. Federal e caía em SP.
    assert tb._parse_cargo_uf(["governador", "DF"]) == (3, "DF")
    assert tb._parse_cargo_uf(["gov", "df"]) == (3, "DF")
    assert tb._parse_cargo_uf(["deputado", "SP"]) == (6, "SP")


def test_proporcional_usa_funcoes_que_existem():
    # /proporcional importava uma função inexistente e respondia sempre
    # "indisponível". Garante que o que o bot importa existe e roda.
    from math_engine.proporcional import (
        CandidatoProporcional, calcular_eleitos_proporcional, VAGAS_DEP_FEDERAL,
    )
    cands = [CandidatoProporcional(str(i), f"C{i}", 1000 + i, 13 if i < 5 else 22, 100 * (10 - i))
             for i in range(10)]
    r = calcular_eleitos_proporcional(cands, vagas=VAGAS_DEP_FEDERAL["AC"])
    assert sum(1 for c in r.candidatos if c.status == "eleito") == VAGAS_DEP_FEDERAL["AC"]
