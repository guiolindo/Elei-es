"""Garantias de timezone no parser de datas do TSE.

TSE devolve horários no fuso BRT (America/Sao_Paulo), sem offset no JSON.
Precisamos marcar explicitamente como BRT pra que a conversão pro Postgres
(TIMESTAMPTZ, salvo como UTC) resulte no instante correto.

Bug histórico: parser marcava como UTC → data no banco ficava 3h adiantada.
Também não combinava `dg` + `hg` (que vêm separados), perdendo totalmente a
hora de geração do TSE.
"""
from datetime import datetime, timedelta, timezone
from poller.parser import _parse_dt, _parse_dt_dg_hg, parse_snapshot

BRT = timezone(timedelta(hours=-3))


def test_parse_dt_formato_tse_canonico_vira_brt():
    d = _parse_dt("02/10/2026 20:13:54")
    assert d is not None
    assert d.tzinfo is not None
    assert d.utcoffset() == timedelta(hours=-3)
    # 20:13:54 BRT = 23:13:54 UTC
    assert d.astimezone(timezone.utc).hour == 23
    assert d.astimezone(timezone.utc).minute == 13


def test_parse_dt_dg_hg_combina_data_hora_separadas():
    """TSE real devolve dg='02/10/2026', hg='20:13:54' em chaves separadas."""
    d = _parse_dt_dg_hg("02/10/2026", "20:13:54")
    assert d is not None
    assert d.day == 2 and d.month == 10 and d.year == 2026
    assert d.hour == 20 and d.minute == 13
    assert d.utcoffset() == timedelta(hours=-3)


def test_parse_dt_dg_hg_sem_hora_meia_noite_brt():
    d = _parse_dt_dg_hg("02/10/2026", None)
    assert d is not None
    assert d.hour == 0 and d.minute == 0


def test_parse_dt_dg_hg_sem_data_none():
    assert _parse_dt_dg_hg(None, "20:13:54") is None


def test_parse_snapshot_pega_hora_via_dg_hg():
    """Payload no formato real do TSE 2026 (dg+hg separados)."""
    payload = {
        "s": {"ts": "100", "st": "50"},
        "e": {"te": "1000"},
        "v": {"vv": "500"},
        "dg": "04/10/2026",
        "hg": "18:30:45",
        "carg": [],
    }
    p = parse_snapshot(payload)
    assert p.totais.gerado_em is not None
    assert p.totais.gerado_em.day == 4
    assert p.totais.gerado_em.hour == 18
    assert p.totais.gerado_em.utcoffset() == timedelta(hours=-3)


def test_parse_snapshot_fallback_gerado_em_legado():
    """Fixtures/legado podem usar `gerado_em` já em string única."""
    payload = {"s": {}, "e": {}, "v": {}, "gerado_em": "2026-10-04 20:00:00",
               "carg": []}
    p = parse_snapshot(payload)
    assert p.totais.gerado_em is not None
    assert p.totais.gerado_em.hour == 20
