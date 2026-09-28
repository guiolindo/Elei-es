#!/usr/bin/env python3
"""Baixa candidatos do TSE (com fingerprint de Chrome real) e sobe pro app.

Uso no Termux (Android):
    pkg install python
    pip install curl-cffi
    python importar_termux.py https://elei-es-production.up.railway.app

curl-cffi usa libcurl-impersonate, que mimica exatamente o handshake TLS
e as flags HTTP/2 do Chrome — engana o Akamai do TSE que bloqueia curl
padrão. Precisa rodar do celular (IP residencial BR).
"""
import json
import sys
import time

try:
    from curl_cffi import requests
except ImportError:
    sys.exit("Falta a lib. Rode: pip install curl-cffi")

APP = sys.argv[1] if len(sys.argv) > 1 else "https://elei-es-production.up.railway.app"
COD = 20322002026  # ID interno da eleição 2026 (visto na URL do site do TSE)
ANO = 2026
UFS = ["AC","AL","AM","AP","BA","CE","DF","ES","GO","MA","MG","MS","MT",
       "PA","PB","PE","PI","PR","RJ","RN","RO","RR","RS","SC","SE","SP","TO"]

# (cargo_codigo, nome, ufs)
CARGOS = [
    (1, "Presidente",        ["BR"]),
    (3, "Governador",        UFS),
    (5, "Senador",           UFS),
    (6, "Deputado Federal",  UFS),
    (7, "Deputado Estadual", UFS),
]

TSE = "https://divulgacandcontas.tse.jus.br/divulga/rest/v1/candidatura/listar"

ok = 0
fail = 0
total_cand = 0

for cargo, nome, ufs in CARGOS:
    for uf in ufs:
        url = f"{TSE}/{ANO}/{uf}/{COD}/{cargo}/candidatos"
        try:
            # impersonate="chrome" → TLS fingerprint idêntico ao Chrome 116
            r = requests.get(url, impersonate="chrome", timeout=20)
        except Exception as e:
            print(f"[erro] {nome} {uf}: {e}")
            fail += 1
            continue
        if r.status_code != 200:
            print(f"[--] {nome} {uf}: HTTP {r.status_code}")
            fail += 1
            continue
        try:
            data = r.json()
        except Exception:
            print(f"[--] {nome} {uf}: resposta não é JSON")
            fail += 1
            continue
        n_cands = len(data.get("candidatos") or [])
        if n_cands == 0:
            print(f"[--] {nome} {uf}: 0 candidatos")
            fail += 1
            continue
        # POST no app
        try:
            resp = requests.post(
                f"{APP}/api/admin/importar-candidatos",
                json={"cargo": cargo, "uf": uf, "json": data},
                timeout=30,
            )
            if resp.status_code == 200:
                res = resp.json()
                print(f"[OK] {nome} {uf}: {res.get('atualizados')} inseridos "
                      f"(TSE tinha {n_cands})")
                ok += 1
                total_cand += res.get("atualizados", 0)
            else:
                print(f"[err POST] {nome} {uf}: HTTP {resp.status_code}")
                fail += 1
        except Exception as e:
            print(f"[err POST] {nome} {uf}: {e}")
            fail += 1
        time.sleep(0.3)  # gentileza com o TSE

print(f"\n=== {ok} sucessos, {fail} falhas, {total_cand} candidatos importados ===")
