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

**Sub judice ≠ não-ativo**. Candidato "Indeferido em prazo recursal" (recurso rodando) PERMANECE na urna e seus votos **contam como válidos** até trânsito em julgado (Lei 9.504 art. 16-A). O TSE, porém, segrega esses votos do campo `v.vv` do payload JSON — porque podem virar nulos se o recurso for rejeitado. O motor usaria um denominador subestimado e emitiria `ELEITO_MAJORITARIO` indevidamente.

**Fix**: o parser de totais usa `qt_votos_validos = max(TSE.v.vv, soma dos cand.vap do payload)`. A soma incluindo todos os candidatos (ativos + sub judice) nunca fica abaixo da realidade. Testes `test_parse_qt_votos_validos_inclui_sub_judice` + `_mantem_vv_quando_maior`.

**Caso real 2026 — RJ Gov 1T**: Garotinho (REP 10) "Indeferido em prazo recursal", 274.411 votos. Com `v.vv` do TSE o líder Douglas Ruas aparecia com 50,88% dos válidos → engine emitiu `ELEITO_MAJORITARIO`. Com `max(v.vv, soma)` o pct correto é 49,27% → `SEGUNDO_TURNO_DEFINIDO` com Douglas × Eduardo Paes (bate com o anúncio oficial do TSE). Correção retroativa aplicada via `POST /api/admin/corrigir-rj-gov-sub-judice`.

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

Duas estimativas aritméticas do total final por candidato são expostas em `/api/apuracao/atual`. **Nenhuma é predição eleitoral** — ambas são extrapolações matemáticas simples com disclaimer visual (opacidade reduzida, prefixo `~`) que somem automaticamente ao atingir 100% apurado. O frontend exibe as duas como **faixa**: se convergem, mostra um número só; se divergem, a faixa reflete a incerteza real.

### 8.1. Projeção linear
```
proj = votos_atual × secoes_total ÷ secoes_apuradas
```
Assume que o restante das urnas vai votar com a mesma proporção das já apuradas. Sempre calculada após o início da apuração.

### 8.2. Projeção por janela móvel
```
taxa_recente = (votos_atual - votos_15_atrás) ÷ (pct_apurado_atual - pct_apurado_15_atrás)
proj         = votos_atual + taxa_recente × (100 - pct_apurado)
```
Captura o ritmo das últimas 15 snapshots. **Importante: não modela composição regional**. Se as urnas restantes forem de perfil regional muito diferente, essa projeção falha junto com a linear — ela só reage ao que já aconteceu nas últimas atualizações, não antecipa o que vem.

Guardas pra evitar ruído:
- Só roda após `pct_apurado >= 30%`.
- Janela precisa de pelo menos 10 snapshots não-suspeitos.
- Delta de % apurado na janela precisa ser `>= 1%` (evita divisão por quase-zero).
- Resultado clipado entre `votos_atual` e `2 × projecao_linear` (guard de UX pra evitar valor absurdo — não tem base estatística).

Quando qualquer guarda falha, o campo `projecao_tendencia` fica `null` — o frontend cai pra `projecao_linear`.

Fonte: `app/api.py:_calcular_projecao_tendencia`.

### 8.3. Limitações conhecidas (honestas)
- **Composição regional das urnas faltantes não é modelada**. No 2º turno isso é tratado pela estimativa estratificada (8.4).
- **Sem backtest histórico ainda**. Os parâmetros (janela de 15, mínimo de 30% apurado) são escolhas heurísticas razoáveis mas não validadas contra erro observado em eleições passadas. Validação retroativa com dados 2022/2026 fica pra depois do dia D.
- **Sem intervalo de incerteza estatístico**. A "faixa" exibida é só a diferença entre as duas métricas aritméticas — informativa mas não é um intervalo de confiança formal.

### 8.4. Estimativa do 2º turno (estratificada) — `math_engine/projecao.py`

