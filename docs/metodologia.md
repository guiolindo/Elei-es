# Metodologia matemática

Todas as regras que o site usa pra decidir "resultado matematicamente definido", com as fontes primárias que embasam cada uma.

## Princípio geral

**Toda comparação é estrita**. Se ainda existir cenário de empate exato, o resultado permanece em disputa. O motor prefere errar pra menos (chamar tarde) do que pra mais (chamar cedo).

**Limite superior conservador**. `votos_restantes_max = eleitorado_apto − eleitorado_apto_totalizadas`. Isso é um upper bound: na realidade ~20% se abstém e ~10% dos válidos vira branco/nulo, mas o motor não presume — usa o eleitorado total das seções faltantes como potencial máximo pra oposição. Isso ATRASA um pouco cada chamada, mas nunca chama errado.

**Silêncio inicial**. Enquanto `pct_apurado < 20%`, o motor não emite nada. Antes disso o `restantes_max` é grande demais pra qualquer desigualdade fechar.

## 1. Presidente eleito no 1º turno

**Fórmula**:
```
lider.votos × 2 > qt_votos_validos + restantes_max
```

**Base legal**: Constituição Federal, art. 77 §2º:
> "Será considerado eleito Presidente o candidato que, registrado por partido político, obtiver a maioria absoluta de votos, não computados os em branco e os nulos."

**Cenário coberto pelo restantes_max**: pior caso pro líder é todos os restantes virarem válidos e irem pra oposição.

## 2. Segundo turno matematicamente definido

**Duas condições estritas simultâneas**:
1. **Líder não pode mais fechar 1º turno**:
   ```
   (a.votos + restantes_max) × 2 ≤ qt_votos_validos + restantes_max
   ```
2. **3º colocado não alcança o 2º**:
   ```
   c.votos + restantes_max < b.votos
   ```

**Bug histórico corrigido**: versão anterior do motor só verificava a condição 2. Isso gerava falso positivo — se o líder ainda tem folga pra fechar 1T, o 2º turno NÃO está definido. QA achou, teste `test_segundo_turno_nao_definido_lider_pode_vencer_1t` cobre.

## 3. Majoritário — 1 vaga (Governador)

**Fórmula**:
```
b.votos + restantes_max < a.votos
```

**Base legal**: Código Eleitoral (Lei 4.737/1965), regras aplicáveis a Governadores nas eleições gerais (arts. 79-83 da CF regulam elegibilidade; art. 28 CF define governador).

## 4. Majoritário — múltiplas vagas (Senador 2026)

**Cenário 2026**: eleição de renovação de 2/3 do Senado — cada UF elege **2 senadores**. Anos de renovação 1/3 (2018, 2022) elegem 1.

**Fonte**: Constituição Federal, art. 46 §2º:
> "A representação de cada Estado e do Distrito Federal será renovada de quatro em quatro anos, alternadamente, por um e dois terços."

