"""Garante que o parser de situacao casa variações acentuadas do TSE.

Bug real (2026, Leonardo Avalanche): descricaoSituacao='Renúncia' (com
acento no ú) → match "renunc" não casava com "renúncia" → candidato
virava 'ativo' silenciosamente.
"""
from poller.candidatos_tse import parse_candidato


def _payload(ds):
    return {
        "id": "280002554479",
        "nomeUrna": "LEONARDO AVALANCHE",
        "numero": 28,
        "partido": {"sigla": "PRTB", "nome": "..."},
        "descricaoSituacao": ds,
    }


def test_renuncia_com_acento_vira_renunciou():
    c = parse_candidato(_payload("Renúncia"), cod_cargo=1, uf="BR")
    assert c.situacao == "renunciou"


def test_renuncia_sem_acento_tambem():
    c = parse_candidato(_payload("Renuncia"), cod_cargo=1, uf="BR")
    assert c.situacao == "renunciou"


def test_inapto_vira_indeferido():
    c = parse_candidato(_payload("Inapto"), cod_cargo=1, uf="BR")
    assert c.situacao == "indeferido_sem_recurso"


def test_inelegivel_com_acento_vira_indeferido():
    c = parse_candidato(_payload("Inelegível"), cod_cargo=1, uf="BR")
    assert c.situacao == "indeferido_sem_recurso"


def test_cassado_vira_cassado():
    c = parse_candidato(_payload("Cassado"), cod_cargo=1, uf="BR")
    assert c.situacao == "cassado"


def test_cancelado_vira_cancelado():
    c = parse_candidato(_payload("Registro cancelado"), cod_cargo=1, uf="BR")
    assert c.situacao == "cancelado"


def test_indeferido_sem_recurso():
    c = parse_candidato(_payload("Indeferido"), cod_cargo=1, uf="BR")
    assert c.situacao == "indeferido_sem_recurso"


def test_deferido_vira_ativo():
    c = parse_candidato(_payload("Deferido"), cod_cargo=1, uf="BR")
    assert c.situacao == "ativo"


def test_sem_descricao_vira_ativo():
    p = {"id": "X", "nomeUrna": "Y", "numero": 1, "partido": {"sigla": "A", "nome": ""}}
    c = parse_candidato(p, cod_cargo=1, uf="BR")
    assert c.situacao == "ativo"


# ============ DF Dep. Distrital (cargo 7 → c0008 no TSE) ============

def test_cargo_tse_df_distrital_usa_c0008():
    """DF: Dep. Distrital é cargo 7 no nosso enum, mas c0008 na URL do TSE."""
    from poller.tse_client import cargo_tse, resultado_url
    assert cargo_tse(7, "DF") == 8
    assert cargo_tse(7, "df") == 8
    assert cargo_tse(7, "SP") == 7
    assert cargo_tse(3, "DF") == 3  # governador DF normal
    url = resultado_url("https://x.com/ele2026", 6259, 7, "DF")
    assert "df-c0008-e006259" in url, url


def test_cargo_tse_outras_ufs_cargo_7_fica_7():
    from poller.tse_client import cargo_tse
    for uf in ("SP","RJ","MG","BA","AC","AM","AL","CE","ES","GO","MA","MT","MS","PA","PB","PE","PI","PR","RN","RO","RR","RS","SC","SE","TO","AP"):
        assert cargo_tse(7, uf) == 7, uf
