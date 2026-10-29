"""Monta a lista de seções para o verificar_integridade.py.

    python scripts/validacao_2t/amostra_integridade.py PASTA SAIDA.csv [N_SORTEIO]

Junta: (1) sorteio uniforme de N seções (padrão 10.000, semente fixa, para dar
para refazer); (2) TODAS as urnas que fecharam depois das 18h de Brasília;
(3) as seções que os testes estatísticos apontaram: 100% num candidato,
virada ≥ 10 p.p. além da zona, salto ≥ 20 p.p. de eleitor sem biometria,
comparecimento ≥ 98% e comparecimento 15 p.p. acima da zona.
"""
import csv, random, sys
from datetime import timedelta

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from auditoria_bu import hora, finalistas  # noqa: E402
from auditoria_extra import fusos, ler, residuos  # noqa: E402


def montar(pasta, saida, n=10_000):
    s1 = ler(f"{pasta}/2026_1t.csv"); s2 = ler(f"{pasta}/2026_2t.csv")
    (a, b), _ = finalistas(s2)
    off = fusos(s2)
    motivos = {}
    add = lambda k, m: motivos.setdefault(k, []).append(m)

    for k in random.Random(20261025).sample(sorted(s2), min(n, len(s2))):
        add(k, "sorteio")
    for k, r in s2.items():
        e = hora(r["encerramento"])
        if e and (e + timedelta(hours=off.get(k[:2], 0))).hour >= 18:
            add(k, "fechou depois das 18h")
        v = r["votos"].get(a, 0) + r["votos"].get(b, 0)
        if v >= 20 and max(r["votos"].get(a, 0), r["votos"].get(b, 0)) == v:
            add(k, "100% num candidato")
        if r["aptos"] >= 50 and r["comparecimento"] / r["aptos"] >= 0.98:
            add(k, "comparecimento ≥ 98%")

    ds, dc, dsb = {}, {}, {}
    for k, r2 in s2.items():
        r1 = s1.get(k)
        if not r1 or r1["aptos"] < 50:
            continue
        v1 = r1["votos"].get(a, 0) + r1["votos"].get(b, 0); v2 = r2["votos"].get(a, 0) + r2["votos"].get(b, 0)
        if v1 < 30 or v2 < 30:
            continue
        ds[k] = r2["votos"].get(a, 0) / v2 - r1["votos"].get(a, 0) / v1
        dc[k] = r2["comparecimento"] / r2["aptos"] - r1["comparecimento"] / r1["aptos"]
        if r1["sb"] is not None and r2["sb"] is not None:
            dsb[k] = r2["sb"] / max(r2["comparecimento"], 1) - r1["sb"] / max(r1["comparecimento"], 1)
    for k, v in residuos(ds).items():
        if abs(v) >= 0.10:
            add(k, "virada ≥ 10pp além da zona")
    for k, v in residuos(dc).items():
        if v >= 0.15:
            add(k, "comparecimento 15pp acima da zona")
    for k, v in residuos(dsb).items():
        if v >= 0.20:
            add(k, "salto ≥ 20pp sem biometria")

    with open(saida, "w", newline="") as f:
        w = csv.writer(f); w.writerow(["uf", "municipio", "zona", "secao", "motivo", "fuso"])
        for k, ms in sorted(motivos.items()):
            w.writerow([k[0], k[1], k[2], k[3], " | ".join(ms), off.get(k[:2], 0)])
    cont = {}
    for ms in motivos.values():
        for m in ms:
            cont[m] = cont.get(m, 0) + 1
    print(f"{len(motivos):,} seções".replace(",", "."), cont)


if __name__ == "__main__":
    montar(sys.argv[1], sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 10_000)
