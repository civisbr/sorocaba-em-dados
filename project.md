# sorocaba-sp — "Sorocaba em Dados"

Hub de dados públicos de Sorocaba/SP. Agrega, em um único site estático e rápido, os
indicadores municipais que hoje estão espalhados por bases federais, estaduais e repositórios
CivisBR já existentes.

Repositório sob a org CivisBR. Marca pública anônima — ver `IDENTIDADE` no final.

## 0. Nomenclatura e URL

| | |
|---|---|
| Repositório | `civisbr/sorocaba-sp` |
| Nome do produto | **Sorocaba em Dados** |
| Assinatura | "Sorocaba em Dados — uma iniciativa CivisBR" |
| URL canônica | `civisbr.org/sorocaba-sp` |

Este repositório quebra deliberadamente o padrão `<tema>-<recorte>-<local>` dos demais repos
da org. Os outros são investigações temáticas; este é o guarda-chuva municipal que as agrega.
O padrão a replicar para novas cidades é `<municipio>-<uf>`.

Servir em **subdiretório** do domínio da org, nunca em subdomínio nem domínio próprio por
cidade — concentra autoridade de domínio em vez de fragmentá-la a cada município novo.

Em todo texto visível: o produto é "Sorocaba em Dados", nunca o slug do repositório. O
`<title>` de cada página segue `<Painel> em Sorocaba | Sorocaba em Dados` — o topônimo é o que
traz busca orgânica e precisa estar no título, não só na marca.

---

## 1. Objetivo e escopo

**Objetivo:** um cidadão de Sorocaba abre o site no celular, em 4G, e em menos de 2 segundos
encontra um dado que o ajuda a tomar uma decisão concreta hoje.

**Não é:** um portal de transparência, um dashboard de BI, um blog de análise. É uma camada de
tradução. Cada painel responde a *uma* pergunta prática.

**Escopo v1 — três painéis, nada além disso. Construir nesta ordem:**

| # | Painel | Pergunta que responde | Cadência |
|---|---|---|---|
| 1 | Emprego | O mercado de trabalho aqui está crescendo ou encolhendo, e em quê? | mensal |
| 2 | Combustível | Este posto é caro ou barato — e há quanto tempo? | semanal |
| 3 | Escolas | Como está a escola do meu bairro? | anual |

A ordem mudou após a verificação de fontes de 2026-10-11 (ver `docs/fontes.md`). Combustível
era a âncora original; descobriu-se que pelo menos dois serviços já republicam o LPC da ANP
com recorte de Sorocaba e preço por posto. Reimplementar isso seria gastar o início do
projeto onde o retorno marginal é menor.

**Regra que gerou essa troca, e que vale para todo painel novo:** antes de escrever ETL,
verificar quem já publica esse dado para o público geral. Se já existe equivalente bem-feito,
ou se acha um ângulo que ele não cobre, ou não se constrói. Essa checagem é item obrigatório
do Definition of Done (§10).

Painéis de saúde (SIH/CNES/SIM) ficam para o v2 — o lag de 2-3 meses e a necessidade de
ajuste por complexidade tornam a modelagem lenta demais para o v1. Não começar por eles.

**Escopo v2 — só depois dos três do v1 no estado do §10.** Fontes e status em `docs/fontes.md`
("Candidatos a v2"). Ordem sugerida:

| # | Item | Pergunta | Restrição de projeto |
|---|---|---|---|
| 4 ✔ | Perfil da cidade (IBGE) | Quanto a cidade tem de gente, área e economia? | Campo que o IBGE não publica fica `null`; sem PIB per capita calculado por conta própria |
| 5 ✔ | Representantes (TSE, Câmara, Alesp) | Quem governa e quem representa Sorocaba? | Eleito ≠ em exercício; deputado é do estado, então o recorte é "mais votados na cidade" com critério explícito; sem ranking nem juízo de mérito |
| 6 ✔ | Segurança (SSP-SP) | Que tipos de crime acontecem, quando e com que tendência? | Boletim mede registro, não crime. Decisão do responsável em 2026-10-11: ranking de bairros por contagem de roubos e furtos e mapa de calor são permitidos nesta página, com as ressalvas obrigatórias (contagem não é risco, depende de população, comércio e hábito de registrar; bairro digitado com grafias variadas). Estupros, mortes e tráfico só como série mensal da cidade inteira; hora, bairro e mapa só para roubos e furtos |
| 7 | Emendas com destino a Sorocaba | Que dinheiro federal e estadual chega à cidade? | Valores, autor, finalidade e status, sem adjetivo. Não classificar projeto de lei como "beneficia Sorocaba" automaticamente |
| 8 | Saúde (SIH/CNES/SIM) | — | Ver parágrafo acima |
| ✔ | Comparativo entre municípios (IBGE, INEP) | Em que posição Sorocaba está, e como isso mudou? | Posição é fato de tamanho, não de qualidade; empates explícitos; per capita só com população do mesmo ano |

