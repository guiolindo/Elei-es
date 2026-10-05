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


def test_parse_qt_votos_validos_inclui_sub_judice():
    """Caso RJ Gov 04/10/2026: candidato Garotinho estava "Indeferido em prazo
    recursal" (sub judice). O TSE separa esses votos do `v.vv` do payload
    porque podem virar nulos se o recurso for rejeitado — mas enquanto roda,
    a Lei 9.504 art. 16-A manda contar como válidos pros efeitos de maioria
    absoluta no 1T. O parser agora usa max(vv, sum(cand.vap)) pra não
    subestimar o denominador e produzir falso-positivo de ELEITO_MAJORITARIO.
    """
    payload = {
        "dg": "04/10/2026", "hg": "22:30:00",
        "s": {"ts": 37675, "st": 37675},
        "e": {"te": 12842517, "est": 12842517, "c": 9845867, "a": 2996650},
        "v": {"vv": 8394627, "vb": 501537, "vn": 675292},  # TSE's vv exclui o sub judice
        "carg": [{
            "agr": [{
                "par": [{
                    "cand": [
                        {"sqcand": "LIDER", "vap": 4271199, "pvap": 49.27, "nmu": "LIDER", "n": 22},
                        {"sqcand": "SEG",   "vap": 3706984, "pvap": 42.76, "nmu": "SEG",   "n": 15},
                        {"sqcand": "GAR",   "vap": 274411,  "pvap": 3.17,  "nmu": "GAROTINHO", "n": 10},
                        {"sqcand": "D",     "vap": 235347,  "pvap": 2.71,  "nmu": "D", "n": 11},
                        {"sqcand": "E",     "vap": 84889,   "pvap": 0.98,  "nmu": "E", "n": 12},
                    ]
                }]
            }]
        }],
    }
    p = parse_snapshot(payload)
    soma = 4271199 + 3706984 + 274411 + 235347 + 84889
    # Piso vence: TSE vv (8394627) < soma (8572830)
    assert p.totais.qt_votos_validos == soma, (
        f"Esperava max(vv_tse, soma_vap)={soma}, obteve {p.totais.qt_votos_validos}"
    )
    # Com o denominador correto, 2 × 4271199 = 8542398 NÃO ultrapassa
    # 8572830 → líder NÃO tem maioria absoluta → vai pro 2T.
    assert 2 * 4271199 < p.totais.qt_votos_validos


def test_parse_qt_votos_validos_mantem_vv_quando_maior():
    """Caso normal: TSE's vv >= soma. Mantém vv (nunca abaixa)."""
    payload = {
        "s": {"ts": 100, "st": 100},
        "e": {"te": 1000, "est": 1000, "c": 900, "a": 100},
        "v": {"vv": 800, "vb": 50, "vn": 50},
        "carg": [{"agr": [{"par": [{"cand": [
            {"sqcand": "A", "vap": 400},
            {"sqcand": "B", "vap": 300},
        ]}]}]}],
    }
    p = parse_snapshot(payload)
    assert p.totais.qt_votos_validos == 800  # vv do TSE, não a soma 700
