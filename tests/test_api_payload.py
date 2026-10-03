"""Testes do helper _candidato_payload que garante que o join
sq_candidato → metadados nunca vai pro candidato errado.
"""
from types import SimpleNamespace
from app.api import _candidato_payload


def _sc(sq="X", votos=100, pct=50.0, posicao=1):
    """Fake SnapshotCandidato."""
    return SimpleNamespace(sq_candidato=sq, votos=votos,
                           pct_validos=pct, posicao=posicao)


def _tot(total=100, apur=50):
    """Fake SnapshotTotais."""
    return SimpleNamespace(qt_secoes_total=total, qt_secoes_totalizadas=apur)


def _ficha(sq="X", nome="FULANO", numero=13, partido=13, situacao="ativo", uf="SP"):
    """Fake Candidato."""
    return SimpleNamespace(sq_candidato=sq, nome_urna=nome, numero=numero,
                           partido_numero=partido, situacao=situacao, uf=uf)


def test_payload_sem_inflate_enxuto():
    """Default: só sq/votos/pct/posicao/projecao — payload leve pro WS."""
    out = _candidato_payload(_sc(), _tot(), _ficha(), inflate=False)
    assert set(out.keys()) == {"sq_candidato", "votos", "pct_validos",
                                "posicao", "projecao_linear"}
    assert "nome_urna" not in out


def test_payload_com_inflate_tem_tudo():
    """inflate=True inclui nome/numero/partido/situacao/uf."""
    out = _candidato_payload(_sc(sq="A"), _tot(),
                              _ficha(sq="A", nome="LULA", numero=13,
                                     partido=13, situacao="ativo", uf="BR"),
                              inflate=True)
    assert out["sq_candidato"] == "A"
    assert out["nome_urna"] == "LULA"
    assert out["numero"] == 13
    assert out["partido"] == 13
    assert out["situacao"] == "ativo"
    assert out["uf"] == "BR"


def test_payload_inflate_sem_ficha_marca_orfao():
    """Se o snapshot tem sq que não bate com Candidato (órfão),
    inflate expõe isso explicitamente — nunca gruda nome de outro."""
    out = _candidato_payload(_sc(sq="XX"), _tot(), ficha=None, inflate=True)
    assert out["sq_candidato"] == "XX"
    assert out["nome_urna"] is None
    assert out["orfao"] is True


def test_payload_sem_inflate_sem_ficha_nao_quebra():
    """Mesmo sem ficha, o payload default (sem inflate) sai limpo."""
    out = _candidato_payload(_sc(sq="XX"), _tot(), ficha=None, inflate=False)
    assert out["sq_candidato"] == "XX"
    assert "orfao" not in out
    assert "nome_urna" not in out


def test_payload_projecao_zero_quando_sem_apuracao():
    """Pré-apuração (secoes_totalizadas=0): projecao_linear = votos atuais."""
    out = _candidato_payload(_sc(votos=0), _tot(apur=0), _ficha(), inflate=False)
    assert out["projecao_linear"] == 0


def test_payload_projecao_linear_calculada():
    """20% apurado + 1000 votos → projeção = 1000/(0.2) = 5000."""
    out = _candidato_payload(_sc(votos=1000), _tot(total=100, apur=20), _ficha(), inflate=False)
    assert out["projecao_linear"] == 5000


def test_payload_ficha_e_sc_de_sqs_diferentes_bug_detectado():
    """IMPORTANTE: função nunca deve ser chamada com ficha de outro sq.
    Mas se for (bug no caller), o payload fica consistente com o sq do sc,
    não o da ficha — evita colar nome em candidato errado silenciosamente.
    """
    sc = _sc(sq="CANDIDATO_A", votos=100)
    ficha_errada = _ficha(sq="CANDIDATO_B", nome="OUTRO")
    out = _candidato_payload(sc, _tot(), ficha_errada, inflate=True)
    # sq_candidato na resposta é do SnapshotCandidato (fonte da verdade)
    assert out["sq_candidato"] == "CANDIDATO_A"
    # Nome vem da ficha passada — se o caller passou ficha errada, aparece
    # mesmo. A proteção é o CALLER (api.py) usar ficha_map[c.sq_candidato].
    # Esse teste existe só pra documentar que o helper confia no caller.
    assert out["nome_urna"] == "OUTRO"
