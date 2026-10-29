# Auditoria dos boletins de urna do 2º turno de 2026 (Presidente)

Feita em 29/10/2026 com os arquivos públicos do TSE, baixados seção por seção de
`resultados.tse.jus.br/oficial/ele2026/arquivo-urna/3221`. Os scripts estão em
`scripts/validacao_2t/` e qualquer pessoa pode refazer tudo.

Régua: cada teste também rodou no 2º turno de 2022. Uma coisa só conta como
anomalia se for diferente do que acontece normalmente numa eleição.

## Conclusão

Não apareceu nenhum sinal de fraude. A soma dos boletins bate voto por voto com o
resultado oficial. Em 17.350 seções verificadas a fundo, os arquivos estão íntegros
e a recontagem voto a voto pelo RDV deu exatamente o BU em todas. Os pontos fora do
comum têm explicação conhecida e aparecem do mesmo jeito em 2022. As urnas que
ficaram abertas até 19h e os eleitores liberados sem digital não pendem para
nenhum lado.

## 1. Soma

| | Boletins somados | Oficial TSE |
|---|---|---|
| Lula (13) | 64.256.232 | 64.256.232 |
| Flávio Bolsonaro (22) | 59.826.041 | 59.826.041 |
| Brancos | 1.430.496 | |
| Nulos | 2.723.305 | |
| Comparecimento | 128.236.074 de 158.745.079 aptos | |

São 499.207 boletins, contra 499.206 seções no 1º turno. Nenhum boletim tem mais
votos que comparecimento, nem mais comparecimento que eleitores aptos. Nenhuma urna
abriu antes da hora, e nenhum BU foi emitido antes de a urna fechar. 29 seções do
exterior foram apuradas pelo Sistema de Apuração, o que é normal quando a urna
falha ou a votação é em cédula.

## 2. Integridade dos arquivos (amostra de 17.350 seções)

A amostra juntou três grupos:

- 10.000 seções sorteadas;
- todas as 7.089 urnas que fecharam depois das 18h;
- todas as seções que os testes estatísticos apontaram: 100% num candidato,
  virada brusca, salto de eleitor sem digital e comparecimento muito alto.

Para cada seção foram baixados o BU, o RDV (registro de cada voto, embaralhado),
o log da urna e o arquivo de assinaturas (vota.vsc).

| Verificação | Resultado |
|---|---|
| SHA-512 do BU igual ao gravado pela urna | 17.350 de 17.350 |
| SHA-512 do RDV igual ao gravado pela urna | 17.350 de 17.350 |
| SHA-512 do log igual ao gravado pela urna | 17.350 de 17.350 |
| Recontagem do RDV voto a voto = BU | 17.350 de 17.350 |
| Votos computados no log = comparecimento do BU | 17.350 de 17.350 |
| Voto antes das 8h ou depois do encerramento | 0 |
| Dois votos com menos de 15 s entre eles | 0 (o menor intervalo foi 18 s) |

O sorteio de 10.000 seções tem uma consequência prática. Se o RDV não batesse com
o BU em 150 seções ou mais (0,03% do total), a chance de nenhuma cair na amostra
seria menor que 5%. Para mudar uma diferença de 4,4 milhões de votos seria preciso
mexer em milhares de seções.

94 seções tiveram troca de urna durante a votação: a urna reserva recebe os votos
já gravados e guarda o log da anterior. Juntando os logs, todas batem com o BU.

Limite: a assinatura de hardware da urna (ECDSA, 132 bytes) não traz o certificado
público no arquivo, então quem está fora do TSE não consegue validar quem assinou.
O que se prova aqui é que BU, RDV e log são coerentes entre si e com os hashes que a
própria urna gravou.

## 3. Votos depois das 17h e prorrogação

| | 2026 | 2022 |
|---|---|---|
| Urnas que fecharam entre 18h e 19h | 2.722 | 100 |
| Urnas que fecharam depois das 19h | 4.359 | 20 |

As urnas que fecharam tarde ficam quase todas nas capitais onde a votação foi
prorrogada: Rio de Janeiro (2.149), São Paulo (1.661), Salvador (755), outras cidades
do RJ, João Pessoa e Recife.

O log mostra quantos votos entraram de fato depois de cada horário:

