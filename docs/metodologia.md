# Metodologia matemática

Todas as regras que o site usa pra decidir "resultado matematicamente definido", com as fontes primárias que embasam cada uma.

## Princípio geral

**Toda comparação é estrita**. Se ainda existir cenário de empate exato, o resultado permanece em disputa. O motor prefere errar pra menos (chamar tarde) do que pra mais (chamar cedo).

**Limite superior conservador**. `votos_restantes_max = eleitorado_apto − eleitorado_apto_totalizadas`. Isso é um upper bound: na realidade ~20% se abstém e ~10% dos válidos vira branco/nulo, mas o motor não presume — usa o eleitorado total das seções faltantes como potencial máximo pra oposição. Isso ATRASA um pouco cada chamada, mas nunca chama errado.

**Silêncio inicial**. Enquanto `pct_apurado < 20%`, o motor não emite nada. Antes disso o `restantes_max` é grande demais pra qualquer desigualdade fechar.

**Exclusão de candidatos não-ativos**. Antes de qualquer cálculo (maioria absoluta, inalcançabilidade, QE, QP, barreira, D'Hondt, matematicamente eliminado), o motor remove todo candidato cuja `situacao` seja diferente de `ativo` — ou seja, `renunciou`, `cancelado`, `cassado` ou `indeferido_sem_recurso`.

**Base legal**: Lei 9.504/97, art. 175 §3º:
> "Serão nulos, para todos os efeitos, os votos dados a candidatos inelegíveis ou não registrados."

**Impacto prático**:
- Majoritário: os votos no cassado/renunciado **não contam** no total de válidos usado pra testar maioria absoluta. O 2º colocado efetivo passa a disputar com o líder.
- Proporcional: os votos **não entram no QE**, **não entram no QP** da legenda nem da federação, **não puxam chapa**. Vagas que seriam do partido do cassado via sobras D'Hondt vão pra outro partido.
- Isso é defesa em profundidade: filtragem acontece em `avaliar_apuracao` (`math_engine/engine.py`) e em `calcular_eleitos_proporcional` (`math_engine/proporcional.py`), independente do caller.

**Fonte da verdade**: campo `situacao` na tabela `candidatos`, atualizado pelo parser de `descricaoSituacao` do TSE (`poller/candidatos_tse.py`), com normalização de acentos. Caso real 2026: Leonardo Avalanche e Pablo Marçal (PRTB) marcados `renunciou`.

**Escopo nacional vs. estadual**. A regra constitucional de maioria absoluta pra Presidente vale sobre os válidos do **Brasil inteiro** (CF art. 77 §2º). O coletor baixa `(cargo=1, UF)` apenas pra alimentar o mapa colorido por estado; o motor matemático **não avalia** nenhum evento (`ELEITO_1T`, `SEGUNDO_TURNO_DEFINIDO`, `MATEMATICAMENTE_ELIMINADO`) nesses alvos. Um candidato pode ter 70% dos válidos num estado e perder o pleito nacional.

## 1. Presidente eleito no 1º turno

**Fórmula**:
```
lider.votos × 2 > qt_votos_validos + restantes_max
```

**Base legal**: Constituição Federal, art. 77 §2º:
> "Será considerado eleito Presidente o candidato que, registrado por partido político, obtiver a maioria absoluta de votos, não computados os em branco e os nulos."

**Cenário coberto pelo restantes_max**: pior caso pro líder é todos os restantes virarem válidos e irem pra oposição.

## 2. Segundo turno matematicamente definido

Aplicável a **Presidente** e **Governador** — os dois cargos que exigem maioria absoluta no 1º turno (art. 28 CF remete a art. 77).

**Duas condições estritas simultâneas**:
1. **Líder não pode mais fechar 1º turno**:
   ```
   (a.votos + restantes_max) × 2 ≤ qt_votos_validos + restantes_max
   ```
2. **3º colocado não alcança o 2º**:
   ```
   c.votos + restantes_max < b.votos
   ```

**Bugs históricos corrigidos**:
- (v1) Motor só verificava a condição 2 → falso positivo se líder ainda podia fechar 1T. Teste `test_segundo_turno_nao_definido_lider_pode_vencer_1t`.
- (v2) Motor só emitia SEGUNDO_TURNO_DEFINIDO pra Presidente, ignorando Governador. Agora Presidente e Governador compartilham a mesma máquina (art. 28 CF é explícito: "observado, quanto ao mais, o disposto no art. 77"). Teste `test_governador_2_turno_definido`.

## 3. Majoritário — 1 vaga

Duas famílias de regra na Constituição:

### 3.1. Governador — maioria absoluta (CF art. 28 → art. 77 §2º)

O Governador é regido pelo art. 28 CF, que remete ao art. 77 (regras da eleição presidencial): "maioria absoluta dos votos válidos" no 1º turno, senão vai a 2T.

**Duas condições estritas simultâneas**:
1. **Líder inalcançável** pelo 2º: `b.votos + restantes_max < a.votos`
2. **Maioria absoluta matematicamente garantida**: `a.votos × 2 > votos_validos + restantes_max`
   (mesmo que TODOS os restantes virem válidos, o líder mantém >50%)

Se qualquer uma falha, NÃO é eleito no 1T — vai a 2º turno (ou continua em disputa).

**Bug histórico**: versão anterior do motor só verificava condição 1. Cenário A=40%, B=20%, C=10%, restantes=5%: líder inalcançável mas sem maioria → deveria ir a 2T, mas motor declarava eleito. Coberto por `test_governador_precisa_maioria_absoluta_1t`.

### 3.1.b. Regra do 2º turno (Presidente e Governador)

Quando o 1º turno **não** decide (nenhum candidato tem maioria absoluta e o motor emitiu `SEGUNDO_TURNO_DEFINIDO`), o TSE realiza o 2º turno com os **dois mais votados**. Aí a apuração recomeça do zero, com um `cod_eleicao` diferente (`ELEICAO_COD_2T`) e um novo tipo de snapshot (`turno=2`).

**No 2º turno só há 2 candidatos.** Não existe 3º turno. Vence quem tiver mais votos ao fim. Formalmente:
```
b.votos + restantes_max < a.votos
```
Que, com apenas 2 candidatos, colapsa matematicamente na condição de maioria absoluta:
```
validos_finais_max = A + B + restantes
2A > validos_finais_max ⇔ A > B + restantes ⇔ a mesma condição acima
```
As duas condições viram uma só — não há como ter maioria simples sem também ter maioria absoluta em 2T.

**Eventos emitidos no 2T:**
- `ELEITO_2T` — pra Presidente.
- `ELEITO_MAJORITARIO` com `detalhes.turno=2` — pra Governador.
- `MATEMATICAMENTE_ELIMINADO` — pro perdedor quando inalcançável.
- **Não emite** `SEGUNDO_TURNO_DEFINIDO` (não existe 3T).
- **Não emite** `ELEITO_1T` (é a máquina errada).

**Chamada**: `avaliar_apuracao(candidatos, totais, cod_cargo=1, turno=2)`. O poller passa `turno` a partir do `AlvoColeta.turno` (que é preenchido pelo alvo de coleta — cargo 1 turno 1 é `presidente_1t`, cargo 1 turno 2 é `presidente_2t`).

**Empate exato no 2T — Art. 110 do Código Eleitoral**:

> "Em caso de empate haver-se-á por eleito o mais idoso, salvo se algum dos candidatos ainda não tiver a idade mínima fixada nesta Lei, caso em que se dará a eleição ao outro."

Cenário: 100% apurado, dois candidatos com exatamente o mesmo número de votos. Formalmente vence o mais idoso.

**Implementação**: `CandidatoResumo` aceita campo opcional `idade_anos`. Quando `restantes == 0` e `a.votos == b.votos`, o motor verifica se as idades foram fornecidas — se sim, emite `ELEITO_2T` pro mais velho com `detalhes.criterio_desempate = "idade_art_110_ce"`. Se as idades não foram fornecidas ou são iguais, o motor não decide (deixa pra Justiça Eleitoral). O poller lê `raw_divulga.dataDeNascimento` do candidato (importado pelo Termux) e calcula a idade automaticamente pra snapshots do 2T.

### 3.2. Senador maioria simples (CF art. 46)

Senador NÃO precisa de maioria absoluta — os N mais votados vencem. Em ano de renovação 1/3 (2018, 2022), N=1. Em 2026 (renovação 2/3), N=2 — ver seção 4.

**Fórmula** (1 vaga, quando aplicável): `b.votos + restantes_max < a.votos`

## 3.3. Desempate por idade (art. 110 CE)

Vale pra TODOS os cargos sempre que a última vaga/posição ficar com dois candidatos em **empate exato de votos** no fechamento (100% apurado):

> "Em caso de empate, haver-se-á por eleito o candidato mais idoso." — Código Eleitoral, art. 110.

Aplicação no sistema:
- **Presidente/Governador 2º turno**: motor emite ELEITO_2T pro mais velho.
- **Senador multivaga (2 vagas em 2026)**: `eleitos_majoritario_multivaga` troca o 2º colocado pelo 3º se o 3º for mais velho.
- **Deputado proporcional**: `calcular_eleitos_proporcional` ordena candidatos do mesmo partido/federação por `(votos desc, idade desc)` — mais velho fica à frente em caso de empate exato.

Se a idade de qualquer um dos empatados não foi coletada (`idade_anos is None`), o motor **não decide** — mantém em disputa e deixa pra Justiça Eleitoral resolver. É preferível silêncio a erro.

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

> **Pré-filtro obrigatório**: antes de QE/QP/barreira/D'Hondt, o motor remove todo candidato com `situacao != "ativo"`. Ver seção "Exclusão de candidatos não-ativos" no topo do documento. Isso impede que o partido do cassado "puxe" vagas via sobras com votos que legalmente são nulos (Lei 9.504/97 art. 175 §3º).

### 7.1. Quociente Eleitoral (QE)

```
QE = int(votos_validos / vagas)
```

Onde `votos_validos = soma dos votos nominais dos candidatos ATIVOS + votos de legenda`.

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

**5 federações registradas no TSE pras Eleições 2026** (verificado 2026-09-29 contra Portal TSE):

```python
FEDERACOES_2026_DEFAULT = {
    "F_BRASIL_ESPERANCA":    {13, 65, 43},  # PT + PCdoB + PV       (herdada de 2022)
    "F_PSDB_CIDADANIA":      {45, 23},      # PSDB + Cidadania      (herdada de 2022)
    "F_PSOL_REDE":           {50, 18},      # PSOL + REDE           (herdada de 2022)
    "F_UNIAO_PROGRESSISTA":  {44, 11},      # UNIÃO + PP            (NOVA — mar/2026)
    "F_RENOVACAO_SOLIDARIA": {77, 25},      # SOLIDARIEDADE + PRD   (NOVA — dez/2025)
}
```

A federação **União Progressista** (União Brasil + Progressistas) foi aprovada pelo TSE em 26/03/2026 e forma o maior bloco da Câmara com 109 deputados + 15 senadores no ato da criação. A **Renovação Solidária** foi aprovada em dez/2025 juntando Solidariedade e PRD.

Fontes primárias:
- [Portal TSE — Federações registradas](https://www.tse.jus.br/partidos/federacoes-registradas-no-tse)
- [TSE — União Progressista](https://www.tse.jus.br/partidos/federacoes-registradas-no-tse/uniao-progressista)
- [TSE — Renovação Solidária](https://www.tse.jus.br/partidos/federacoes-registradas-no-tse/renovacao-solidaria)
- [Agência Brasil — TSE aprova União Progressista (mar/2026)](https://agenciabrasil.ebc.com.br/justica/noticia/2026-03/tse-aprova-registro-da-federacao-uniao-progressista)

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

## 8. Projeções

Duas projeções do total final por candidato são expostas em `/api/apuracao/atual`. **Nenhuma é predição eleitoral** — ambas são extrapolações aritméticas com disclaimer visual (opacidade reduzida, prefixo `~`) e somem automaticamente ao atingir 100% apurado.

### 8.1. Projeção linear
```
proj = votos_atual × secoes_total ÷ secoes_apuradas
```
Assume que o restante das urnas vai votar com a mesma proporção das já apuradas. É sempre calculada após qualquer apuração começar.

### 8.2. Projeção por tendência (janela móvel)
Problema que resolve: no Brasil, Sul/Sudeste historicamente apura antes do Nordeste. A projeção linear subestima/superestima candidatos cujo perfil regional difere das urnas já apuradas.

Fórmula:
```
taxa_recente = (votos_atual - votos_15_atrás) ÷ (pct_apurado_atual - pct_apurado_15_atrás)
proj         = votos_atual + taxa_recente × (100 - pct_apurado)
```

Guardas pra evitar ruído:
- Só roda após `pct_apurado >= 30%`.
- Janela precisa de pelo menos 10 snapshots não-suspeitos.
- Delta de % apurado na janela precisa ser `>= 1%` (evita divisão por quase-zero).
- Resultado clipado entre `votos_atual` e `2 × projecao_linear`.

Quando qualquer guarda falha, o campo `projecao_tendencia` fica `null` — o frontend cai pra `projecao_linear`.

Fonte: `app/api.py:_calcular_projecao_tendencia`.

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
