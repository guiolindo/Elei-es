"""Validação retrospectiva da estimativa do 2T com boletins de urna reais.

    python scripts/validacao_2t/backtest.py DADOS 2022 [--ordem recebido|encerramento]

DADOS = pasta com {ano}_1t.csv e {ano}_2t.csv (baixar_bu.py).

Reconstrução: as seções entram na ordem de chegada. Em cada instante o
motor recebe só as seções já chegadas, somadas por estrato (o que o TSE
publica), mais o 1T do mesmo estrato como base. Total de seções e
eleitorado apto de cada estrato entram desde o início (o TSE publica com
0% apurado). O resultado final só é usado para pontuar.

Ordem: 2022 tem DT_BU_RECEBIDO (horário de Brasília em que o TSE recebeu o
boletim) = ordem real de chegada. 2018 não tem; usa DT_ENCERRAMENTO
(hora local em que a urna fechou) convertido para Brasília: APROXIMAÇÃO.
Em 2022 dá pra comparar as duas ordens e medir o tamanho dessa
aproximação (--ordem encerramento).

Presidente: estratificado por UF (+ exterior). Governador: estrato único
por UF com 2º turno. A = candidato com mais votos no 1T entre os dois
finalistas.
"""
import csv, json, os, sys
from datetime import datetime, timedelta
import numpy as np
AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(AQUI, "..", ".."))
from math_engine import projecao as P

# Diferença para Brasília (sem horário de verão nos 2ºs turnos de 2018 e 2022).
FUSO = {"AC": -2, "AM": -1, "RO": -1, "RR": -1, "MT": -1, "MS": -1}
CHECKPOINTS = list(range(10, 100, 5))
PASSO_SNAPSHOT = 0.5   # % das seções entre publicações simuladas
NAO_CANDIDATO = {"95", "96", "97"}


def ler(caminho, cargo):
    out = []
    with open(caminho) as f:
        for r in csv.DictReader(f):
            if r["cargo"] != cargo:
                continue
            r["votos"] = json.loads(r["votos_json"])
            r["aptos"] = int(r["aptos"]); r["comparecimento"] = int(r["comparecimento"])
            out.append(r)
    return out


def instante(r, ordem):
    txt = r[ordem]
    if not txt or txt.startswith("#"):
        return None
    t = datetime.strptime(txt, "%d/%m/%Y %H:%M:%S")
    if ordem == "encerramento":
        t += timedelta(hours=FUSO.get(r["uf"], 0))
    return t


def finalistas(sec2):
    tot = {}
    for r in sec2:
        for nr, v in r["votos"].items():
            if nr not in NAO_CANDIDATO:
                tot[nr] = tot.get(nr, 0) + v
    return [nr for nr, _ in sorted(tot.items(), key=lambda x: -x[1])[:2]]