Perfil e Representantes são conteúdo de referência de baixa cadência (anual e por eleição);
podem virar uma página "A cidade" em vez de painéis com workflow próprio.

---

## 2. Princípios não-negociáveis

Herdados do `CLAUDE.md` da CivisBR. Valem aqui sem exceção.

1. **Nunca fabricar dado.** Nenhum número no site pode existir sem origem rastreável até o
   arquivo bruto baixado da fonte. Sem exceção para "placeholder", "exemplo" ou "só para o
   layout". Use `null` e renderize estado vazio.
2. **Todo dado é flagueado** como `real`, `estimativa` ou `pendente`. O flag é parte do schema
   e é visível na UI, não só no JSON.
3. **Todo número exibido carrega data de referência e link para a fonte primária.** Dado sem
   data de referência não entra na build — é erro de validação, não warning.
4. **Pipeline determinístico e offline.** Rodar o ETL duas vezes sobre o mesmo snapshot bruto
   produz bytes idênticos. Nenhum `datetime.now()` dentro da lógica de transformação; o
   timestamp entra via parâmetro explícito.
5. **Nunca derivar e publicar ranking de qualidade a partir de dado que não suporta ranking.**
   Volume é volume; desfecho exige ajuste de risco. Na dúvida, publique o dado cru e explique.

---

## 3. Stack

**Python para todo o ETL.** Sem Ruby neste repositório — Ruby entra apenas em projetos que
usam Rails, e aqui não há backend nem banco em produção.

```
uv                 gerenciamento de pacotes e venv
polars             transformação (preferir sobre pandas)
duckdb             joins e agregações pesadas, leitura de parquet
httpx              requests HTTP
selectolax         parsing de HTML (preferir sobre BeautifulSoup por performance)
pydantic           validação de schema na fronteira de saída
jinja2             renderização dos templates HTML no build
pytest             testes
playwright         só se alguma fonte exigir render de JS; evitar
```

Frontend: HTML + CSS + JS vanilla. **Sem build step, sem framework, sem bundler.** Gráficos
gerados como SVG no build (Python → Jinja2), não bibliotecas client-side. JS só para
interação que realmente exige (busca, filtro, ordenação de tabela).

Deploy: GitHub Actions → GitHub Pages.

---

## 4. Arquitetura

```
fontes públicas
     │
     ▼
scripts/fetch_*.py      baixa bruto, salva com hash, NÃO transforma
     │
     ▼
data/raw/               snapshot imutável, versionado por data (gitignored se > 50MB)
     │
     ▼
scripts/build_*.py      transforma, valida, flagueia
     │
     ▼
data/public/*.json      contrato estável, commitado SEMPRE
     │
     ▼
scripts/render.py       Jinja2 → dist/
     │
     ▼
dist/                   site estático → Pages
```

**A separação fetch/build é obrigatória.** Fetch toca a rede e nada mais. Build é puro e
testável sem rede. Isso é o que permite rodar o pipeline inteiro offline em CI e em teste.

**`data/public/*.json` é commitado a cada execução.** Isso não é poluição de histórico — é o
ativo do projeto. Em dois anos o git log desses arquivos é uma série histórica municipal que
não existe organizada em lugar nenhum, nem na prefeitura.

### Reuso dos repos CivisBR existentes

`medicamentos-sus-sorocaba-sp` e `repasses-saude-sorocaba-sp` já publicam JSON. Este hub
**consome** esses artefatos pela URL pública do Pages/raw e os renderiza como cards de entrada.
Não reimplementar o ETL deles aqui. Se o schema de origem divergir do contrato da seção 5,
escrever um adaptador fino em `scripts/adapters/`, nunca editar o repo de origem para servir
a este.

---

## 5. Contrato de dados

Todo arquivo em `data/public/` segue esta envelope. Validado com pydantic antes de escrever;
falha de validação quebra a build.

```json
{
  "schema_version": "1.0",
  "painel": "combustivel",
  "fonte": {
    "nome": "ANP — Levantamento de Preços de Combustíveis",
    "url": "https://...",
    "licenca": "...",
    "acesso_em": "2026-10-11"
  },
  "referencia": {
    "inicio": "2026-10-05",
    "fim": "2026-10-11",
    "granularidade": "semanal"
  },
  "cobertura": {
    "municipio": "Sorocaba",
    "ibge": "3552205",
    "uf": "SP"
  },
  "qualidade": {
    "flag": "real",
    "n_registros": 142,
    "notas": ["3 postos sem informação de bandeira"]
  },
  "dados": []
}
```