Usada só no 2º turno, Presidente-BR e Governador. As seções 8.1–8.3 valem para o 1º turno.

**Dados de entrada por estrato `u`** (Presidente: 27 UFs + exterior; Governador: a própria UF), do último snapshot não-suspeito do 2T:
`E_u` eleitorado apto · `E_cu` apto das seções já totalizadas · `A_u`, `B_u` votos de A e B · `V_u = A_u + B_u` (no 2T, válidos = A + B) · `n_cu` seções totalizadas · `n_u` seções totais. **Prior** `p_u = A¹_u / (A¹_u + B¹_u)` com os votos de A e B no 1º turno daquele estrato.

**Passo 1 — válidos restantes** (inclui comparecimento *e* brancos/nulos, porque a razão é medida em válidos por apto):
```
r_u = V_u / E_cu                 (estrato sem voto ainda: r_nat = ΣV / ΣE_c)
R_u = r_u · (E_u − E_cu)
```

**Passo 2 — swing nacional 1T→2T**, ponderado por válidos, só estratos com prior e voto:
```
δ = Σ V_u (q_u − p_u) / Σ V_u,   q_u = A_u / V_u
var(δ) = τ_p² / n_eff,           n_eff = 1 / Σ (V_u/ΣV)²
```

**Passo 3 — share de A nos votos que faltam** (mistura por precisão, não linear no % apurado):
```
v_o = drift_a² + c²/n_cu + b²/(n_u − n_cu)        variância do observado como preditor do restante
w   = (1/v_o) / (1/v_o + 1/τ_p²)
m_u = w · q_u + (1 − w) · (p_u + δ)
v_u = 1 / (1/v_o + 1/τ_p²)
```
`drift_a` é um **piso**: mesmo com 99% apurado, o observado nunca vira certeza sobre as seções que faltam (elas não são amostra aleatória). Com os valores atuais o peso do observado fica **no máximo ≈ 0,44** (`1/0,028²` contra `1/0,025²`).
Casos: estrato sem prior → `m = q`, `v = v_o`; sem voto ainda → `m = p + δ`, `v = τ_p²`; sem nenhum dos dois → `m = q_nat`, `v = τ_sem_prior²`.
**Estrato único (Governador)**: `δ` sairia do próprio estrato e `p + δ = q` — o 1T era anulado e a variância contava duas fontes. Desde 17/10: `m = w′q + (1−w′)p`, com `τ′² = τ_p² + τ_swing²` no lugar de `τ_p²`.

**Passo 4 — total e incerteza**:
```
S   = (Σ A_u + Σ R_u m_u) / (Σ V_u + Σ R_u)
Var = [ Σ R_u² v_u  +  (Σ R_u (1−w_u))² var(δ)  +  (τ_nat Σ R_u)² ] / (ΣV + ΣR)²
sd  = √Var · f(fração apurada)        f = 1,8 (<30%) · 1,4 (<50%) · 1,15 (<80%) · 1,0
IC95 = S ± 1,96 sd          P(A vence) = Φ((S − 0,5)/(k·sd)), k = 1,4        B = complemento
```
`drift_a` e `τ_nat` são substituídos pelo máximo entre a constante e o valor **medido** comparando o snapshot atual com o de ~60% do progresso (`estimar_deriva`): a banda só alarga, nunca estreita. A chance é exibida só a partir de 50% apurado (era 30% até 17/10), recortada em 1–99% (recorte só de exibição; o modelo é a normal acima).

**Não usa** extrapolação de tendência: votos que mudam ao longo da noite refletem *de onde* vêm as urnas, e isso já está nos estratos.

#### Origem de cada parâmetro

