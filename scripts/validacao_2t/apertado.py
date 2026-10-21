"""Apuração real de 2022 (ordem real de chegada das urnas), com votos
deslocados para o resultado final ficar em ~50,05% × 49,95%. Roda o motor
(eleito, viradas) e a estimativa do site como no dia."""
import sys, copy, random
import os
AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(AQUI, "..", "..")); sys.path.insert(0, AQUI)
import backtest as B
from math_engine.engine import CandidatoResumo, TotaisResumo, avaliar_apuracao, detectar_viradas
# python scripts/validacao_2t/apertado.py DADOS 0.5005   (DADOS = pasta do baixar_bu.py)
D = sys.argv[1]
alvo_b = float(sys.argv[2]) if len(sys.argv) > 2 else 0.5005   # fração final do 22
s1, s2 = B.ler(f"{D}/2022_1t.csv", "1"), B.ler(f"{D}/2022_2t.csv", "1")
L, Bo = "13", "22"
tl = sum(r["votos"].get(L, 0) for r in s2); tb = sum(r["votos"].get(Bo, 0) for r in s2)
# fração dos votos de Lula transferida em cada seção para chegar no alvo
t = (alvo_b * (tl + tb) - tb) / tl
rnd = random.Random(1)
s2m = []
for r in s2:
    r = copy.deepcopy(r); l = r["votos"].get(L, 0)
    mv = int(l * t + rnd.random())
    r["votos"][L] = l - mv; r["votos"][Bo] = r["votos"].get(Bo, 0) + mv
    s2m.append(r)
tl = sum(r["votos"].get(L, 0) for r in s2m); tb = sum(r["votos"].get(Bo, 0) for r in s2m)
print(f"final: 22 = {tb/(tl+tb)*100:.3f}%  13 = {tl/(tl+tb)*100:.3f}%  diferença {tb-tl:,} votos".replace(",", "."))
# --- motor: aviso de eleito e viradas, a cada 0,5% (ritmo de publicação)
ordem = sorted(((B.instante(r, "recebido"), r) for r in s2m if B.instante(r, "recebido")), key=lambda x: x[0])
n = len(ordem); apt_tot = sum(r["aptos"] for _, r in ordem)
va = vb = apt = val = 0; ant = None; viradas = []; eleito = None; k = 0
cortes = sorted({max(1, int(n * p / 1000)) for p in range(5, 1001, 5)}) + [n]
for c in cortes:
    while k < c:
        t_, r = ordem[k]; va += r["votos"].get(L, 0); vb += r["votos"].get(Bo, 0); apt += r["aptos"]; k += 1
    cands = [CandidatoResumo(L, va), CandidatoResumo(Bo, vb)]
    tot = TotaisResumo(n, k, apt_tot, apt, va + vb)
    if ant:
        for ev in detectar_viradas(cands, ant): viradas.append((k / n * 100, t_, ev["sq_candidato_a"]))
    ant = cands
    if not eleito:
        evs = [e for e in avaliar_apuracao(cands, tot, cod_cargo=1, turno=2) if e["tipo"] == "ELEITO_2T"]
        if evs: eleito = (k / n * 100, t_, evs[0]["sq_candidato_a"])
for p, t_, sq in viradas: print(f"virada: {sq} passa à frente com {p:.1f}% apurado ({t_:%H:%M})")
print("eleito:", f"{eleito[2]} com {eleito[0]:.2f}% apurado às {eleito[1]:%H:%M}" if eleito else "não declarado")
# --- estimativa do site, momento a momento
res = B.avaliar(s1, s2m, lambda r: r["uf"], "recebido")
print(f"\nestimativa (A = {res['a']}, real {res['verdade']:.2f}%):")
for l in res["linhas"]:
    ch = f"{l['p']*100:.0f}%" if l["exibir"] else "—"
    print(f"  {l['cp']:3d}%: placar A {l['placar']:.2f}% | estimativa A {l['est']:.2f}% ±{(l['hi']-l['lo'])/2:.2f} | chance A {ch} | real dentro da margem: {'sim' if l['lo']<=l['real']<=l['hi'] else 'NÃO'}")