Regras:
- `flag` em `qualidade` é `real` | `estimativa` | `pendente` e vale para o arquivo inteiro.
  Registro individual pode ter `flag` próprio que sobrescreve.
- `dados` é sempre uma lista de objetos planos. Sem aninhamento profundo, sem chaves
  dinâmicas — o frontend não deve precisar de lógica para interpretar a forma.
- Nomes de campo em português, snake_case. O público-alvo e quem vai auditar são brasileiros.

---

## 6. Fontes por painel

### 6.1 Emprego — `scripts/fetch_caged.py` — PAINEL ÂNCORA

Novo CAGED, microdados mensais no FTP do MTE. Filtrar por `município == 355220` (IBGE sem
dígito verificador; o 3552205 vale só no campo `ibge` do envelope).

Saída: `data/public/emprego.json` — saldo mensal (admissões − desligamentos), quebra por
seção CNAE, faixa salarial de admissão, série de 24 meses.

Cuidado: o CAGED tem ajustes retroativos que alcançam 12 meses (FOR) e anos (EXC). Saldo =
MOV + FOR − EXC por `competênciamov`; a janela de 24 meses exige as declarações de todos os
meses desde o início dela. Detalhes e números em `docs/fontes.md`.

Fonte verificada em 2026-10-11. A checagem de concorrência tem uma ressalva aberta (painel
Power BI do MTE não confirmado), registrada em `docs/fontes.md`.

### 6.2 Combustível — `scripts/fetch_anp.py`

Fonte **verificada como viável** (`docs/fontes.md`): Sorocaba está na amostra do LPC da ANP,
inclusive na sub-amostra de GLP, com algo entre 26 e 41 postos pesquisados. Série histórica
por revenda em CSV semestral, licença Creative Commons Attribution, com CNPJ, razão social,
endereço, bandeira, produto, preço e data da coleta.

**Ângulo obrigatório: série histórica, não cotação.** Os agregadores existentes mostram o
preço da semana. O que eles não mostram — e o que este repositório acumula de graça, porque
commita `data/public/` a cada execução — é a trajetória: um posto consistentemente acima da
mediana da cidade, a dispersão entre o mais caro e o mais barato ao longo do tempo, o
repasse (ou não) de reduções de preço na refinaria para a bomba. Construir o painel em torno
disso. Se o painel sair como tabela de preços da semana, ele não deveria ter sido construído.

**Restrição de linguagem não-negociável:** a ANP pesquisa por amostragem, algumas dezenas de
postos numa cidade com centenas. Nunca escrever "o posto mais barato de Sorocaba". Sempre
"o mais barato entre os N postos pesquisados pela ANP na semana de DD/MM". Isso vai no
template, não fica a cargo de quem escreve o copy.

**Bloqueio resolvido (2026-10-11):** Sorocaba segue na amostra (24 CNPJs, coleta de 08/10/2026).
O fetch usa os arquivos "últimas 4 semanas" (gasolina/etanol e diesel/GNV); o histórico se forma
pela acumulação de instantâneos em `data/raw/anp/`. Produtos no painel: gasolina comum, etanol e
diesel S10. Diesel tem 10–13 postos por semana, abaixo do piso de 15, e a página avisa.

**Risco estrutural:** o LPC encolheu de 459 para 390 municípios em jun/2025 por
contingenciamento orçamentário, e já havia encolhido antes. A fonte pode sumir por decisão
federal, não por falha técnica. O painel degrada mostrando a última referência válida com a
data — nunca interpola, nunca troca silenciosamente para média estadual.

Saída: `data/public/combustivel.json` — postos com preço por produto, posição relativa
(percentil) na cidade, e série temporal por CNPJ.

### 6.3 Escolas — `scripts/fetch_inep.py`

INEP: IDEB por escola + Censo Escolar (matrículas, infraestrutura, docentes). Ambos têm
código de município e código INEP da escola.

Saída: `data/public/escolas.json` — uma entrada por escola em Sorocaba, com IDEB (anos
iniciais e finais), rede, matrículas, e indicadores de infraestrutura.

**Não construir ranking geral de escolas.** IDEB correlaciona fortemente com perfil
socioeconômico do alunado; um ranking cru penaliza escola de periferia e premia escola que
seleciona aluno. Exibir por proximidade e por rede, com o IDEB como um dado entre outros e
uma nota explicando a limitação. Esta regra não é negociável por "mas fica mais atraente".

Concorrência: QEdu e similares já cobrem IDEB por escola. Registro e ângulo (sem ranking, ano em cada
dado, dado aberto) em `docs/fontes.md`; a ressalva de reavaliação continua lá.

---

## 7. Estrutura de diretórios

