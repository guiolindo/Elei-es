from poller.parser import parse_snapshot


def test_parse_schema_tse_abreviado():
    payload = {
        "dg": "05/10/2026 20:35:12",
        "carg": [{
            "s": "500", "st": "300",
            "e": "2000000", "eA": "1200000",
            "c": "1000000", "a": "200000",
            "vv": "900000", "vb": "50000", "vn": "50000",
            "cand": [
                {"sqcand": "A1", "n": "13", "nm": "FULANO", "vap": "500000", "pvap": "55,55"},
                {"sqcand": "A2", "n": "22", "nm": "CICLANO", "vap": "300000", "pvap": "33,33"},
            ],
        }],
    }
    p = parse_snapshot(payload)
    assert p.totais.qt_secoes_total == 500
    assert p.totais.qt_secoes_totalizadas == 300
    assert p.totais.qt_votos_validos == 900000
    assert len(p.candidatos) == 2
    assert p.candidatos[0].sq_candidato == "A1"
    assert p.candidatos[0].votos == 500000
    assert abs(p.candidatos[0].pct_validos - 55.55) < 0.01


def test_parse_schema_normalizado():
    payload = {
        "gerado_em": "2026-10-05 20:35:12",
        "qt_secoes_total": 100, "qt_secoes_totalizadas": 90,
        "qt_eleitorado_apto": 1000, "qt_eleitorado_apto_totalizadas": 900,
        "qt_comparecimento": 800, "qt_abstencoes": 100,
        "qt_votos_validos": 700, "qt_votos_brancos": 50, "qt_votos_nulos": 50,
        "candidatos": [
            {"sq_candidato": "X", "numero": 13, "nome_urna": "X", "votos": 400, "pct_validos": 57.14},
            {"sq_candidato": "Y", "numero": 22, "nome_urna": "Y", "votos": 300, "pct_validos": 42.86},
        ],
    }
    p = parse_snapshot(payload)
    assert p.totais.qt_secoes_totalizadas == 90
    assert p.candidatos[1].votos == 300


def test_parse_vazio_tolerante():
    p = parse_snapshot({})
    assert p.totais.qt_secoes_total == 0
    assert p.candidatos == []
