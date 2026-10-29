"""Verificação de integridade de seções do 2º turno 2026 a partir dos arquivos da urna.

    python scripts/validacao_2t/verificar_integridade.py SECOES.csv SAIDA.csv

SECOES.csv tem colunas uf,municipio,zona,secao[,motivo,fuso]; fuso = horas a somar
à hora local da urna para chegar à de Brasília. Para cada seção baixa
do arquivo-urna do TSE o BU, o arquivo de assinaturas (vota.vsc), o RDV e o
log, verifica e grava uma linha em SAIDA.csv. Nada fica em disco além do CSV.

  1. Hashes: o SHA-512 do BU, do RDV e do log tem de bater com o que a própria
     urna gravou no vota.vsc (blocos de software e de hardware).
  2. Recontagem: os votos do RDV (um registro por voto, embaralhado) somados
     por candidato, brancos e nulos têm de bater com o BU, para cada cargo.
  3. Log do dia 25/10: votos computados = comparecimento do BU; horário do
     primeiro e do último voto (hora local); votos depois das 17h, 18h e 19h
     de Brasília; eleitores habilitados sem biometria no total e depois das 17h;
     menor intervalo entre dois votos e quantos vieram com menos de 15 s;
     reinícios do aplicativo de votação e linhas de ERRO.
O RDV não guarda horário e o log não guarda em quem se votou (sigilo do voto),
então não existe como saber em quem votaram os eleitores de depois das 17h.
"""
import asyncio, csv, hashlib, io, os, sys, zipfile
from collections import Counter
from datetime import datetime

import httpx

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from baixar_bu_secoes import BASE, H, arvore, decodifica, get, num  # noqa: E402

COLS = ["uf", "municipio", "zona", "secao", "motivo", "status",
        "hash_bu", "hash_rdv", "hash_log", "rdv_bate", "rdv_detalhe",
        "comparecimento_bu", "votos_log", "primeiro_voto", "ultimo_voto",
        "votos_apos_17", "votos_apos_18", "votos_apos_19",
        "sem_biometria_log", "sem_biometria_apos_17", "menor_intervalo_s", "intervalos_menor_15s",
        "reinicios_vota", "erros_log", "encerramento_log", "urnas_no_log"]


def hashes_vsc(vsc):
    """{nome do arquivo: [hashes SHA-512 gravados pela urna]}."""
    out = {}

    def walk(n):
        for t, v in n:
            if t == 0x30 and isinstance(v, list) and len(v) == 2 and v[0][0] == 0x1b and v[1][0] == 0x30:
                h = [x[1] for x in v[1][1] if x[0] == 0x04 and len(x[1]) == 64]
                out.setdefault(v[0][1].decode("latin-1"), []).extend(h[:1])
            elif isinstance(v, list):
                walk(v)
            elif t == 0x04 and len(v) > 2 and v[0] == 0x30:
                try:
                    walk(arvore(v))
                except Exception:
                    pass
    walk(arvore(vsc))
    return out


def recontagem_rdv(rdv):
    """{código do cargo: Counter(chave → votos)} no mesmo formato de chave do BU."""
    por_cargo = {}

    def walk(n):
        for t, v in n:
            if isinstance(v, list):
                # bloco de um cargo: [81] cargo (ou [82] consulta), [02] qtd escolhas, [30] lista de votos
                if any(x[0] in (0x81, 0x82) for x in v) and any(x[0] == 0x30 for x in v):
                    cod = [x for x in v if x[0] in (0x81, 0x82)][0]
                    cargo = num(cod[1]) + (100 if cod[0] == 0x82 else 0)
                    votos = [x for x in v if x[0] == 0x30][0][1]
                    if votos and all(isinstance(y[1], list) and y[1] and y[1][0][0] == 0x0a for y in votos):
                        c = por_cargo.setdefault(cargo, Counter())
                        for _, voto in votos:
                            tipo = num(voto[0][1])
                            dig = voto[1][1].decode() if len(voto) > 1 else ""
                            if tipo in (1, 2):
                                c[str(int(dig))] += 1
                            elif tipo in (3, 5):
                                c["95"] += 1
                            else:
                                c["96"] += 1
                        continue
                walk(v)
    walk(arvore(rdv))
    return por_cargo