```
sorocaba-sp/
├── project.md              este arquivo
├── pyproject.toml          uv
├── docs/
│   └── fontes.md           catálogo de fontes, verificações, limitações conhecidas
├── scripts/
│   ├── fetch_anp.py
│   ├── fetch_caged.py
│   ├── fetch_inep.py
│   ├── adapters/           normalizadores dos JSONs de outros repos CivisBR
│   ├── build.py            orquestra transformação → data/public/
│   ├── render.py           Jinja2 → dist/
│   └── charts.py           geradores de SVG
├── schemas/                modelos pydantic do contrato da seção 5
├── templates/
│   ├── base.html
│   └── paineis/
├── static/
│   ├── style.css
│   └── app.js
├── data/
│   ├── raw/                snapshots brutos
│   └── public/             JSONs publicados — COMMITAR SEMPRE
├── tests/
└── .github/workflows/
    ├── combustivel.yml     semanal
    ├── emprego.yml         mensal
    └── deploy.yml          após qualquer atualização de data/public/
```

---

## 8. Frontend — restrições

Orçamento de performance, medido em throttling 4G / Moto G de entrada:

- First Contentful Paint < 1.2s
- Página completa < 150KB (incluindo fontes; preferir system font stack e não carregar
  webfont nenhuma)
- Lighthouse Performance e Accessibility ≥ 95
- **Funciona com JS desabilitado.** Os números e os gráficos SVG são renderizados no build.
  JS adiciona filtro e ordenação, nunca é pré-requisito para ler o conteúdo.

Design: limpo, alto contraste, tipografia grande. O público que mais precisa desse dado lê em
tela pequena, com luz do sol, em conexão ruim. Densidade de informação é inimiga aqui — um
número grande, uma frase de contexto, o detalhamento abaixo.

Cada painel tem rodapé obrigatório: fonte, data de referência, data de coleta, link para o
JSON bruto, link para o script que o gerou.

---

## 9. GitHub Actions

- Um workflow por fonte, agendado conforme a cadência real da fonte (não rodar diário o que
  atualiza mensal — gera commit vazio e ruído).
- O job faz: fetch → build → validar → `git diff --exit-code data/public/` → se mudou,
  commitar e disparar deploy.
- **Falha de fetch não quebra o site.** O JSON anterior continua servido. O job abre issue
  automática e o painel exibe a data de referência antiga, que já é obrigatória pela seção 2.
- Rate limit e retry com backoff em toda chamada a servidor gov.br — eles são instáveis em
  horário comercial.

---

## 10. Definition of done (por painel)

Um painel só é considerado pronto quando:

- [ ] Fonte verificada e documentada em `docs/fontes.md` com status `verificada`, incluindo
      limitações conhecidas
- [ ] **Checagem de concorrência feita e registrada**: quem já publica esse dado para o
      público geral, e qual é o ângulo que este painel cobre e o outro não. Sem resposta a
      isso, não começar o ETL
- [ ] `fetch_*.py` roda isolado e salva bruto sem transformar
- [ ] `build` roda offline a partir do bruto e é determinístico (teste que roda duas vezes e
      compara hash)
- [ ] Saída valida contra o schema pydantic
- [ ] Teste com snapshot real pequeno em `tests/fixtures/`
- [ ] Workflow agendado e com tratamento de falha
- [ ] Página renderiza sem JS
- [ ] Rodapé com proveniência completa
- [ ] Lighthouse ≥ 95 em mobile

---

## 11. O que NÃO fazer

- Não adicionar um quarto painel antes dos três estarem no estado acima. O modo de falha
  deste tipo de projeto é dez painéis pela metade.
- Não criar backend, banco de dados, autenticação ou API em runtime. Se parecer necessário,
  a resposta é um JSON estático a mais.
- Não fazer fetch de fonte governamental no browser. Nenhuma delas manda CORS e todas caem.
- Não usar biblioteca de gráfico client-side para o que pode ser SVG no build.
- Não raspar o site da prefeitura no v1. Scraping de portal municipal quebra a cada
  redesign e vai consumir o tempo que deveria ir para os painéis que importam.
- Não redistribuir dado da EMTU sem ler os termos — o acesso exige cadastro e proíbe venda e
  sublicenciamento.

---

## IDENTIDADE

Repositório público `civisbr/sorocaba-em-dados`, com autoria `CivisBR <compact.chipmunk.sqpx@mask.me>` em todos os commits (autor e committer). Nunca usar a identidade pessoal nesta org.

```bash
git config user.name  "<identidade CivisBR>"
git config user.email "<email CivisBR>"
```

Config **por repositório**, nunca global. Verificar com `git log --format='%an <%ae>'` antes
do primeiro push. Checar também que nenhum caminho absoluto com nome de usuário vazou para
dentro de arquivo commitado.
