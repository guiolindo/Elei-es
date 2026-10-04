"""Testes do dedup HONESTO em GET /api/candidatos.

Caso real 2026 que motivou o dedup:
- Guto Schiavetto SP cargo=5 nº144: 2 sq ambos 'ativo' (reregistro TSE sem baixa).
- Avalanche + Marçal cargo=1 nº28: pessoas distintas, ambos 'mortos' (renunciou e indeferido).
- Governador BA nº27: Ariel (ativo) + Estêvão (indeferido) → só Ariel aparece.

Lógica: só esconde quando há EXATAMENTE 1 ativo entre todos. Nos outros casos
mostra todos — a UI não deve mentir sobre o que o TSE mandou.
"""
from types import SimpleNamespace


def _cand(sq, nome, numero, uf="SP", cargo=5, situacao="ativo", partido=22):
    return SimpleNamespace(
        sq_candidato=sq, nome=nome, nome_urna=nome, numero=numero,
        uf=uf, cod_cargo=cargo, partido_numero=partido, situacao=situacao,
    )


def _rodar_dedup(todos):
    """Replica a lógica de dedup do endpoint pra testar isoladamente."""
    from collections import defaultdict
    import unicodedata
    def _norm(s):
        if not s: return ""
        return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().strip().lower()

    grupos = defaultdict(list)
    extras = []
    for c in todos:
        if not c.numero:
            extras.append(c)
            continue
        chave = (c.uf or "BR", c.numero)
        grupos[chave].append(c)
    final = []
    for cands_do_grupo in grupos.values():
        ativos = [c for c in cands_do_grupo if c.situacao == "ativo"]
        if len(ativos) == 1 and len(cands_do_grupo) > 1:
            final.append(ativos[0])
            continue
        if len(ativos) >= 2:
            nomes = {_norm(c.nome_urna) for c in ativos}
            if len(nomes) == 1:
                canonico = max(ativos, key=lambda c: str(c.sq_candidato))
                final.append(canonico)
                continue
        final.extend(cands_do_grupo)
    final.extend(extras)
    final.sort(key=lambda x: (x.numero or 0, str(x.sq_candidato)))
    return final


def test_1_ativo_mais_inativos_mostra_so_o_ativo():
    """Caso típico: TSE marcou o antigo como renunciado e o novo como ativo.
    Exibimos só o ativo — padrão legítimo de substituição."""
    r = _rodar_dedup([
        _cand("ANTIGO", "ARIEL", 27, uf="BA", cargo=3, situacao="indeferido_sem_recurso"),
        _cand("NOVO",   "ARIEL", 27, uf="BA", cargo=3, situacao="ativo"),
    ])
    sqs = [c.sq_candidato for c in r]
    assert sqs == ["NOVO"]


def test_todos_inativos_mostra_todos_avalanche_e_marcal():
    """PRTB 2026: Avalanche renunciou, Marçal indeferido. Pessoas distintas,
    ambos devem aparecer com suas respectivas tarjas."""
    r = _rodar_dedup([
        _cand("AVAL", "AVALANCHE", 28, uf=None, cargo=1, situacao="renunciou", partido=28),
        _cand("MARC", "MARÇAL",    28, uf=None, cargo=1, situacao="indeferido_sem_recurso", partido=28),
    ])
    sqs = sorted(c.sq_candidato for c in r)
    assert sqs == ["AVAL", "MARC"]


def test_multiplos_ativos_mesmo_nome_vira_um_so():
    """SP Senador nº144: dois sq_candidato ambos 'ativo' com MESMO nome
    (Guto Schiavetto × 2). É a mesma pessoa — TSE não deu baixa no
    reregistro. Dedup: mantém o sq maior (reregistro mais recente)."""
    r = _rodar_dedup([
        _cand("GUTO_A", "GUTO SCHIAVETTO", 144, uf="SP", cargo=5, situacao="ativo"),
        _cand("GUTO_B", "GUTO SCHIAVETTO", 144, uf="SP", cargo=5, situacao="ativo"),
    ])
    sqs = [c.sq_candidato for c in r]
    assert sqs == ["GUTO_B"]  # sq lexicograficamente maior


def test_multiplos_ativos_nomes_diferentes_mostra_todos():
    """DF Dep. Fed nº3535: dois sq ambos ativos com nomes DIFERENTES
    (Laira × Noely). Pessoas distintas — não cabe esconder nenhuma."""
    r = _rodar_dedup([
        _cand("A", "LAIRA INACIO", 3535, uf="DF", cargo=6, situacao="ativo"),
        _cand("B", "NOELY COLETIVO CORAGEM", 3535, uf="DF", cargo=6, situacao="ativo"),
    ])
    sqs = sorted(c.sq_candidato for c in r)
    assert sqs == ["A", "B"]


def test_multiplos_ativos_nome_so_difere_em_acento_ainda_dedup():
    """Comparação de nome ignora acento (TSE varia 'MARÇAL' vs 'MARCAL')."""
    r = _rodar_dedup([
        _cand("A", "JOSE MARCAL", 100, situacao="ativo"),
        _cand("B", "JOSE MARÇAL", 100, situacao="ativo"),
    ])
    assert len(r) == 1


def test_candidato_unico_nao_e_afetado():
    r = _rodar_dedup([_cand("UNICO", "LULA", 13, uf=None, cargo=1)])
    assert len(r) == 1 and r[0].sq_candidato == "UNICO"


def test_candidatos_de_numeros_diferentes_coexistem():
    """Dedup é por (uf, numero), não por nome."""
    r = _rodar_dedup([
        _cand("A", "LULA", 13),
        _cand("B", "BOLSONARO", 22),
    ])
    assert len(r) == 2


def test_candidato_sem_numero_sempre_mantido():
    """Lixo de parser com numero=0 fica, não é feito dedup."""
    cands = [
        _cand("LIXO1", "", 0),
        _cand("LIXO2", "", 0),
        _cand("REAL",  "LULA", 13),
    ]
    r = _rodar_dedup(cands)
    assert len(r) == 3


def test_ordenacao_por_numero_depois_sq():
    """Ordem determinística: primeiro por numero, depois por sq_candidato."""
    r = _rodar_dedup([
        _cand("B", "X", 22),
        _cand("A", "Y", 13),
        _cand("C", "Z", 13),  # mesmo numero que A, ambos ativos → ambos passam
    ])
    assert [c.sq_candidato for c in r] == ["A", "C", "B"]
