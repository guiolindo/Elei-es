"""Diagnóstico do ponto 2 com dados reais: a virada 1T→2T medida nas seções
já apuradas vale para as que faltam?

    python scripts/validacao_2t/diag_swing.py DADOS 2022 30

Para cada UF, no instante em que X% das seções do país chegaram:
  virada apurada  = share de A nas seções já apuradas (2T) − base 1T da UF
  virada faltante = share de A nas seções que faltam (2T) − base 1T da UF
  δ do motor      = média nacional da virada apurada (pesos = válidos)
"""
import os, sys
import numpy as np
AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)
import backtest as B

REG = {"S": "PR RS SC", "SE": "ES MG RJ SP", "CO": "DF GO MS MT", "NE": "AL BA CE MA PB PE PI RN SE",
       "N": "AC AM AP PA RO RR TO", "EX": "ZZ"}
REG_DE = {uf: g for g, s in REG.items() for uf in s.split()}


def main():
    pasta, ano, pct = sys.argv[1], sys.argv[2], float(sys.argv[3])
    ordem = "recebido" if ano != "2018" else "encerramento"
    if "--ordem" in sys.argv:
        ordem = sys.argv[sys.argv.index("--ordem") + 1]
    s1, s2 = B.ler(f"{pasta}/{ano}_1t.csv", "1"), B.ler(f"{pasta}/{ano}_2t.csv", "1")
    a, b = B.finalistas(s2)
    t1 = {}
    for r in s1:
        d = t1.setdefault(r["uf"], [0, 0]); d[0] += r["votos"].get(a, 0); d[1] += r["votos"].get(b, 0)
    if sum(d[0] for d in t1.values()) < sum(d[1] for d in t1.values()):
        a, b = b, a; t1 = {u: [d[1], d[0]] for u, d in t1.items()}
    prior = {u: d[0] / sum(d) for u, d in t1.items()}
    regs = sorted(((B.instante(r, ordem), r) for r in s2), key=lambda x: (x[0] is None, x[0] or 0))
    corte = int(len(regs) * pct / 100)
    ac, rest = {}, {}
    for i, (_, r) in enumerate(regs):
        d = (ac if i < corte else rest).setdefault(r["uf"], [0, 0])
        d[0] += r["votos"].get(a, 0); d[1] += r["votos"].get(a, 0) + r["votos"].get(b, 0)
    num = sum(ac[u][1] * (ac[u][0] / ac[u][1] - prior[u]) for u in ac if ac[u][1])
    delta = num / sum(ac[u][1] for u in ac if ac[u][1])
    print(f"{ano}, {pct:.0f}% das seções ({ordem}); A={a}. δ nacional medido = {delta*100:+.2f} pp")
    print(" região | válidos faltando | virada apurada | virada faltante | faltante − δ")
    por_reg = {}
    for u in rest:
        g = REG_DE.get(u, "?"); x = por_reg.setdefault(g, [0, 0, 0, 0])
        if ac.get(u, [0, 0])[1]:
            x[0] += ac[u][1] * (ac[u][0] / ac[u][1] - prior[u]); x[1] += ac[u][1]
        x[2] += rest[u][1] * (rest[u][0] / rest[u][1] - prior[u]); x[3] += rest[u][1]
    tot_rest = sum(x[3] for x in por_reg.values())
    for g in ("S", "SE", "CO", "NE", "N", "EX"):
        if g in por_reg:
            x = por_reg[g]
            va = x[0] / x[1] * 100 if x[1] else float("nan"); vf = x[2] / x[3] * 100
            print(f" {g:6s} | {x[3]/tot_rest*100:15.1f}% | {va:+13.2f} | {vf:+14.2f} | {vf - delta*100:+.2f}")
    vf_tot = sum(x[2] for x in por_reg.values()) / tot_rest
    print(f" Total faltante: virada {vf_tot*100:+.2f} pp, motor supõe {delta*100:+.2f} pp → diferença {(vf_tot-delta)*100:+.2f} pp")


if __name__ == "__main__":
    main()
