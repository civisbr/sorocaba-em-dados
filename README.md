# Sorocaba em Dados

Dados públicos de Sorocaba/SP em um site estático, leve e com fonte à vista. Uma iniciativa [CivisBR](https://github.com/civisbr).

**Site:** https://civisbr.github.io/sorocaba-em-dados/

## Painéis

| Painel | Pergunta | Fonte | Atualização |
|---|---|---|---|
| [Emprego](https://civisbr.github.io/sorocaba-em-dados/emprego/) | Sorocaba está gerando mais ou menos empregos? | Novo CAGED (MTE) | mensal |
| [Combustível](https://civisbr.github.io/sorocaba-em-dados/combustivel/) | Como os preços mudam ao longo do tempo? | Levantamento de Preços de Combustíveis (ANP) | semanal |
| [Escolas](https://civisbr.github.io/sorocaba-em-dados/escolas/) | O que os dados mostram sobre cada escola? | Censo Escolar e IDEB (INEP) | anual |
| [Representantes](https://civisbr.github.io/sorocaba-em-dados/representantes/) | Quem governa e quem representa Sorocaba? | TSE, Câmara dos Deputados e Alesp | por eleição |
| [Segurança](https://civisbr.github.io/sorocaba-em-dados/seguranca/) | Que ocorrências são registradas, quando e com que tendência? | SSP-SP | mensal |
| [Comparativo](https://civisbr.github.io/sorocaba-em-dados/comparativo/) | Em que posição Sorocaba está entre os municípios, e como isso mudou? | IBGE e INEP | anual |
| [Clima](https://civisbr.github.io/sorocaba-em-dados/clima/) | Como é o clima e o que esperar nesta semana? | INMET e Open-Meteo (ERA5) | diária (previsão) |
| [A cidade](https://civisbr.github.io/sorocaba-em-dados/cidade/) | Qual o tamanho da cidade, em gente e economia? | Censo 2022, estimativas e PIB (IBGE) | anual |

Cada painel mostra a fonte primária, a data de referência, a data da coleta e as limitações conhecidas. Os dados publicados ficam em `data/public/*.json` e também são servidos pelo site em `/data/`.

## Princípios

1. **Nenhum número sem origem.** Todo valor é rastreável até o arquivo baixado da fonte. O que a fonte não publica fica vazio ou `pendente`, nunca estimado em silêncio.
2. **Todo dado é classificado** como `real`, `estimativa` ou `pendente`, e isso aparece na interface.
3. **Data de referência obrigatória.** Dado sem ela não entra no build.
4. **Pipeline determinístico e offline.** Rodar o build duas vezes sobre o mesmo bruto gera bytes idênticos. A data de coleta entra por parâmetro, não pelo relógio.
5. **Sem ranking onde o dado não suporta.** Escolas não são ordenadas por IDEB. Combustível é sempre "entre os N postos pesquisados pela ANP", nunca "o mais barato da cidade".

## Como funciona

```
fetch (só rede)  →  data/raw/  →  build (puro, offline)  →  data/public/*.json  →  render  →  dist/
```

- `scripts/fetch_*.py` baixam da fonte e guardam apenas o recorte de Sorocaba, com hash no manifesto. Não há microdado individual no repositório.
- `scripts/build_*.py` transformam o bruto em JSON validado pelo contrato em `schemas/envelope.py`.
- `scripts/render.py` gera o HTML estático (Jinja2) e os gráficos em SVG. O site funciona sem JavaScript; a busca é um acréscimo opcional.
- Workflows em `.github/workflows/` atualizam os dados no agendamento, rodam os testes e publicam no GitHub Pages.

| Fonte | Coleta | Observação |
|---|---|---|
| CAGED | FTP do MTE, janela de 24 meses | saldo = movimentações + fora de prazo − exclusões, por competência |
| ANP | CSV "últimas 4 semanas" | o histórico se forma acumulando as coletas |
| INEP | zips de IDEB por escola e Censo Escolar | o servidor não envia o certificado intermediário; ele está em `certs/` e a cadeia TLS segue validada |

Detalhes, verificações e limitações de cada fonte estão em [`docs/fontes.md`](docs/fontes.md). A especificação do projeto está em [`project.md`](project.md).

## Rodando localmente

Requer Python 3.12+ e [uv](https://docs.astral.sh/uv/).

```bash
uv sync
uv run pytest -q

# atualizar dados (rede)
uv run python -m scripts.fetch_caged --auto 24 --acesso-em "$(date -u +%F)"
uv run python -m scripts.fetch_anp   --acesso-em "$(date -u +%F)"
uv run python -m scripts.fetch_inep  --acesso-em "$(date -u +%F)"
uv run python -m scripts.fetch_perfil --acesso-em "$(date -u +%F)"
uv run python -m scripts.fetch_comparativo --acesso-em "$(date -u +%F)"
uv run python -m scripts.fetch_ssp --acesso-em "$(date -u +%F)"  # baixa ~1 GB da SSP-SP
uv run python -m scripts.fetch_representantes --acesso-em "$(date -u +%F)"  # baixa ~1 GB do TSE

# transformar e gerar o site (offline)
uv run python -m scripts.build_emprego
uv run python -m scripts.build_combustivel
uv run python -m scripts.build_escolas
uv run python -m scripts.build_perfil
uv run python -m scripts.build_comparativo
uv run python -m scripts.build_seguranca
uv run python -m scripts.build_representantes
uv run python -m scripts.render

python3 -m http.server --directory dist 8080
```

## Estrutura

```
data/raw/        recortes de Sorocaba + manifestos com hash
data/public/     JSON publicado, um por painel
schemas/         contrato dos dados (pydantic)
scripts/         fetch, build e render
templates/       HTML (Jinja2)
static/          CSS e JS
tests/           testes, incluindo determinismo e orçamento de peso por página
docs/fontes.md   catálogo e verificação das fontes
```

## Próximos passos

Emendas e saúde estão registrados como v2 em `project.md`. O painel de Emprego ainda não mostra faixa salarial: falta uma tabela de salário mínimo com fonte, e o site não estima esse valor.

## Contribuindo

Abra uma issue ou um pull request. O CI roda os testes e o render em todo PR. Mudanças que exibam números novos precisam citar a fonte primária e a data de referência.

## Licença e dados

Os dados pertencem às fontes originais e seguem as licenças delas, citadas em cada painel. A licença do código ainda não foi definida.