def analisa_log(jez, fuso=0, dia="25/10/2026"):
    # Com troca de urna no meio da votação, o .jez traz o logd.dat da urna final
    # e, compactado dentro dele, o da urna anterior: junta os dois.
    linhas = []

    def ler(blob, nivel=0):
        z = zipfile.ZipFile(io.BytesIO(blob))
        for nome in z.namelist():
            dado = z.read(nome)
            if nome.endswith(".jez") and nivel < 2:
                try:
                    ler(dado, nivel + 1)
                except zipfile.BadZipFile:
                    pass
            elif nome.endswith(".dat"):
                linhas.extend(dado.decode("latin-1").splitlines())
    ler(jez)
    linhas = list(dict.fromkeys(linhas))  # os logs aninhados podem repetir linhas uns dos outros
    urnas = len({l.split("\t")[2] for l in linhas if l.count("\t") >= 4})
    linhas.sort(key=lambda l: (l[6:10], l[3:5], l[0:2], l[11:19]))
    txt = "\n".join(linhas)
    votos, sem_bio = [], []
    bio_atual = False; hab_bio = True; erros = reinicios = 0; enc = ""
    for linha in txt.splitlines():
        p = linha.split("\t")
        if len(p) < 5 or not p[0].startswith(dia):
            continue
        msg = p[4]
        if p[1] == "ERRO":
            erros += 1
        if p[3] == "VOTA" and msg.startswith("Iniciando aplicação"):
            reinicios += 1
        if msg.startswith("Tipo de habilitação do eleitor [biométrica]"):
            bio_atual = True
        elif msg == "Eleitor foi habilitado":
            hab_bio = bio_atual; bio_atual = False
        elif msg == "O voto do eleitor foi computado":
            t = datetime.strptime(p[0], "%d/%m/%Y %H:%M:%S")
            votos.append(t)
            if not hab_bio:
                sem_bio.append(t)
            hab_bio = True
        elif msg == "Procedimento de encerramento confirmado":
            enc = p[0][11:]
    votos.sort()
    gaps = [(b - a).total_seconds() for a, b in zip(votos, votos[1:])]
    h = lambda t: t.hour * 60 + t.minute + fuso * 60  # minutos no horário de Brasília
    return dict(
        votos_log=len(votos),
        primeiro_voto=votos[0].strftime("%H:%M:%S") if votos else "",
        ultimo_voto=votos[-1].strftime("%H:%M:%S") if votos else "",
        votos_apos_17=sum(h(t) >= 17 * 60 for t in votos),
        votos_apos_18=sum(h(t) >= 18 * 60 for t in votos),
        votos_apos_19=sum(h(t) >= 19 * 60 for t in votos),
        sem_biometria_log=len(sem_bio),
        sem_biometria_apos_17=sum(h(t) >= 17 * 60 for t in sem_bio),
        menor_intervalo_s=int(min(gaps)) if gaps else "",
        intervalos_menor_15s=sum(g < 15 for g in gaps),
        reinicios_vota=reinicios, erros_log=erros, encerramento_log=enc, urnas_no_log=urnas)


