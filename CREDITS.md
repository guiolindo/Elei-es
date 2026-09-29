# Credits

## Fontes de dados

- **Tribunal Superior Eleitoral (TSE)** — dados públicos de apuração, candidatos, fotos. Endpoints `resultados.tse.jus.br` e `divulgacandcontas.tse.jus.br` sob a Lei de Acesso à Informação (Lei 12.527/2011).
- **Logos oficiais dos partidos políticos** — coletados dos sites institucionais dos próprios partidos e do TSE, usados em caráter nominativo (Lei 9.279/1996 permite uso pra identificação sem endosso).

## Bases legais e jurisprudência

- Constituição Federal — arts. 5º XIV, 28, 46 §2º, 77 §2º, 220.
- Lei 4.737/1965 (Código Eleitoral) — arts. 106-113.
- Lei 9.504/1997 (Lei das Eleições).
- Lei 12.527/2011 (LAI).
- Lei 12.965/2014 (Marco Civil da Internet).
- Lei 13.165/2015 (barreira 10% do QE).
- Lei 13.709/2018 (LGPD).
- Lei 14.208/2021 (federações partidárias).
- Lei 14.211/2021 (regra 80/20 das sobras).
- EC 97/2017.
- STF ADI 7228, ADI 7263, ADI 7325 (2024) — Fase 3 residual sem barreira do candidato.
- Resoluções TSE aplicáveis à Eleição de 2026.

## Bibliotecas Python

- **FastAPI** (Sebastián Ramírez) — framework web.
- **SQLAlchemy 2** — ORM.
- **asyncpg** — driver PostgreSQL async.
- **Alembic** — migrations.
- **Pydantic + pydantic-settings** — validação e config.
- **httpx** — cliente HTTP async.
- **slowapi** — rate limiting.
- **pywebpush** — Web Push (opcional).
- **pytest** — testes.

## Bibliotecas frontend

- **ECharts** (Apache) — gráficos e mapas geográficos.
- **Google Fonts** — Inter e JetBrains Mono.

## Ícones e design

- **Feather Icons** — inspiração pro estilo dos ícones SVG do sprite interno.
- **Design system próprio** — logo, tokens, motion, paleta.

## Ferramentas de dev

- **Docker & Docker Compose** — ambiente reproduzível.
- **Railway** — plataforma de deploy.
- **curl-cffi** — TLS fingerprint pro script Termux.

## Contribuidores

- Autor original e mantenedor: Guilherme.
- Assistência de código: Claude (Anthropic) via Claude Code.

## Auditoria

- QA sobre motor matemático (2026-09-29) — apontou 1 bug grave (`segundo_turno_definido`), 3 desatualizações legislativas (Senador 2026, Lei 14.211/2021, STF 2024) e otimizações. Todas as correções aplicadas.
- Verificação online contra fontes primárias — Portal STF, Senado Notícias, TRE-PR, Consultor Jurídico, Agência Brasil.

## Licença

Ainda a definir. Enquanto isso, código aberto pra leitura e inspeção pública.

Fotos e nomes de candidatos permanecem propriedade dos respectivos titulares e usados sob amparo LGPD art. 4º III (fins jornalísticos/informativos).

Logos partidários permanecem propriedade dos respectivos partidos e usados sob amparo Lei 9.279/1996 (uso nominativo).
