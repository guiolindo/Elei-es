"""Baixa GeoJSON de municípios de todas as UFs e simplifica.

Roda uma vez para popular static/municipios/*.geojson. Cada arquivo
carregado só quando o usuário seleciona aquela UF no app.
Fonte: https://github.com/tbrugz/geodata-br (dados do IBGE).
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request

UF_IBGE = {
    "AC": 12, "AL": 27, "AM": 13, "AP": 16, "BA": 29, "CE": 23, "DF": 53,
    "ES": 32, "GO": 52, "MA": 21, "MG": 31, "MS": 50, "MT": 51, "PA": 15,
    "PB": 25, "PE": 26, "PI": 22, "PR": 41, "RJ": 33, "RN": 24, "RO": 11,
    "RR": 14, "RS": 43, "SC": 42, "SE": 28, "SP": 35, "TO": 17,
}


def dedup_ring(ring):
    out = [ring[0]]
    for p in ring[1:]:
        if p != out[-1]:
            out.append(p)
    return out if len(out) >= 4 else ring


def clean_coords(coords):
    if not coords:
        return coords
    if isinstance(coords[0], (int, float)):
        return [round(coords[0], 3), round(coords[1], 3)]
    if isinstance(coords[0][0], (int, float)):
        return dedup_ring([clean_coords(p) for p in coords])
    return [clean_coords(c) for c in coords]


def baixar_uf(sigla: str, ibge: int, destino: str) -> None:
    url = f"https://raw.githubusercontent.com/tbrugz/geodata-br/master/geojson/geojs-{ibge}-mun.json"
    caminho = f"{destino}/{sigla.lower()}.geojson"
    if os.path.exists(caminho):
        print(f"{sigla}: já existe, pulando")
        return
    print(f"{sigla}: baixando {url}")
    with urllib.request.urlopen(url) as r:
        data = json.loads(r.read())
    for f in data["features"]:
        f["geometry"]["coordinates"] = clean_coords(f["geometry"]["coordinates"])
        p = f["properties"]
        f["properties"] = {
            "id": p.get("id") or p.get("codarea"),
            "nome": p.get("name") or p.get("description") or "",
        }
    with open(caminho, "w") as f:
        json.dump(data, f, separators=(",", ":"))
    print(f"{sigla}: {os.path.getsize(caminho) // 1024} KB, {len(data['features'])} municípios")


def main():
    destino = "static/municipios"
    os.makedirs(destino, exist_ok=True)
    apenas = sys.argv[1:] if len(sys.argv) > 1 else list(UF_IBGE)
    for sigla in apenas:
        try:
            baixar_uf(sigla, UF_IBGE[sigla], destino)
        except Exception as e:
            print(f"{sigla}: erro {e}")


if __name__ == "__main__":
    main()
