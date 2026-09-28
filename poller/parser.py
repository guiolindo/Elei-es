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
class ParsedMunicipio:
    """Breakdown de votos de candidatos em um município específico."""
    cod_ibge: str      # 7 dígitos do IBGE
    nome: str
    candidatos: list[ParsedCandidato]


@dataclass
class ParsedSnapshot:
    totais: ParsedTotais
    candidatos: list[ParsedCandidato]
    municipios: list[ParsedMunicipio]


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

    def _parse_cand_list(raw_list) -> list[ParsedCandidato]:
        out = []
        for c in raw_list or []:
            if not isinstance(c, dict):
                continue
            sq = c.get("sqcand") or c.get("sq_candidato") or c.get("sqCand") or c.get("id")
            if not sq:
                continue
            out.append(ParsedCandidato(
                sq_candidato=str(sq),
                numero=_to_int(c.get("n") or c.get("numero") or c.get("nr")),
                nome_urna=(c.get("nm") or c.get("nome_urna") or "").strip(),
                votos=_to_int(c.get("vap") or c.get("votos") or c.get("vv")),
                pct_validos=_to_float(c.get("pvap") or c.get("pct_validos") or c.get("pvv")),
            ))
        return out

    candidatos = _parse_cand_list(raiz.get("cand") or raiz.get("candidatos"))

    # Breakdown por município. TSE historicamente usa `abr[].mu[]` ou `mu[]`.
    # Cada município tem cand[] próprio. Se o TSE mudar o formato, esta parte
    # simplesmente devolve [] e não quebra nada.
    municipios: list[ParsedMunicipio] = []
    fontes_mun = []
    for chave in ("abr", "mu", "municipios"):
        val = raiz.get(chave)
        if isinstance(val, list):
            for item in val:
                if isinstance(item, dict) and item.get("mu"):
                    fontes_mun.extend(item["mu"])
                elif isinstance(item, dict):
                    fontes_mun.append(item)
    for m in fontes_mun:
        if not isinstance(m, dict):
            continue
        cod_ibge = str(m.get("cdi") or m.get("cod_ibge") or m.get("codIbge") or "")
        if not cod_ibge:
            continue
        cands_m = _parse_cand_list(m.get("cand") or m.get("candidatos"))
        if cands_m:
            municipios.append(ParsedMunicipio(
                cod_ibge=cod_ibge,
                nome=(m.get("nm") or m.get("nome") or "").strip(),
                candidatos=cands_m,
            ))

    return ParsedSnapshot(totais=tot, candidatos=candidatos, municipios=municipios)