def avaliar(sec1, sec2, estrato_de, ordem):
    """Uma disputa. estrato_de(r) -> nome do estrato."""
    a_nr, b_nr = finalistas(sec2)
    v1 = {}
    for r in sec1:
        g = estrato_de(r); d = v1.setdefault(g, [0, 0])
        d[0] += r["votos"].get(a_nr, 0); d[1] += r["votos"].get(b_nr, 0)
    if sum(x[0] for x in v1.values()) < sum(x[1] for x in v1.values()):
        a_nr, b_nr = b_nr, a_nr  # A = quem teve mais votos no 1T
        v1 = {g: [d[1], d[0]] for g, d in v1.items()}
    prior = {g: d[0] / (d[0] + d[1]) for g, d in v1.items() if d[0] + d[1] > 0}
    estratos = sorted({estrato_de(r) for r in sec2})
    gi = {g: i for i, g in enumerate(estratos)}
    regs = [(instante(r, ordem), gi[estrato_de(r)], r["aptos"],
             r["votos"].get(a_nr, 0), r["votos"].get(b_nr, 0)) for r in sec2]
    sem_hora = sum(1 for x in regs if x[0] is None)
    fim = max(x[0] for x in regs if x[0] is not None)
    regs = [(x[0] or fim, *x[1:]) for x in regs]   # sem horário: entra por último
    regs.sort(key=lambda x: x[0])
    n = len(regs); G = len(estratos)
    E_tot = np.zeros(G); S_tot = np.zeros(G); A_tot = np.zeros(G); V_tot = np.zeros(G)
    for _, g, apt, a, b in regs:
        E_tot[g] += apt; S_tot[g] += 1; A_tot[g] += a; V_tot[g] += a + b
    verdade = A_tot.sum() / V_tot.sum()
    # Publicações a cada PASSO_SNAPSHOT % das seções
    cortes = sorted({min(n, int(np.ceil(n * p / 100))) for p in np.arange(PASSO_SNAPSHOT, 100, PASSO_SNAPSHOT)})
    snaps = []; E = np.zeros(G); S = np.zeros(G); A = np.zeros(G); V = np.zeros(G); k = 0
    for c in cortes:
        while k < c:
            _, g, apt, a, b = regs[k]; E[g] += apt; S[g] += 1; A[g] += a; V[g] += a + b; k += 1
        snaps.append((c / n * 100, E.copy(), S.copy(), A.copy(), V.copy()))

    def estr(s):
        _, E, S, A, V = s
        return [P.Estrato(int(E_tot[g]), int(E[g]), int(V[g]), int(A[g]), int(S_tot[g]), int(S[g]),
                          prior.get(estratos[g])) for g in range(G)]

    linhas = []
    for cp in CHECKPOINTS:
        j = next(i for i, s in enumerate(snaps) if s[0] >= cp)
        agora = estr(snaps[j])
        # "antes" como no servidor: por estrato, o último snapshot anterior
        # com 0 < eleitorado apurado <= 60% do atual.
        antes, achou = [], False
        for g in range(G):
            alvo = 0.6 * snaps[j][1][g]
            cand = [i for i in range(j) if 0 < snaps[i][1][g] <= alvo]
            if cand:
                antes.append(estr(snaps[cand[-1]])[g]); achou = True
            else:
                antes.append(agora[g])
        r = P.projetar_2t(agora, antes if achou else None)
        if r is None:
            continue
        _, E, S, A, V = snaps[j]
        # Comparecimento (válidos/apto) já apurado x o que faltava, por estrato
        rest = E_tot - E
        m = (E > 0) & (rest > 0)
        tc = np.where(m, V / np.maximum(E, 1), 0); tr = np.where(m, (V_tot - V) / np.maximum(rest, 1), 0)
        peso = np.where(m, rest, 0)
        dif_comp = float((peso * (tc - tr)).sum() / peso.sum() * 100) if peso.sum() else 0.0
        validos_proj = r.votos_a + r.votos_b
        linhas.append(dict(
            cp=cp, fracao=r.fracao_apurada * 100, est=r.pct_a, real=verdade * 100,
            erro=r.pct_a - verdade * 100, lo=r.ic95_a[0], hi=r.ic95_a[1], sd=r.sd_pp,
            p=r.p_vitoria_a, exibir=r.exibir_probabilidade,
            erro_validos_rest=(validos_proj - V_tot.sum()) / max(V_tot.sum() - V.sum(), 1) * 100,
            dif_comp=dif_comp, placar=A.sum() / max(V.sum(), 1) * 100))
    return dict(a=a_nr, b=b_nr, verdade=verdade * 100, linhas=linhas, sem_hora=sem_hora, n=n)


def imprimir(nome, res):
    print(f"\n## {nome}: A={res['a']} × B={res['b']} | real A = {res['verdade']:.2f}% | {res['n']} seções"
          + (f" ({res['sem_hora']} sem horário, contadas por último)" if res["sem_hora"] else ""))
    print("  apur | placar A | estim. A | erro   | IC95          | cobre | chance A | válidos restantes | comparec. apurado−faltante")
    for l in res["linhas"]:
        ch = f"{l['p']*100:5.1f}%" if l["exibir"] else "  —  "
        print(f"  {l['cp']:3d}% | {l['placar']:6.2f}%  | {l['est']:6.2f}%  | {l['erro']:+.2f} | {l['lo']:5.2f}–{l['hi']:5.2f} | {'sim' if l['lo'] <= l['real'] <= l['hi'] else 'NÃO':5s} | {ch}   | {l['erro_validos_rest']:+6.2f}%           | {l['dif_comp']:+.2f} pp")


def main():
    pasta, ano = sys.argv[1], sys.argv[2]
    ordem = "recebido" if ano != "2018" else "encerramento"
    if "--ordem" in sys.argv:
        ordem = sys.argv[sys.argv.index("--ordem") + 1]
    print(f"# {ano}, ordem por {ordem}" + ("  (APROXIMAÇÃO da ordem real)" if ordem == "encerramento" else "  (ordem real de chegada)"))
    resultados = {}
    p1, p2 = ler(f"{pasta}/{ano}_1t.csv", "1"), ler(f"{pasta}/{ano}_2t.csv", "1")
    res = avaliar(p1, p2, lambda r: r["uf"], ordem)
    imprimir("Presidente", res); resultados["Presidente"] = res
    g1, g2 = ler(f"{pasta}/{ano}_1t.csv", "3"), ler(f"{pasta}/{ano}_2t.csv", "3")
    for uf in sorted({r["uf"] for r in g2}):
        res = avaliar([r for r in g1 if r["uf"] == uf], [r for r in g2 if r["uf"] == uf], lambda r: r["uf"], ordem)
        imprimir(f"Governador {uf}", res); resultados[f"Governador {uf}"] = res
    with open(f"{pasta}/backtest_{ano}_{ordem}.json", "w") as f:
        json.dump(resultados, f)


if __name__ == "__main__":
    main()