| Parâmetro | Valor | Origem |
|---|---|---|
| `drift_a`, `c`, `b` | 0,028 · 0,37 · 0,12 | Regressão ponderada em simulação (cenário "base", semente 99). **Sintético.** |
| `τ_p` | 0,025 | Heurístico (erro típico do 1T como guia do 2T por UF). |
| `τ_nat` | 0,010 | Heurístico. |
| `τ_sem_prior` | 0,10 | Heurístico. |
| `τ_swing` | 0,04 | Heurístico; a escolha da regra de estrato único foi decidida na semente 555 e conferida em 31337 (abaixo). |
| `f(fração)` | 1,8/1,4/1,15/1,0 | Escolhido olhando simulações base/hard — **sementes que também serviram de avaliação na época (vazamento)**. |
| `k` (só na chance) | 1,4 | Escolhido na semente 555 entre 1,0/1,4/1,7/2,0 (melhor Brier nos cenários hard e adverso); conferido na 31337 (tabela abaixo). |
| 10% / 50% | limiares | Heurísticos de produto. Chance subiu de 30% para 50% em 17/10 por causa da calibração nos cenários hard/adverso (tabela abaixo). |

**Nenhum parâmetro foi calibrado em eleição real.** O simulador usa eleitorado e voto por UF do 2T de 2022 e uma ordem regional de apuração Sul/Sudeste → Norte/Nordeste, mas a sequência real de parciais de 2022 não foi reproduzida.

#### Simulador e resultados (17/10/2026)

`scripts/validacao_2t/sim.py`: 28 estratos com seções em blocos; voto por bloco = logit(share da UF + choque nacional) + viés ligado à **posição na fila de apuração dentro da UF** (capital × interior) + ruído; comparecimento por bloco, correlacionado à ordem no N/NE; prior = share final − swing + ruído. Cenários: **base**; **hard** (viés intra-UF 2×, prior pior); **adverso** — criado depois do ajuste e **nunca usado para escolher nada**: viés intra-UF 3×, comparecimento ligado à ordem, prior pior (σ 5 pp), swing grande (σ 5 pp).

Medido só no que a tela mostra (≥30% apurado, 7 pontos de corte × 300 eleições = 2.100 previsões por cenário; pontos da mesma eleição são correlacionados, então o n efetivo é menor), semente de relatório 31337:

| Presidente | erro médio | IC95 contém o real | prev. 50–70% → real | prev. 70–90% → real | prev. 90–99% → real |
|---|---|---|---|---|---|
| base | 0,37 pp | 100% | 61% → 63% ±7 | 81% → 84% ±4 | 96% → 99% ±1 |
| hard | 0,68 pp | 99,2% | 61% → 59% ±7 | 81% → **72% ±5** | 96% → 98% ±1 |
| adverso | 0,99 pp | 98,2% | 60% → **54% ±6** | 82% → **68% ±4** | 96% → 96% ±2 |

Leitura: o **IC95 está conservador** (cobre mais que 95%) em todos os cenários. A **chance de vencer é bem calibrada no cenário base, mas fica confiante demais na faixa 60–90% quando há viés forte capital × interior** (hard/adverso). Acima de 90% está calibrada nos três.

Governador (estrato único, UFs AC/AM/DF/ES/RN/TO, disputas recentradas perto de 50%, 400 eleições, semente 31337), regra antiga → nova:

| | erro médio | Brier | prev. 70–90% → real |
|---|---|---|---|
| base | 0,79 → **0,72** pp | 0,047 → **0,044** | 81% → 93% / 96% (ambas subconfiantes) |
| hard | 1,48 → **1,28** pp | 0,078 → **0,070** | 81% → 78% / **85%** |
| adverso | 2,17 → **1,81** pp | 0,106 → **0,094** | 81% → 66% / **79%** |

**Chance a partir de 50% apurado, com `k`** (semente de relatório 31337, só ≥50%, 1.500 previsões por cenário), favorito previsto 70–90% → venceu:

| | k = 1,0 | k = 1,4 (atual) | Brier 1,0 → 1,4 |
|---|---|---|---|
| base | 82% → 79% | 82% → 90% (cauteloso) | 0,0270 → 0,0285 |
| hard | 81% → **71%** | 81% → 84% | 0,0441 → 0,0440 |
| adverso | 82% → **68%** | 81% → 81% | 0,0625 → 0,0611 |

