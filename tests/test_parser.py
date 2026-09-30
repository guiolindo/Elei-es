from poller.parser import parse_snapshot


def test_parse_schema_tse_2026_real():
    """Schema oficial confirmado em 30/09/2026 via
    resultados.tse.jus.br/oficial/ele2026/6257/dados/br/br-c0001-e006257-u.json.

    Totais estão no ROOT em s/e/v como DICTS (não escalares como o
    parser antigo assumia). Candidatos estão aninhados em
    carg[0].agr[N].par[N].cand[N]."""
    payload = {
        "dg": "05/10/2026 20:35:12",
        "s": {"ts": "500", "st": "300"},
        "e": {"te": "2000000", "est": "1200000", "c": "1000000", "a": "200000"},
        "v": {"vv": "900000", "vb": "50000", "vn": "50000"},
        "carg": [{
            "cd": "1",
            "agr": [{
                "n": "1",
                "par": [{
                    "n": "13", "sg": "PT",
                    "cand": [
                        {"sqcand": "A1", "n": "13", "nmu": "FULANO",
                         "vap": "500000", "pvap": "55,55"},
                    ],
                }],
            }, {
                "n": "2",
                "par": [{
                    "n": "22", "sg": "PL",
                    "cand": [
                        {"sqcand": "A2", "n": "22", "nmu": "CICLANO",
                         "vap": "300000", "pvap": "33,33"},
                    ],
                }],
            }],
        }],
    }
    p = parse_snapshot(payload)
    assert p.totais.qt_secoes_total == 500
    assert p.totais.qt_secoes_totalizadas == 300
    assert p.totais.qt_eleitorado_apto == 2000000
    assert p.totais.qt_comparecimento == 1000000
    assert p.totais.qt_abstencoes == 200000
    assert p.totais.qt_votos_validos == 900000
    assert p.totais.qt_votos_brancos == 50000
    assert p.totais.qt_votos_nulos == 50000
    assert len(p.candidatos) == 2
    sqs = {c.sq_candidato for c in p.candidatos}
    assert sqs == {"A1", "A2"}
    a1 = next(c for c in p.candidatos if c.sq_candidato == "A1")
    assert a1.votos == 500000
    assert a1.nome_urna == "FULANO"
    assert abs(a1.pct_validos - 55.55) < 0.01


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
