"""Auditoria dos boletins de urna (BU) do 2º turno para Presidente.

    python scripts/validacao_2t/auditoria_bu.py PASTA 2026 [--ref 2022]

PASTA tem {ano}_1t.csv e {ano}_2t.csv (saída do baixar_bu.py). Com --ref, a
mesma auditoria roda numa eleição anterior (ex.: 2022), para separar o que é
anomalia do que é o padrão normal de qualquer eleição.

Verificações (só Presidente, cargo 1):
  1. Soma: total de cada candidato, brancos, nulos e comparecimento somados
     seção por seção, para comparar com o resultado oficial.
  2. Consistência interna: votos > comparecimento, comparecimento > aptos.
  3. Horários: urnas encerradas depois das 17h (horário de Brasília) por UF e
     faixa; votos que entraram depois das 17h só existem em urnas que
     ficaram abertas depois disso. Abertura antes das 7h ou BU emitido antes
     do encerramento.
  4. Seções com 100% (ou ≥ 95%) dos votos válidos num só candidato.
  5. Mudança brusca em relação ao 1º turno na MESMA seção: comparecimento e
     participação de cada candidato (Flávio/Lula entre os dois, no 1T contra
     o 2T). Distribuição, desvios extremos (|z| alto) e se os extremos
     pendem para um lado.
  6. Seções novas no 2T (sem par no 1T) e urnas de contingência / voto em
     cédula / seções agregadas.
Saída: relatório em texto (stdout) e CSV das seções sinalizadas.
"""
import csv, json, math, statistics as st, sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta

# Os BUs trazem o horário LOCAL da urna. Em vez de manter uma tabela de
# fusos por município (o AM tem dois), o fuso de cada município é deduzido
# dos próprios dados: as urnas abrem às 8h de Brasília, então a mediana da
# hora de abertura no município diz quantas horas somar.
_OFFSET = {}


def calibrar_fusos(secoes):
    por_mun = defaultdict(list)
    for k, r in secoes.items():
        ab = hora(r.get("abertura", ""))
        if ab:
            por_mun[(k[0], k[1])].append(ab.hour + ab.minute / 60)
    for m, hs in por_mun.items():
        _OFFSET[m] = round(8 - st.median(hs))


def hora(s):
    if not s or s.startswith("#"):
        return None
    for f in ("%Y-%m-%d %H:%M:%S", "%d/%m/%Y %H:%M:%S"):
        try:
            return datetime.strptime(s, f)
        except ValueError:
            pass
    return None


def para_brasilia(dt, uf, mun):
    if dt is None:
        return None
    return dt + timedelta(hours=_OFFSET.get((uf, mun), 0))


def ler(caminho):
    out = {}
    with open(caminho) as f:
        for r in csv.DictReader(f):
            if r["cargo"] != "1":
                continue
            r["votos"] = {k: int(v) for k, v in json.loads(r["votos_json"]).items()}
            r["aptos"] = int(r["aptos"]); r["comparecimento"] = int(r["comparecimento"])
            out[(r["uf"], r["municipio"], r["zona"], r["secao"])] = r
    return out


def finalistas(sec2):
    tot = Counter()
    for r in sec2.values():
        for k, v in r["votos"].items():
            if k not in ("95", "96"):
                tot[k] += v
    return [k for k, _ in tot.most_common(2)], tot