Leave-one-out no swing (Presidente): efeito nulo dentro do erro de simulação → desligado (`DELTA_LOO = False`).

#### Teste de viés (18/10/2026)

`scripts/validacao_2t/vies.py`. Motor sem nenhuma alteração. Semente nova (2610), nunca usada em decisão; 2.000 eleições por cenário. Em cada ponto a projeção vê só o snapshot do instante, um anterior e o 1T; o resultado final só pontua. Eleitorado e total de seções por UF entram desde o início porque o TSE publica esses números com 0% apurado.

A = candidato forte no Nordeste/Norte (geografia de 2022); B = forte no Sul/Centro-Oeste. No simulador Sul e Sudeste apuram primeiro.

Cenários novos, com erro do 1T **por região** (todas as UFs da região juntas, o que o motor não modela: ele supõe erro independente por UF mais o swing nacional):
- **regional_aleatorio** / **adverso_regional**: cada região recebe um desvio aleatório de σ 3 pp na migração 1T→2T (sobre o base / sobre o adverso).
- **dirigido_pro_A** / **dirigido_pro_B**: S, SE e CO desviam 2 pp para um lado e N e NE 2 pp para o outro. O swing medido cedo (Sul) é o errado para o Norte/Nordeste. É um teste de estresse com sinal fixo, não um cenário provável.

Simetria da fórmula: trocar A e B em todas as 84.000 previsões dá o resultado espelhado (diferença máxima 2×10⁻¹¹). Isso prova só a simetria, não a ausência de viés empírico.

Erro assinado da estimativa de A (estimado − real, pp; positivo = superestima A), com IC95 entre eleições:

| cenário | 10% | 30% | 50% | 90% | IC95 cobre (50% / 90%) |
|---|---|---|---|---|---|
| base | +0,18 (±0,06) | +0,13 | +0,10 | +0,03 | 100% / 99,5% |
| hard | +0,18 (±0,12) | +0,13 | +0,10 | +0,03 | 98,8% / 95,5% |
| adverso | +0,17 (±0,17) | +0,12 | +0,09 | +0,04 | 97,8% / **91,6%** |
| regional_aleatorio | +0,12 | +0,09 | +0,07 | +0,02 | 99,6% / 96,7% |
| adverso_regional | +0,02 | +0,01 | +0,01 | +0,02 | 94,9% / **88,4%** |
| dirigido_pro_A | −0,46 | −0,28 | −0,20 | −0,04 | 99,8% / 99,1% |
| dirigido_pro_B | +0,82 | +0,55 | +0,39 | +0,10 | 98,8% / **91,7%** |
| base sem comparecimento ligado à ordem | −0,02 (±0,06) | | −0,00 | +0,00 | 100% / 99,8% |

Erro absoluto médio a 10% / 50% / 90%: base 1,14 / 0,46 / 0,10; adverso 3,19 / 1,24 / 0,27; dirigidos ~1,2–1,3 / ~0,5 / ~0,1.

Leitura:
- **O desvio de +0,1 a +0,18 pp para A nos cenários sem efeito regional vem de uma hipótese do simulador, não da fórmula**: no N/NE as seções que chegam por último têm comparecimento menor, e o motor estima os votos que faltam em cada UF pelo comparecimento já apurado. Desligando só esse termo o viés vai a −0,02 ± 0,06. Na eleição real o lado do viés depende de onde o comparecimento das seções tardias cai, não de qual candidato é.
- **Swing regional diferente do nacional**: com 4 pp de diferença entre quem apura cedo e quem apura tarde, o erro sistemático (descontado o +0,18 do base) é ±0,64 pp a 10%, ±0,30 a 50% e ±0,07 a 90%. É contido porque cada UF já tem parte apurada desde cedo e esses votos pesam na própria UF.
- **A margem não incorpora erro regional correlacionado** de forma explícita. Até 70% ela ainda cobre mais de 94% nos cenários regionais, porque já era conservadora. **A 90% a cobertura cai para 88–92%** nos cenários adversos e no dirigido_pro_B: banda estreita (fator 1,0) contra erro sistemático.

