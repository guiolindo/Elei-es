"""Parser dos JSONs de resultado do TSE.

O formato oficial usa nomes abreviados. Este módulo isola essa dependência —
se o TSE mudar o schema, só este arquivo muda. Todos os campos que não vêm
no JSON são tratados como 0.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
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


# TSE devolve horários no fuso de Brasília (sem offset no JSON). Marcamos
# com BRT explicitamente pra que o conversor pra UTC (feito pelo Postgres
# ao salvar em TIMESTAMPTZ) resulte no instante correto.
_BRT = timezone(timedelta(hours=-3))


def _parse_dt(raw: str | None) -> datetime | None:
    """Parse de uma string de data+hora do TSE em datetime timezone-aware (BRT).

    Formatos aceitos: '12/10/2026 20:35:12', '2026-10-12T20:35:12',
    '2026-10-12 20:35:12'. Pra variante ISO já com offset ('...+00:00'),
    respeita o fuso recebido; senão assume BRT.
    """
    if not raw:
        return None
    for fmt in ("%d/%m/%Y %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            dt = datetime.strptime(raw, fmt)
            return dt.replace(tzinfo=_BRT)
        except ValueError:
            continue
    # Último fallback: fromisoformat aceita ISO com offset (ex.: "+00:00")
    try:
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=_BRT)
        return dt
    except ValueError:
        return None


def _parse_dt_dg_hg(dg: str | None, hg: str | None) -> datetime | None:
    """Combina `dg` (dd/mm/aaaa) e `hg` (HH:MM:SS) que vêm separados nos JSONs
    reais do TSE (ex.: dg='02/10/2026', hg='20:13:54'). Fuso: BRT.
    """
    if not dg:
        return None
    if hg:
        return _parse_dt(f"{dg} {hg}")
    # Só a data — meio-noite BRT como aproximação (melhor que None)
    return _parse_dt(f"{dg} 00:00:00")


def parse_snapshot(payload: dict) -> ParsedSnapshot:
    """Converte payload JSON do TSE em objetos tipados.

    Schema oficial 2026 (confirmado em 30/09/2026):
      raiz.s = {ts: total_secoes, st: totalizadas, sa: aptas, sni: não iniciadas}
      raiz.e = {te: total_eleitorado, est: eleitorado_totalizado, c: comparecimento,
                a: abstencoes}
      raiz.v = {vv: votos_validos, vb: brancos, vn: nulos, vnom: nominais}
      raiz.carg[0].agr[N] = agrupamentos (partido/federacao):
        .par[M] = partidos:
          .cand[K] = candidatos com sqcand, n, nm, nmu, vap, pvap
      raiz.abr[] = breakdown por UF (opcional, quando abrangência BR)
                   ou raiz.mu[] pra municípios (quando abrangência UF)

    Também aceita chaves em snake_case (fixtures/modo simulação legado).

    Bug histórico: parser anterior lia `raiz.s` como inteiro direto — mas
    é um DICT. Resultado: qt_secoes_total sempre 0 em prod.
    """
    # Totais moram no PAYLOAD ROOT, não em carg[0]. carg[0] tem só a
    # estrutura de candidatos (agr → par → cand).
    root = payload

    s = root.get("s") if isinstance(root.get("s"), dict) else {}
    e = root.get("e") if isinstance(root.get("e"), dict) else {}
    v = root.get("v") if isinstance(root.get("v"), dict) else {}

    tot = ParsedTotais(
        # Total de seções da abrangência (ex.: 499.248 no BR).
        # Fallback pra chave legada `s` direto (fixtures antigas).
        qt_secoes_total=_to_int(s.get("ts") or root.get("qt_secoes_total")),
        qt_secoes_totalizadas=_to_int(s.get("st") or root.get("qt_secoes_totalizadas")),
        qt_eleitorado_apto=_to_int(e.get("te") or root.get("qt_eleitorado_apto")),
        qt_eleitorado_apto_totalizadas=_to_int(
            e.get("est") or root.get("qt_eleitorado_apto_totalizadas")
        ),
        qt_comparecimento=_to_int(e.get("c") or root.get("qt_comparecimento")),
        qt_abstencoes=_to_int(e.get("a") or root.get("qt_abstencoes")),
        qt_votos_validos=_to_int(v.get("vv") or root.get("qt_votos_validos")),
        qt_votos_brancos=_to_int(v.get("vb") or root.get("qt_votos_brancos")),
        qt_votos_nulos=_to_int(v.get("vn") or root.get("qt_votos_nulos")),
        # TSE 2026: dg (data) e hg (hora) vêm SEPARADOS. Fixtures legadas
        # usam `gerado_em` já formatado em uma string única.
        gerado_em=(
            _parse_dt_dg_hg(root.get("dg"), root.get("hg"))
            or _parse_dt(root.get("gerado_em"))
        ),
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
                # nmu = nome_urna, nm = nome completo — preferir nmu (mais curto)
                nome_urna=(c.get("nmu") or c.get("nm") or c.get("nome_urna") or "").strip(),
                votos=_to_int(c.get("vap") or c.get("votos") or c.get("vv")),
                pct_validos=_to_float(c.get("pvap") or c.get("pct_validos") or c.get("pvv")),
            ))
        return out

    # Achata carg[0].agr[].par[].cand[] pra lista única de candidatos.
    # `agr` são AGRUPAMENTOS (federação ou partido isolado); dentro tem
    # par[] (partidos membros) e cada partido tem cand[].
    candidatos: list[ParsedCandidato] = []
    if "carg" in root and isinstance(root["carg"], list) and root["carg"]:
        for cargo in root["carg"]:
            for agr in cargo.get("agr", []) or []:
                for par in agr.get("par", []) or []:
                    candidatos.extend(_parse_cand_list(par.get("cand")))
    # Fallback pra fixtures antigas com cand[] direto no root ou carg[0]
    if not candidatos:
        raiz_alt = root["carg"][0] if root.get("carg") else root
        candidatos = _parse_cand_list(raiz_alt.get("cand") or raiz_alt.get("candidatos"))

    # Breakdown por município. TSE 2026: raiz.mu[] (quando abrangencia=UF)
    # ou raiz.abr[].mu[] (quando abrangencia=BR). Cada município tem sua
    # própria estrutura de agr[].par[].cand[].
    municipios: list[ParsedMunicipio] = []
    fontes_mun = []
    for chave in ("mu", "municipios"):
        val = root.get(chave)
        if isinstance(val, list):
            fontes_mun.extend(val)
    for item in root.get("abr", []) or []:
        if isinstance(item, dict) and item.get("mu"):
            fontes_mun.extend(item["mu"])
    for m in fontes_mun:
        if not isinstance(m, dict):
            continue
        cod_ibge = str(m.get("cdi") or m.get("cod_ibge") or m.get("codIbge") or "")
        if not cod_ibge:
            continue
        # Achata cand do município (mesmo padrão do raiz)
        cands_m: list[ParsedCandidato] = []
        for agr in m.get("agr", []) or []:
            for par in agr.get("par", []) or []:
                cands_m.extend(_parse_cand_list(par.get("cand")))
        if not cands_m:
            cands_m = _parse_cand_list(m.get("cand") or m.get("candidatos"))
        if cands_m:
            municipios.append(ParsedMunicipio(
                cod_ibge=cod_ibge,
                nome=(m.get("nm") or m.get("nome") or "").strip(),
                candidatos=cands_m,
            ))

    return ParsedSnapshot(totais=tot, candidatos=candidatos, municipios=municipios)