def auditar(pasta, ano, saida_csv):
    s1 = ler(f"{pasta}/{ano}_1t.csv")
    s2 = ler(f"{pasta}/{ano}_2t.csv")
    (a, b), tot = finalistas(s2)
    _OFFSET.clear(); calibrar_fusos(s2)
    P_fusos = Counter(_OFFSET.values())
    P = lambda *x: print(*x, flush=True)
    P(f"\n================ {ano} · 2º turno · Presidente ================")
    P(f"Seções no 2T: {len(s2):,}   no 1T: {len(s1):,}".replace(",", "."))
    P(f"Fusos deduzidos (horas somadas → nº de municípios): {dict(P_fusos)}")
    sinal = []

    # 1. Soma
    br = sum(r["votos"].get("95", 0) for r in s2.values())
    nu = sum(r["votos"].get("96", 0) for r in s2.values())
    comp = sum(r["comparecimento"] for r in s2.values())
    aptos = sum(r["aptos"] for r in s2.values())
    val = tot[a] + tot[b]
    P("\n1) Soma dos boletins")
    for c in (a, b):
        P(f"   {c}: {tot[c]:,} ({tot[c]/val*100:.2f}% dos válidos)".replace(",", "."))
    P(f"   brancos {br:,} · nulos {nu:,} · comparecimento {comp:,} de {aptos:,} aptos".replace(",", "."))

    # 2. Consistência interna
    P("\n2) Consistência de cada boletim")
    n_votos_maior = n_comp_maior = 0
    for k, r in s2.items():
        soma = sum(r["votos"].values())
        if soma > r["comparecimento"]:
            n_votos_maior += 1; sinal.append((k, "votos > comparecimento", soma - r["comparecimento"]))
        if r["comparecimento"] > r["aptos"]:
            n_comp_maior += 1; sinal.append((k, "comparecimento > aptos", r["comparecimento"] - r["aptos"]))
    P(f"   votos acima do comparecimento: {n_votos_maior} seções")
    P(f"   comparecimento acima dos aptos: {n_comp_maior} seções (pode ser legítimo: eleitor em trânsito, mesário de outra seção)")

    # 3. Horários
    P("\n3) Horários (convertidos para Brasília)")
    faixas = Counter(); por_uf_tarde = Counter(); abertura_cedo = emissao_antes = sem_hora = 0
    votos_tarde = Counter()
    for k, r in s2.items():
        uf, mun = k[0], k[1]
        enc = para_brasilia(hora(r["encerramento"]), uf, mun)
        ab = para_brasilia(hora(r.get("abertura", "")), uf, mun)
        em = para_brasilia(hora(r.get("emissao", "")), uf, mun)
        if enc is None:
            sem_hora += 1; continue
        m = enc.hour * 60 + enc.minute
        f = ("até 17:00" if m <= 17 * 60 else "17:00–17:30" if m <= 17 * 60 + 30 else "17:30–18:00" if m <= 18 * 60
             else "18:00–19:00" if m <= 19 * 60 else "depois das 19:00")
        faixas[f] += 1
        if m > 17 * 60:
            por_uf_tarde[uf] += 1
            for c in (a, b, "95", "96"):
                votos_tarde[c] += r["votos"].get(c, 0)
        if m > 19 * 60 + 15:
            sinal.append((k, "encerrou depois das 19:15", enc.strftime("%H:%M")))
        if ab and ab.hour * 60 + ab.minute < 7 * 60 + 30:
            abertura_cedo += 1; sinal.append((k, "abriu antes das 7h30 (Brasília)", ab.strftime("%H:%M")))
        if em and em < enc - timedelta(minutes=1):
            emissao_antes += 1; sinal.append((k, "BU emitido antes do encerramento", em.strftime("%H:%M")))
    for f in ("até 17:00", "17:00–17:30", "17:30–18:00", "18:00–19:00", "depois das 19:00"):
        P(f"   encerradas {f:16s}: {faixas[f]:,}".replace(",", "."))
    P(f"   sem horário de encerramento: {sem_hora}")
    if sum(por_uf_tarde.values()):
        P("   UFs com mais urnas encerradas depois das 17h: " +
          ", ".join(f"{u} {n}" for u, n in por_uf_tarde.most_common(10)))
        vt = votos_tarde[a] + votos_tarde[b]
        if vt:
            P(f"   votos (inteiros) das urnas que fecharam depois das 17h: {a} {votos_tarde[a]:,} · {b} {votos_tarde[b]:,} "
              f"({votos_tarde[a]/vt*100:.1f}% × {votos_tarde[b]/vt*100:.1f}%)".replace(",", "."))
            P(f"   saldo dessas urnas: {abs(votos_tarde[a]-votos_tarde[b]):,} votos; diferença total da eleição: {abs(tot[a]-tot[b]):,}".replace(",", "."))
            P("   (é o voto TODO dessas urnas, não só o do horário extra: o BU não separa por hora)")
    P(f"   abertura antes das 7h30: {abertura_cedo} · BU emitido antes do encerramento: {emissao_antes}")

    # 4. Unanimidade
    P("\n4) Seções com votos válidos concentrados num candidato")
    for lim in (1.0, 0.95):
        cont = Counter()
        for k, r in s2.items():
            v = r["votos"].get(a, 0) + r["votos"].get(b, 0)
            if v >= 20:
                for c in (a, b):
                    if r["votos"].get(c, 0) / v >= lim:
                        cont[c] += 1
                        if lim == 1.0:
                            sinal.append((k, f"100% {c}", v))
        P(f"   ≥{lim*100:.0f}% (seções com 20+ válidos): {a} {cont[a]} · {b} {cont[b]}")

    # 5. Comparação com o 1T, mesma seção
    P("\n5) Mesma seção, 1º × 2º turno")
    d_comp, d_share, pares = [], [], []
    for k, r2 in s2.items():
        r1 = s1.get(k)
        if not r1 or r1["aptos"] < 50:
            continue
        v1 = r1["votos"].get(a, 0) + r1["votos"].get(b, 0)
        v2 = r2["votos"].get(a, 0) + r2["votos"].get(b, 0)
        if v1 < 20 or v2 < 20:
            continue
        dc = r2["comparecimento"] / r2["aptos"] - r1["comparecimento"] / r1["aptos"]
        ds = r2["votos"].get(a, 0) / v2 - r1["votos"].get(a, 0) / v1
        d_comp.append(dc); d_share.append(ds); pares.append((k, dc, ds))
    nov = len(s2) - len(pares)
    P(f"   seções comparadas: {len(pares):,} (fora: {nov:,} novas, pequenas ou sem par)".replace(",", "."))
    for nome, xs in (("comparecimento (p.p.)", d_comp), (f"participação de {a} entre os dois (p.p.)", d_share)):
        mu, sd = st.mean(xs), st.pstdev(xs)
        q = st.quantiles(xs, n=100)
        P(f"   Δ {nome}: média {mu*100:+.2f} · desvio {sd*100:.2f} · 1% {q[0]*100:+.1f} · 99% {q[-1]*100:+.1f}")
    mu_c, sd_c = st.mean(d_comp), st.pstdev(d_comp)
    mu_s, sd_s = st.mean(d_share), st.pstdev(d_share)
    ext_c = [p for p in pares if abs(p[1] - mu_c) > 5 * sd_c]
    ext_s = [p for p in pares if abs(p[2] - mu_s) > 5 * sd_s]
    lado = Counter("a" if p[2] > mu_s else "b" for p in ext_s)
    P(f"   desvio extremo (>5σ) no comparecimento: {len(ext_c)} seções")
    P(f"   desvio extremo (>5σ) na participação: {len(ext_s)} seções · para {a}: {lado['a']} · para {b}: {lado['b']}")
    for p in ext_c:
        sinal.append((p[0], "Δ comparecimento >5σ", f"{p[1]*100:+.1f}pp"))
    for p in ext_s:
        sinal.append((p[0], "Δ participação >5σ", f"{p[2]*100:+.1f}pp"))
    # comparecimento cresceu mais onde fechou tarde?
    tarde = {k for k, r in s2.items() if (e := para_brasilia(hora(r["encerramento"]), k[0], k[1])) and e.hour * 60 + e.minute > 17 * 60}
    dc_t = [p[1] for p in pares if p[0] in tarde]; dc_n = [p[1] for p in pares if p[0] not in tarde]
    if dc_t:
        P(f"   Δ comparecimento médio: urnas que fecharam depois das 17h {st.mean(dc_t)*100:+.2f}pp ({len(dc_t)}) × "
          f"demais {st.mean(dc_n)*100:+.2f}pp ({len(dc_n)})")
        ds_t = [p[2] for p in pares if p[0] in tarde]
        P(f"   Δ participação de {a} nessas urnas: {st.mean(ds_t)*100:+.2f}pp × demais {st.mean([p[2] for p in pares if p[0] not in tarde])*100:+.2f}pp")

    # 6. Tipos de urna
    P("\n6) Tipo de urna e seções agregadas")
    P("   " + " · ".join(f"{t or '?'}: {n:,}".replace(",", ".") for t, n in Counter(r.get("tipo_urna", "") for r in s2.values()).most_common()))
    agreg = sum(1 for r in s2.values() if r.get("agregadas") and not r["agregadas"].startswith("#"))
    P(f"   seções com agregadas: {agreg:,}".replace(",", "."))

    with open(saida_csv, "w", newline="") as f:
        w = csv.writer(f); w.writerow(["uf", "municipio", "zona", "secao", "motivo", "detalhe"])
        for k, m, d in sinal:
            w.writerow([*k, m, d])
    P(f"\nSeções sinalizadas: {len(sinal):,} → {saida_csv}".replace(",", "."))
    P("Sinalizada não quer dizer fraude: cada caso precisa ser comparado com o padrão da eleição de referência.")


if __name__ == "__main__":
    pasta, ano = sys.argv[1], sys.argv[2]
    auditar(pasta, ano, f"{pasta}/sinalizadas_{ano}.csv")
    if "--ref" in sys.argv:
        ref = sys.argv[sys.argv.index("--ref") + 1]
        auditar(pasta, ref, f"{pasta}/sinalizadas_{ref}.csv")