async def secao(cli, sem, alvo, w, f):
    uf, mu, zn, ns, motivo, fuso = alvo
    linha = dict(uf=uf.upper(), municipio=int(mu), zona=int(zn), secao=int(ns), motivo=motivo)
    async with sem:
        try:
            pre = f"{BASE}/dados/{uf}/{mu}/{zn}/{ns}"
            aux = await get(cli, f"{pre}/p003221-{uf}-m{mu}-z{zn}-s{ns}-aux.json")
            if not aux or not aux.get("hashes"):
                linha["status"] = "sem arquivos"; return
            hsh = aux["hashes"][-1]
            nomes = {a.get("tp") or a["nm"].rsplit("-", 1)[-1].split(".")[0]: a["nm"] for a in hsh.get("arq", [])}
            arqs = {}
            # Seção apurada no Sistema de Apuração: busa / sa.vsc / logsa no lugar de bu / vota.vsc / log
            if "bu" not in nomes and "busa" in nomes:
                nomes["bu"], linha["motivo"] = nomes["busa"], (motivo + " SA").strip()
                if "sa" in nomes:
                    nomes["vota"] = nomes["sa"]
                nomes.pop("log", None)
            for tp in ("bu", "vota", "rdv", "log"):
                if tp in nomes:
                    arqs[tp] = await get(cli, f"{pre}/{hsh['hash']}/{nomes[tp]}", binario=True)
            if not arqs.get("bu"):
                linha["status"] = f"sem bu ({hsh.get('st')})"; return
            linha["status"] = "ok"
            bu = decodifica(arqs["bu"])
            pres = [c for c in bu["cargos"] if c[0] == 1]
            linha["comparecimento_bu"] = pres[0][2] if pres else ""
            if arqs.get("vota"):
                hv = hashes_vsc(arqs["vota"])
                for tp, col in (("bu", "hash_bu"), ("rdv", "hash_rdv"), ("log", "hash_log")):
                    if tp in nomes and arqs.get(tp) is not None:
                        esperado = hv.get(nomes[tp], [])
                        d = hashlib.sha512(arqs[tp]).digest()
                        linha[col] = "ok" if esperado and all(e == d for e in esperado) else ("ausente" if not esperado else "DIVERGE")
            if arqs.get("rdv"):
                rc = recontagem_rdv(arqs["rdv"])
                dif = []
                for cargo, _, _, votos in bu["cargos"]:
                    r = rc.get(cargo, Counter())
                    for k in set(votos) | set(r):
                        if votos.get(k, 0) != r.get(k, 0):
                            dif.append(f"c{cargo}:{k} bu={votos.get(k, 0)} rdv={r.get(k, 0)}")
                linha["rdv_bate"] = "sim" if not dif else "NAO"
                linha["rdv_detalhe"] = ";".join(dif[:6])
            if arqs.get("log"):
                linha.update(analisa_log(arqs["log"], fuso))
        except Exception as e:
            linha["status"] = f"erro {e!r}"[:150]
        finally:
            w.writerow(linha); f.flush()


async def main(entrada, saida):
    alvos = []
    for r in csv.DictReader(open(entrada)):
        alvos.append((r["uf"].lower(), f"{int(r['municipio']):05d}", f"{int(r['zona']):04d}",
                      f"{int(r['secao']):04d}", r.get("motivo", ""), int(r.get("fuso") or 0)))
    feitas = set()
    if os.path.exists(saida):
        feitas = {(r["uf"].lower(), int(r["municipio"]), int(r["zona"]), int(r["secao"])) for r in csv.DictReader(open(saida))}
    novo = not os.path.exists(saida)
    f = open(saida, "a", newline=""); w = csv.DictWriter(f, COLS, extrasaction="ignore")
    if novo:
        w.writeheader()
    alvos = [a for a in alvos if (a[0], int(a[1]), int(a[2]), int(a[3])) not in feitas]
    print("seções:", len(alvos), "já feitas:", len(feitas), flush=True)
    lim = httpx.Limits(max_connections=24, max_keepalive_connections=24)
    async with httpx.AsyncClient(headers=H, timeout=60, limits=lim, http2=True) as cli:
        sem = asyncio.Semaphore(24)
        for i in range(0, len(alvos), 500):
            await asyncio.gather(*(secao(cli, sem, a, w, f) for a in alvos[i:i + 500]))
            print(min(i + 500, len(alvos)), "/", len(alvos), flush=True)
    f.close()


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1], sys.argv[2]))