Chance de vencer, só nos pontos em que o site mostra (≥50% apurado, 6.000 previsões por cenário), probabilidade média do favorito × frequência real de vitória:

| cenário | geral | A favorito | B favorito | faixa 50–70% |
|---|---|---|---|---|
| base | 92,6 × 96,2 | 93,5 × 96,1 | 91,1 × 96,3 | 59,9 × 68,6 ±3,9 |
| hard | 90,7 × 92,8 | 92,0 × 93,9 | 88,6 × 91,0 | 60,4 × 58,9 ±3,6 |
| adverso | 88,8 × 89,4 | 90,4 × 91,7 | 86,2 × 85,8 | **60,0 × 54,8 ±3,3** |
| regional_aleatorio | 92,6 × 95,8 | 93,5 × 96,3 | 90,9 × 94,9 | 60,3 × 65,5 ±3,9 |
| adverso_regional | 88,8 × 89,3 | 90,2 × 92,4 | **86,3 × 84,1** | **60,6 × 55,4 ±3,2** |
| dirigido_pro_A | 92,4 × 95,8 | 93,1 × 97,9 | 91,4 × 92,6 | 60,2 × 65,5 ±3,9 |
| dirigido_pro_B | 92,8 × 94,9 | 93,7 × 93,1 | 91,1 × 98,3 | 60,2 × 59,1 ±4,3 |

Leitura: no agregado a chance é cautelosa em todos os cenários. O problema fica localizado: **na faixa 50–70% ela é confiante demais nos dois cenários adversos (diz 60%, acontece 55%)**. Quando a estimativa pende para um lado (dirigidos), a chance do favorecido fica perto do correto e a do outro fica cautelosa demais. O viés da estimativa não vira excesso de confiança para quem ele favorece nesses testes.

Limitações: o simulador é nosso (geografia 2022, ordem de apuração e efeitos regionais com tamanhos escolhidos, não medidos); as previsões da mesma eleição são correlacionadas (os IC95 são calculados por ponto de corte, entre eleições independentes); só Presidente; nada aqui substitui o backtest com seções reais abaixo, que também precisa medir se o comparecimento das seções tardias é de fato diferente.

#### Plano de validação retrospectiva (pós-eleição, sem vazamento)

1. **Dados**: arquivos públicos do TSE de 2018 e 2022 (dadosabertos.tse.jus.br) com resultado por seção nos dois turnos: votação por seção, boletins de urna e eleitorado por seção. Verificar se os boletins trazem horário de recebimento/totalização; se trouxerem, reconstruir a **ordem real** da apuração. Se não, usar ordens alternativas plausíveis (por zona e município, capital primeiro), marcadas como aproximação.
2. **Reconstrução**: em cada instante `t`, só a informação disponível em `t` (seções totalizadas até `t`; 1T completo como prior). Nada do resultado final entra.
3. **Separação**: ajustar constantes em **2018**; avaliar em **2022** sem tocar em nada. Depois do 2T de 2026, avaliar em 2026 como terceiro conjunto.
4. **Métricas separadas**: erro absoluto e **erro assinado** (com contagem de super/subestimação por candidato) do share final por % apurado; comparecimento das seções tardias × já apuradas por UF; cobertura empírica do IC95; calibração da probabilidade (diagrama de confiabilidade com intervalos, Brier); acerto do vencedor — com bootstrap por eleição para os intervalos.
5. **Comparação** de variantes nos mesmos instantes: atual × estratificação municipal (Governador e UFs grandes), medindo também custo (requisições por ciclo ao TSE).
6. Só então decidir constantes novas e a versão municipal.

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
