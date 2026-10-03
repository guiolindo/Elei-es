"""Teste contra JSON REAL do TSE baixado em 03/10/2026.

Pega o arquivo /oficial/ele2026/6257/dados/br/br-c0001-e006257-u.json
(presidente Brasil, pré-apuração) e valida que o parser extrai tudo
corretamente. Blind spot que fixtures sintéticas não cobrem.
"""
import json
import os
import pytest

from poller.parser import parse_snapshot

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures",
                        "tse_2026_br_pres_pre_apuracao.json")


@pytest.fixture
def tse_json():
    with open(FIXTURE) as f:
        return json.load(f)


def test_parse_tse_real_extrai_totais(tse_json):
    """O JSON real tem secoes_total=499248, eleitorado=158M."""
    parsed = parse_snapshot(tse_json)
    assert parsed.totais.qt_secoes_total == 499248
    assert parsed.totais.qt_eleitorado_apto == 158745502
    assert parsed.totais.qt_secoes_totalizadas == 0


def test_parse_tse_real_extrai_candidatos(tse_json):
    """12 candidatos a presidente devem ser extraídos."""
    parsed = parse_snapshot(tse_json)
    assert len(parsed.candidatos) == 12
    nomes = {c.nome_urna for c in parsed.candidatos}
    assert "LULA" in nomes
    assert any("BOLSONARO" in n for n in nomes)


def test_parse_tse_real_sqcandidato_formato(tse_json):
    """sq_candidato é string de dígitos no padrão TSE."""
    parsed = parse_snapshot(tse_json)
    for c in parsed.candidatos:
        assert c.sq_candidato.isdigit()
        assert len(c.sq_candidato) >= 10


def test_parse_tse_real_zero_votos_pre_apuracao(tse_json):
    """Pré-apuração: todos candidatos têm 0 votos."""
    parsed = parse_snapshot(tse_json)
    assert all(c.votos == 0 for c in parsed.candidatos)
