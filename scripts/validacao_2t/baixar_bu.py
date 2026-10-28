"""Baixa os boletins de urna (BU) do TSE e guarda Presidente e Governador, por seção.

    python scripts/validacao_2t/baixar_bu.py 2022 DESTINO
    python scripts/validacao_2t/baixar_bu.py 2018 DESTINO

Saída: DESTINO/{ano}_{turno}t.csv com uma linha por seção e cargo:
cargo (1 Presidente, 3 Governador), uf, municipio, zona, secao, recebido (DT_BU_RECEBIDO; não existe em 2018),
encerramento (DT_ENCERRAMENTO, hora em que a urna fechou), aptos, comparecimento,
e uma coluna por número votado (inclui 95 branco e 96 nulo).
Um zip por vez, apagado depois de lido (os do 1º turno têm todos os cargos).
"""
import csv, io, json, os, subprocess, sys, urllib.request, zipfile

PACOTE = {"2022": "resultados-2022-boletim-de-urna", "2018": "resultados-2018-boletim-de-urna",
          "2026": "resultados-2026-boletim-de-urna"}


def urls(ano):
    api = f"https://dadosabertos.tse.jus.br/api/3/action/package_show?id={PACOTE[ano]}"
    j = json.load(urllib.request.urlopen(api, timeout=60))["result"]
    return [r["url"] for r in j["resources"] if r["url"].lower().endswith(".zip")]


def processar(zip_path, saida, campos_vistos):
    with zipfile.ZipFile(zip_path) as z:
        nome = next(n for n in z.namelist() if n.lower().endswith(".csv"))
        secoes = {}
        with z.open(nome) as f:
            leitor = csv.DictReader(io.TextIOWrapper(f, encoding="latin1"), delimiter=";")
            for row in leitor:
                cargo = row.get("CD_CARGO_PERGUNTA")
                if cargo not in ("1", "3"):
                    continue
                uf = row.get("SG_UF") or row.get("SG_ UF")  # 2018: "SG_ UF"
                k = (cargo, uf, row["CD_MUNICIPIO"], row["NR_ZONA"], row["NR_SECAO"])
                s = secoes.get(k)
                if s is None:
                    s = secoes[k] = {"recebido": row.get("DT_BU_RECEBIDO", ""),
                                     "encerramento": row.get("DT_ENCERRAMENTO", ""),
                                     "abertura": row.get("DT_ABERTURA", ""),
                                     "emissao": row.get("DT_EMISSAO_BU", ""),
                                     "tipo_urna": row.get("DS_TIPO_URNA", ""),
                                     "agregadas": row.get("DS_SECOES_AGREGADAS", ""),
                                     "sem_biometria": row.get("QT_ELEI_BIOM_SEM_HABILITACAO", ""),
                                     "aptos": int(row["QT_APTOS"]),
                                     "comparecimento": int(row["QT_COMPARECIMENTO"]),
                                     "votos": {}}
                nr = row["NR_VOTAVEL"]
                s["votos"][nr] = s["votos"].get(nr, 0) + int(row["QT_VOTOS"])
                campos_vistos.add(nr)
    novo = not os.path.exists(saida)
    with open(saida, "a", newline="") as out:
        w = csv.writer(out)
        if novo:
            w.writerow(["cargo", "uf", "municipio", "zona", "secao", "recebido", "encerramento", "aptos", "comparecimento", "votos_json",
                        "abertura", "emissao", "tipo_urna", "agregadas", "sem_biometria"])
        for (cargo, uf, mun, zona, sec), s in secoes.items():
            w.writerow([cargo, uf, mun, zona, sec, s["recebido"], s["encerramento"], s["aptos"], s["comparecimento"],
                        json.dumps(s["votos"], separators=(",", ":")),
                        s["abertura"], s["emissao"], s["tipo_urna"], s["agregadas"], s["sem_biometria"]])
    return len(secoes)


def main():
    ano, destino = sys.argv[1], sys.argv[2]
    os.makedirs(destino, exist_ok=True)
    feitos_path = os.path.join(destino, f"{ano}_feitos.txt")
    feitos = set(open(feitos_path).read().split()) if os.path.exists(feitos_path) else set()
    vistos = set()
    for url in urls(ano):
        base = url.rsplit("/", 1)[1]
        if base in feitos:
            continue
        turno = "1t" if "_1t_" in base.lower() else "2t"
        tmp = os.path.join(destino, base)
        subprocess.run(["curl", "-s", "-m", "1800", "--retry", "4", "-o", tmp, url], check=True)
        n = processar(tmp, os.path.join(destino, f"{ano}_{turno}.csv"), vistos)
        os.remove(tmp)
        with open(feitos_path, "a") as f:
            f.write(base + "\n")
        print(f"{base}: {n} seções", flush=True)


if __name__ == "__main__":
    main()