Confirmado pra 2026:
- [TRE-PR — Nas Eleições 2026, estarão em disputa duas vagas para senadores](https://www.tre-pr.jus.br/comunicacao/noticias/2026/Fevereiro/nas-eleicoes-2026-estarao-em-disputa-duas-vagas-para-senadores)
- [Senado Verifica — Eleições 2026: voto para o Senado](https://www12.senado.leg.br/verifica/materias-especiais/2026/eleicoes-2026-veja-o-que-e-fato-sobre-o-voto-para-o-senado)

**Fórmula** (função `eleitos_majoritario_multivaga`):
```
Se ordenados[N-1].votos > ordenados[N].votos + restantes_max
  → top-N estão TODOS matematicamente eleitos
```

Onde `N` é o número de vagas (2 pra senador em 2026). O motor só declara TODOS os top-N como eleitos quando o N-ésimo está inalcançável pelo (N+1)-ésimo. Caso contrário retorna lista vazia — se ainda existe possibilidade de troca no top-N, ninguém é declarado eleito.

## 5. Matematicamente eliminado

Um candidato está eliminado se, mesmo levando todos os restantes, não pode entrar no top-N relevante:
```
candidato.votos + restantes_max < pos_alvo.votos
```

- Presidente: `pos_alvo = 2º colocado` (top 2 vai pro 2º turno).
- Governador: `pos_alvo = 1º colocado`.
- Senador 2026: `pos_alvo = 2º colocado` (2 vagas).

## 6. Detecção de virada

Compara posições no top-5 entre dois snapshots consecutivos. Se A subiu passando B, emite `VIRADA(A, B)`.

**Bug histórico corrigido**: candidato novo (SQ inédito) que aparecia num snapshot era tratado como se estivesse "à frente" antes, disparando virada fantasma. Corrigido usando sentinel `len(pos_anterior)` (posição atrás de todo mundo) em vez de `-1`.

## 7. Proporcional (Deputado Federal/Estadual)

Sistema atual pós-STF ADI 7228/7263 (2024): **três fases**.

### 7.1. Quociente Eleitoral (QE)

```
QE = int(votos_validos / vagas)
```

Onde `votos_validos = votos nominais + votos de legenda + votos de todas as unidades`.

**Base**: Código Eleitoral art. 106.

### 7.2. Fase 1 — Distribuição por Quociente Partidário (QP)

Cada unidade (partido isolado ou federação) recebe:
```
vagas_QP = int(votos_unidade / QE)
```

**Barreira do candidato**: cada candidato precisa ≥ **10% do QE** em votos nominais pra ocupar uma vaga do QP. Se o partido levou 3 vagas mas só 2 candidatos passam da barreira, ganha 2 e a 3ª volta pro pool de sobras.

**Base**: Código Eleitoral art. 108, com redação da Lei 13.165/2015.

### 7.3. Fase 2 — Sobras (Regra 80/20)

Só concorrem à distribuição de sobras:
- **Unidade** com ≥ **80% do QE** em votos, E
- **Candidatos** com ≥ **20% do QE** em votos nominais.

Distribuição por **maiores médias** (D'Hondt):
```
média = votos_unidade / (vagas_totais_ja + 1)
```
A unidade com maior média leva a próxima vaga, incrementa contador, recalcula.

**Base**: Código Eleitoral art. 109 §2º, com redação da Lei 14.211/2021.

Fontes:
- [Senado Notícias — Lei prevê novas regras para 'sobras'](https://www12.senado.leg.br/noticias/materias/2021/10/04/lei-preve-novas-regras-para-sobras-nas-eleicoes-de-deputados-e-vereadores)

### 7.4. Fase 3 — Residual (STF ADI 7228/7263, 2024)

Se ainda sobram vagas após a Fase 2 (nenhuma unidade preenche 80/20), a distribuição continua por maiores médias entre TODAS as unidades com candidatos disponíveis. **Sem barreira do partido**, **sem barreira do candidato** — um candidato com < 10% do QE pode se eleger aqui.

**Base**: STF em 2024 (ADI 7228, 7263 e 7325) julgou inconstitucional a barreira do 80% na fase residual do art. 109, III. A decisão vale a partir das eleições de 2024.

Fontes primárias:
- [STF — Supremo invalida regra sobre distribuição de sobras eleitorais](https://portal.stf.jus.br/noticias/verNoticiaDetalhe.asp?idConteudo=528283)
- [Agência Brasil — STF derruba regras de sobras eleitorais (Fev/2024)](https://agenciabrasil.ebc.com.br/justica/noticia/2024-02/stf-derruba-regras-de-sobras-eleitorais)
- [Consultor Jurídico — STF foi coerente com seus precedentes](https://conjur.com.br/2024-mar-07/sobras-eleitorais-stf-foi-coerente-com-seus-precedentes/)
- [Transmissão Política — A Redefinição da 3ª Fase](https://transmissaopolitica.com.br/politica-nacional/2026/02/24/decisao-stf-sobras-eleitora/)

**Argumentação do STF (Min. Alexandre de Moraes)**: a regra anterior deixava vagas ocupadas por candidatos com poucos votos e excluía candidatos com votação expressiva de partidos menores. Exemplo citado: no AP em 2022, 4 deputados com 28.831 votos combinados haviam substituído candidatos com 48.000.

### 7.5. Federações partidárias

Uma **federação** (Lei 14.208/2021 + EC 97/2017) é um conjunto de partidos que competem como uma única unidade nas eleições:
- Somam votos pro cálculo do QE.
- Competem por vagas em bloco.
- Distribuem internamente pelos candidatos mais votados.

**Default hardcoded pra 2026** (baseado nas federações de 2022, ajuste se mudar):
```python
{
    "F_BRASIL_ESPERANCA": {13, 65, 43},  # PT + PCdoB + PV
    "F_PSOL_REDE": {50, 18},              # PSOL + REDE
    "F_PSDB_CIDADANIA": {45, 23},         # PSDB + Cidadania
}
```

Pra rodar com federações diferentes, passar `federacoes=...` na chamada.

### 7.6. Vagas por UF

**Deputado Federal** (513 total): Res. TSE 23.660/2022 e ADCT art. 45.

```python
VAGAS_DEP_FEDERAL = {
    "AC": 8, "AL": 9, "AM": 8, "AP": 8, "BA": 39, "CE": 22, "DF": 8,
    "ES": 10, "GO": 17, "MA": 18, "MG": 53, "MS": 8, "MT": 8, "PA": 17,
    "PB": 12, "PE": 25, "PI": 10, "PR": 30, "RJ": 46, "RN": 8, "RO": 8,
    "RR": 8, "RS": 31, "SC": 16, "SE": 8, "SP": 70, "TO": 8,
}  # soma = 513
```

**Deputado Estadual/Distrital**: ADCT art. 4º:
- Se `df ≤ 12` → `est = 3 × df`
- Se `df > 12` → `est = 36 + (df − 12)`

## Auditoria

Cada snapshot armazena o **hash SHA-256 do JSON bruto do TSE** no campo `snapshots.hash_conteudo`. O endpoint `/api/apuracao/atual` expõe esse hash junto dos resultados.

Qualquer pessoa pode:
1. Baixar o mesmo JSON do TSE via `resultados.tse.jus.br`.
2. Calcular o SHA-256.
3. Comparar com o hash exposto no site.

Se bater, é prova criptográfica de que o site exibe exatamente o que o TSE publicou — nenhuma modificação, nenhuma adulteração.

## Referências rápidas

| Regra | Norma |
|---|---|
| Maioria absoluta 1T presidente | CF art. 77 §2º |
| Governador majoritário | CF art. 28 + CE arts. 79-83 |
| Senado 2/3 renovação | CF art. 46 §2º |
| Quociente Eleitoral | CE art. 106 |
| Barreira 10% QE | CE art. 108 (red. Lei 13.165/2015) |
| Sobras 80/20 (Fase 2) | CE art. 109 §2º (red. Lei 14.211/2021) |
| Sobras residuais (Fase 3) | STF ADI 7228/7263/7325 (2024) |
| Federações | Lei 14.208/2021 + EC 97/2017 |
