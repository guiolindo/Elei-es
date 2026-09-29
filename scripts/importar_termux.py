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
TSE_DETALHE = "https://divulgacandcontas.tse.jus.br/divulga/rest/v1/candidatura/buscar"

ok = 0
fail = 0
total_cand = 0

# 1) Limpa candidatos falsos (seed) antes de importar os reais
print("Limpando seed antigo…")
try:
    r = requests.post(f"{APP}/api/admin/limpar-seed", timeout=30)
    print(f"  removidos: {r.json().get('removidos')}")
except Exception as e:
    print(f"  aviso: {e}")

FOTO_BASE = "https://divulgacandcontas.tse.jus.br/divulga/rest/arquivo/img"

def buscar_detalhe(ufs: list[str], sq: str) -> dict | None:
    """Puxa a ficha completa do candidato (nascimento, sexo, escolaridade,
    ocupação, gastos, vice, coligação). Presidente às vezes só responde
    com a UF do domicílio eleitoral do candidato, não com BR — por isso
    tentamos várias."""
    for uf in ufs:
        if not uf:
            continue
        try:
            r = requests.get(
                f"{TSE_DETALHE}/{ANO}/{uf}/{COD}/candidato/{sq}",
                impersonate="chrome",
                timeout=15,
            )
            if r.status_code == 200:
                j = r.json()
                if isinstance(j, dict) and j.get("id"):
                    return j
        except Exception:
            continue
    return None


def enviar_detalhe(sq: str, detalhe: dict) -> bool:
    try:
        r = requests.post(
            f"{APP}/api/admin/atualizar-detalhe",
            json={"sq_candidato": sq, "detalhe": detalhe},
            timeout=30,
        )
        return r.status_code == 200 and r.json().get("ok")
    except Exception:
        return False


def baixar_foto(sq: str, uf: str) -> bool:
    """Baixa a foto do candidato do TSE e envia pro app."""
    try:
        r = requests.get(f"{FOTO_BASE}/{COD}/{sq}/{uf}", impersonate="chrome", timeout=15)
        if r.status_code != 200 or len(r.content) < 500:
            return False
        import base64
        b64 = base64.b64encode(r.content).decode()
        resp = requests.post(
            f"{APP}/api/admin/upload-foto",
            json={"sq_candidato": sq, "b64": b64},
            timeout=30,
        )
        return resp.status_code == 200
    except Exception:
        return False


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
                # Majoritários: baixa foto + ficha completa (poucos candidatos)
                if cargo in (1, 3, 5):
                    uf_foto = "BR" if cargo == 1 else uf
                    n_fotos = 0
                    n_det = 0
                    for c in (data.get("candidatos") or [])[:20]:
                        sq = str(c.get("id") or "")
                        if not sq:
                            continue
                        # Pra presidente, tenta BR e as UFs do domicílio
                        ufs_tentativa = [uf_foto]
                        for k in ("ufCandidatura", "sgUe", "sgUf", "uf"):
                            v = c.get(k)
                            if v and v not in ufs_tentativa:
                                ufs_tentativa.append(v)
                        if cargo == 1:
                            ufs_tentativa += ["SP","RJ","MG","DF","BR"]
                        # Foto: mesma lógica — tenta as UFs até uma dar 200
                        for uf_try in ufs_tentativa:
                            if baixar_foto(sq, uf_try):
                                n_fotos += 1
                                break
                        det = buscar_detalhe(ufs_tentativa, sq)
                        if det and enviar_detalhe(sq, det):
                            n_det += 1
                        time.sleep(0.15)
                    if n_fotos or n_det:
                        print(f"     └ {n_fotos} fotos, {n_det} detalhes")
            else:
                print(f"[err POST] {nome} {uf}: HTTP {resp.status_code}")
                fail += 1
        except Exception as e:
            print(f"[err POST] {nome} {uf}: {e}")
            fail += 1
        time.sleep(0.3)  # gentileza com o TSE

print(f"\n=== {ok} sucessos, {fail} falhas, {total_cand} candidatos importados ===")
