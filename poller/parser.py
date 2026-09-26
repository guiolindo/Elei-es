"""Parser dos JSONs de resultado do TSE.

O formato oficial usa nomes abreviados. Este módulo isola essa dependência —
se o TSE mudar o schema, só este arquivo muda. Todos os campos que não vêm
no JSON são tratados como 0.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


def _to_int(v: Any) -> int:
    if v is None or v == "":
        return 0
    if isinstance(v, str):
        return int(v.replace(".", "").replace(",", ""))
    return int(v)


def _to_float(v: Any) -> float:
    if v is None or v == "":
        return 0.0
    if isinstance(v, str):
        return float(v.replace(",", "."))
    return float(v)


@dataclass
class ParsedTotais:
    qt_secoes_total: int
    qt_secoes_totalizadas: int
    qt_eleitorado_apto: int
    qt_eleitorado_apto_totalizadas: int
    qt_comparecimento: int
    qt_abstencoes: int
    qt_votos_validos: int
    qt_votos_brancos: int
    qt_votos_nulos: int
    gerado_em: datetime | None


@dataclass
class ParsedCandidato:
    sq_candidato: str
    numero: int
    nome_urna: str
    votos: int
    pct_validos: float


@dataclass
class ParsedSnapshot:
    totais: ParsedTotais
    candidatos: list[ParsedCandidato]


def _parse_dt(raw: str | None) -> datetime | None:
    if not raw:
        return None
    # TSE costuma mandar "dd/mm/aaaa hh:mm:ss"
    for fmt in ("%d/%m/%Y %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def parse_snapshot(payload: dict) -> ParsedSnapshot:
    """Converte payload JSON do TSE em objetos tipados.

    Suporta tanto o schema oficial da CDN (chaves como `st`, `s`, `pst`,
    `cand`) quanto uma versão espelho normalizada (chaves em snake_case),
    usada em fixtures e no modo simulação.
    """
    # aceita variantes: cargos > [ { agr > [ { cand } ] } ] ou direto
    if "carg" in payload and isinstance(payload["carg"], list) and payload["carg"]:
        raiz = payload["carg"][0]
    else:
        raiz = payload

    tot = ParsedTotais(
        qt_secoes_total=_to_int(raiz.get("s") or raiz.get("qt_secoes_total")),
        qt_secoes_totalizadas=_to_int(raiz.get("st") or raiz.get("qt_secoes_totalizadas")),
        qt_eleitorado_apto=_to_int(raiz.get("e") or raiz.get("qt_eleitorado_apto")),
        qt_eleitorado_apto_totalizadas=_to_int(
            raiz.get("eA") or raiz.get("qt_eleitorado_apto_totalizadas")
        ),
        qt_comparecimento=_to_int(raiz.get("c") or raiz.get("qt_comparecimento")),
        qt_abstencoes=_to_int(raiz.get("a") or raiz.get("qt_abstencoes")),
        qt_votos_validos=_to_int(raiz.get("vv") or raiz.get("qt_votos_validos")),
        qt_votos_brancos=_to_int(raiz.get("vb") or raiz.get("qt_votos_brancos")),
        qt_votos_nulos=_to_int(raiz.get("vn") or raiz.get("qt_votos_nulos")),
        gerado_em=_parse_dt(payload.get("dg") or payload.get("gerado_em")),
    )

    candidatos_raw = raiz.get("cand") or raiz.get("candidatos") or []
    candidatos = [
        ParsedCandidato(
            sq_candidato=str(c.get("sqcand") or c.get("sq_candidato") or ""),
            numero=_to_int(c.get("n") or c.get("numero")),
            nome_urna=(c.get("nm") or c.get("nome_urna") or "").strip(),
            votos=_to_int(c.get("vap") or c.get("votos")),
            pct_validos=_to_float(c.get("pvap") or c.get("pct_validos")),
        )
        for c in candidatos_raw
        if (c.get("sqcand") or c.get("sq_candidato"))
    ]
    return ParsedSnapshot(totais=tot, candidatos=candidatos)