| | Votos |
|---|---|
| Depois das 18h, somando as 7.089 urnas que fecharam tarde | 1.993 |
| Depois das 19h | 11 |
| Depois das 17h, estimado para o país inteiro pelo sorteio | cerca de 36 mil (0,03%) |

Nas urnas que fecharam tarde, o último voto saiu em média 2 horas antes do
fechamento. A urna ficou aberta esperando, mas quase ninguém chegou.

As urnas que fecharam tarde também não se comportaram diferente das urnas da mesma
cidade que fecharam no horário. A mudança de voto entre o 1º e o 2º turno nelas foi
−0,02 ponto para Lula, dentro da margem de erro. O comparecimento subiu 0,16 ponto a
mais, o esperado de quem teve mais tempo para votar.

O RDV não guarda horário e o log não guarda em quem se votou, por causa do sigilo do
voto. Por isso não existe como saber em quem votaram os eleitores depois das 17h.

## 4. Seções com 100% para um candidato

| | 2026 | 2022 |
|---|---|---|
| 100% Lula (20+ votos válidos) | 103 | 137 |
| 100% para o outro finalista | 4 | 2 |
| 95% ou mais para Lula | 1.746 | 2.466 |
| 95% ou mais para o outro finalista | 41 | 22 |

Todas as 107 seções com 100% já davam 90% ou mais para o mesmo lado no 1º turno de
2026. Das que existiam em 2022, 64 de 65 também. A maioria fica no AM, MA, PA, RR
e TO, onde há muitas aldeias e comunidades que votam em bloco. É padrão.

## 5. Mesma seção, 1º × 2º turno (virada brusca)

O país inteiro se moveu entre os turnos, com +2,9 pontos para Lula entre os dois
finalistas. Por isso cada seção foi comparada com as vizinhas da mesma zona
eleitoral.

| Seções que fugiram da zona em | 2026 | 2022 |
|---|---|---|
| 10 pontos ou mais | 172 (97 para Lula, 75 para Flávio) | 187 |
| 20 pontos ou mais | 7 | 11 |
| 30 pontos ou mais | 3 | 7 |

O desvio típico foi de 2,06 pontos em 2026 e 2,01 em 2022. As maiores viradas estão
em seções pequenas do Acre e do Amazonas, e algumas são as mesmas seções que viraram
em 2022 (AC 1139/7/67, AC 1031/3/95). Todas as seções com virada de 10 pontos ou
mais estão na amostra de integridade, e todas passaram na recontagem do RDV.

## 6. Eleitores liberados sem digital

| | |
|---|---|
| Total no 1º turno (mesmas seções) | 8.340.790 |
| Total no 2º turno | 8.630.930 (6,75% do comparecimento) |
| Correlação entre o salto de liberação sem digital e a mudança de voto | −0,001 (nenhuma) |
| 56 seções com salto de 20 pontos ou mais acima da zona | mudança de voto +0,13 ponto, dentro da margem |
| 96 seções com metade ou mais sem digital | mudança de voto −0,01 ponto |

Nos saltos grandes, como uma seção que passou de 16% para 94% sem digital, o mais
provável é leitor biométrico com defeito naquele dia. O voto nessas seções se moveu igual ao
das vizinhas.

## 7. Comparecimento

63 seções tiveram 98% ou mais de comparecimento, contra 15 em 2022. 52 delas já
tinham 95% ou mais no 1º turno. São seções pequenas, com mediana de 116 eleitores, e
o voto nelas mudou menos que a média nacional (+0,95 ponto contra +2,9). O
comparecimento por seção teve desvio de 2,15 pontos em relação à zona, parecido com
os 1,95 de 2022.

## Como refazer

```bash
python scripts/validacao_2t/baixar_bu_secoes.py PASTA/t2 ac al am ... zz   # BUs seção a seção
# juntar PASTA/t2/2t_*.csv em PASTA/2026_2t.csv
python scripts/validacao_2t/auditoria_bu.py PASTA 2026 --ref 2022
python scripts/validacao_2t/auditoria_extra.py PASTA 2026 --ref 2022
python scripts/validacao_2t/amostra_integridade.py PASTA amostra.csv 10000
python scripts/validacao_2t/verificar_integridade.py amostra.csv resultado.csv
```

O 1º turno de 2026 e os dois turnos de 2022 vêm do dados abertos do TSE pelo
`baixar_bu.py`.
