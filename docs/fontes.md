# Catálogo de fontes — Sorocaba em Dados

Registro de verificação de cada fonte antes da implementação. Nenhum painel entra em
desenvolvimento sem uma entrada aqui com status `verificada`.

Convenção de status: `verificada` | `parcial` | `rejeitada` | `pendente`.

---

## ANP — Levantamento de Preços de Combustíveis (LPC)

**Status:** `verificada` em 2026-10-11 contra o CSV primário (ver "Verificação no dado
primário"). Posicionamento do painel mudou: ver "Conclusão" abaixo.

**Verificado em:** 2026-10-11

### Verificação no dado primário (2026-10-11)

`www.gov.br` responde a `curl` apenas com `User-Agent` de navegador; sem ele, 403. Arquivo
`.../dados-abertos/arquivos/shpc/qus/ultimas-4-semanas-gasolina-etanol.csv` (8 MB, UTF-8 com
BOM, separador `;`, decimal com vírgula):

- Sorocaba **presente**: 208 linhas, **24 CNPJs distintos** em 14/09 a 09/10/2026.
- Coleta mais recente em Sorocaba: **08/10/2026**. A hipótese 3 (saída da amostra) está
  refutada para o recorte de gasolina/etanol. Diesel/GNV e GLP têm arquivos próprios, não
  checados.
- Colunas: `Regiao - Sigla;Estado - Sigla;Municipio;Revenda;CNPJ da Revenda;Nome da Rua;
  Numero Rua;Complemento;Bairro;Cep;Produto;Data da Coleta;Valor de Venda;Valor de Compra;
  Unidade de Medida;Bandeira`. Há `Bairro`, o que viabiliza recorte por bairro.
- Contagem de 24 postos é inferior ao 26–41 do agregador, como esperado para 4 semanas de um
  produto; confirma o alerta de não usar o agregador como fonte.
- Padrão de nome dos semestrais: `dsas/ca/ca-AAAA-0S.csv` confirmado até 2021-02. Os arquivos de
  2022 em diante não seguem esse padrão na página; **descobrir os nomes antes de importar
  histórico**. Para o ETL semanal, o arquivo "últimas 4 semanas" basta e o histórico passa a
  ser acumulado pelo commit de `data/public/`.

### Sorocaba está na amostra?

**Sim.** Confirmado indiretamente via agregador que republica o LPC (numerando.com.br), que
exibe dados de Sorocaba com postos nominais, bandeira, endereço e preço individual.

Sorocaba aparece também com **preço de GLP (botijão 13 kg)**, o que significa que está na
sub-amostra de GLP — que cobre apenas 175 dos 390 municípios do levantamento. Isso é um sinal
de que Sorocaba é tratada como praça relevante e tem probabilidade menor de ser cortada em
contingenciamentos futuros.

### Tamanho da amostra

Entre **26 e 41 postos**, dependendo de qual contagem da página do agregador se olha (a
própria página é internamente inconsistente: afirma 41 pesquisados, lista 26 nominalmente e
plota 30 no mapa).

Acima do piso de ~15 postos definido no `project.md` §6.1, portanto o painel é viável do ponto
de vista amostral.

**A contagem exata precisa ser confirmada contra o CSV primário da ANP**, não contra o
agregador. A inconsistência do agregador é exatamente o motivo pelo qual a regra de nunca
consumir dado de segunda mão existe neste projeto.

### Amostra ≠ censo — restrição de linguagem obrigatória

Sorocaba tem várias centenas de postos. A ANP pesquisa algumas dezenas, por amostragem com
roteiro de coleta definido pela contratada.

Logo o site **nunca** pode afirmar "o posto mais barato de Sorocaba". A formulação correta é
**"o mais barato entre os N postos pesquisados pela ANP na semana de DD/MM"**. Afirmar o
contrário é erro factual e expõe o projeto a contestação justa de posto não pesquisado.

Essa restrição vai no template, não só na cabeça de quem escrever o copy.

### Data de referência — PENDÊNCIA ABERTA

O dado mais recente observado no agregador tem coleta em **21/08/2026** — cerca de 7 semanas
antes desta verificação. Três hipóteses, não resolvidas:

1. O agregador está desatualizado.
2. A ANP está com atraso de publicação.
3. Sorocaba saiu da amostra depois de agosto/2026.

**A hipótese 3 é eliminatória para o painel e precisa ser checada primeiro**, direto no CSV da
ANP, antes de escrever qualquer linha de `fetch_anp.py`.

### Histórico de cortes orçamentários — risco estrutural da fonte

O LPC vem encolhendo de forma consistente por restrição orçamentária:

| Período | Municípios | Coletas semanais (automotivos) |
|---|---|---|
| 2003–2007 (pico) | 555 | — (22.880 postos no período) |
| até jun/2024 | 459 | 5.450 |
| jul/2024 | 358 | 6.255 |
| a partir de 15–22/jun/2025 | **390** (máx.) | 4.831 |

Fonte dos números: Agência iNFRA e IstoÉ, reportando comunicado da ANP sobre adaptação ao
Decreto 12.477/2025.

**Implicação de projeto:** a fonte é instável por decisão orçamentária federal, não por falha
técnica. O painel precisa degradar com elegância — se Sorocaba sair da amostra numa semana, a
página mostra a última referência válida com a data, nunca interpola e nunca substitui por
média estadual sem dizer que mudou de granularidade.

### Acesso aos dados

- Série histórica por revenda, CSV, licença Creative Commons Attribution.
- Campos relevantes confirmados nos metadados da ANP: CNPJ da revenda, razão social, município,
  endereço/logradouro, bandeira, produto, preço, data da coleta.
- Padrão de URL: `.../dados-abertos/arquivos/shpc/dsas/ca/ca-<ano>-<semestre>.csv`
  (`ca` = combustíveis automotivos; existe trilha equivalente para GLP).
- Metadados: `.../dados-abertos/arquivos/shpc/metadados-serie-historica-precos-combustiveis.pdf`

Nota operacional: o arquivo é semestral e acumulativo. Baixar o semestre inteiro e filtrar por
município é mais simples e mais robusto do que tentar pegar recorte semanal.

### Concorrência — descoberta que muda o posicionamento

Durante a verificação apareceram **pelo menos dois serviços que já republicam o LPC com
recorte municipal e preço por posto**:

- `numerando.com.br/combustiveis/cidade/sorocaba-sp` — página dedicada a Sorocaba, com lista
  nominal de postos, mapa, média/mediana/mín/máx por combustível.
- `atlaspublico.com.br/infograficos/precos-do-combustivel/...` — infográficos de preço por
  município.

Ou seja: o painel de combustível, como especificado no `project.md`, **não é diferenciado**.
É reimplementação de algo que já existe e já está indexado no Google para a consulta exata que
o painel pretendia capturar.

### Conclusão e recomendação

1. **A fonte é válida e o painel é tecnicamente viável.** Amostra suficiente, dado por posto,
   licença permissiva.
2. **Mas ele não deve ser o painel âncora do v1.** Construir primeiro aquilo que dois
   concorrentes já entregam é gastar a energia escassa do início do projeto no lugar de menor
   retorno marginal.
3. **Âncora do v1 passa a ser Emprego (CAGED).** Recorte municipal de mercado de trabalho não
   tem equivalente bem-servido e é onde a camada de tradução gera valor que ainda não existe.
4. **Combustível entra como segundo painel**, e com um ângulo que os agregadores não cobrem:
   **série histórica por posto**. "Este posto está 4% acima da média da cidade há 6 meses
   seguidos" é análise; "o preço hoje é R$ 5,89" é cotação, e cotação já tem quem dê.
   O repositório acumula o CSV semestral desde 2004 — esse é o ativo que o concorrente não tem.

---

## Novo CAGED — Ministério do Trabalho e Emprego

**Status:** `verificada` (dado primário, 2026-10-11). Checagem de concorrência com ressalva, ver abaixo.

### Acesso

FTP anônimo `ftp.mtps.gov.br`, caminho `/pdet/microdados/NOVO CAGED/<AAAA>/<AAAAMM>/`. Três
arquivos `.7z` por competência de declaração (agosto/2026: MOV ~51 MB, FOR ~0,7 MB, EXC ~0,1 MB):

- `CAGEDMOV<AAAAMM>` — movimentações declaradas no prazo.
- `CAGEDFOR<AAAAMM>` — movimentações declaradas fora do prazo.
- `CAGEDEXC<AAAAMM>` — exclusões (cancelamento de evento já declarado).

Texto UTF-8, separador `;`, decimal com vírgula. Layout em
`Layout Não-identificado Novo Caged Movimentação.xlsx` na raiz do FTP. O servidor não suporta
HTTP; `httpx` não serve, usar `ftplib`.

### Município

Coluna `município` tem 6 dígitos (IBGE sem dígito verificador): Sorocaba = `355220`. Presente
em MOV, FOR e EXC. Agosto/2026 (MOV): 24.860 linhas, 13.137 admissões, 11.723 desligamentos,
saldo +1.414.

### Ajustes retroativos — corrige a premissa do project.md §6.1

"Reprocessar os 3 meses anteriores" **não basta**. Em agosto/2026, para Sorocaba:

| Arquivo | Linhas | Saldo | Competências afetadas (`competênciamov`) |
|---|---|---|---|
| FOR | 302 | −14 | 202508 a 202607 (12 meses) |
| EXC | 27 | +5 | 202208 a 202607 (4 anos) |

Magnitude pequena (~1% do saldo do mês), mas o alcance temporal é longo. Regra de cálculo:

`saldo(X) = MOV_X + Σ FOR_m(competênciamov=X) − Σ EXC_m(competênciamov=X)`, com m ≥ X.

A exclusão inverte o evento (readme do FTP): excluir uma admissão reduz o saldo. A série de 24
meses exige baixar MOV, FOR e EXC de todas as competências de declaração desde o início da
janela, pois FOR/EXC posteriores reescrevem meses antigos.

### Validação cruzada

Matéria de imprensa reporta Sorocaba em janeiro/2026 com saldo +814, 11.869 admissões e 11.055
desligamentos (abcdoabc.com.br). Usado como teste de sanidade do filtro e do cálculo sobre
`CAGEDMOV202601` (valor como declarado no mês, antes de FOR/EXC).

### Concorrência

Busca feita em 2026-10-11. Encontrado:

- Matérias pontuais com saldo mensal total da cidade, sem série, setor ou ajuste retroativo.
- Relatórios mensais do SEBRAE/BA, sem recorte por município de SP.

**Não confirmado:** se o MTE oferece painel público (Power BI) com filtro municipal. A busca
não o localizou; conferir manualmente. Ângulo do painel: série de 24 meses com ajuste
retroativo aplicado, quebra por setor, tradução em linguagem simples. Se o painel do MTE
cobrir isso bem, reavaliar.

### Pendências

- [ ] Tabela do salário mínimo por ano, com fonte, para faixas salariais em múltiplos de SM.
      Sem ela, não publicar faixa salarial.

---

## INEP — IDEB e Censo Escolar

**Status:** `verificada` em 2026-10-11 contra os arquivos primários.

- **IDEB por escola:** `download.inep.gov.br/ideb/resultados/divulgacao_anos_{iniciais,finais}_escolas_AAAA.zip`
  (xlsx). Edição mais recente: **2025**, publicada em 05/08/2026. Sorocaba (código 3552205):
  96 escolas nos anos iniciais e 77 nos finais, 69 e 71 com IDEB calculado em 2025. Só rede
  pública (Municipal e Estadual); escola privada não tem IDEB. O INEP declara MD5 dentro do zip e
  o `fetch_inep.py` confere.
- **Censo Escolar:** `download.inep.gov.br/dados_abertos/microdados_censo_escolar_AAAA.zip`. Edição
  **2024** (a de 2025 ainda não existe sob esse nome; o fetch tenta os últimos 4 anos). Arquivo
  `microdados_ed_basica_2024.csv`, uma linha por escola, em Latin-1, 426 colunas, sem dado pessoal.
  Sorocaba: 490 estabelecimentos, 452 em atividade (183 municipais, 90 estaduais, 1 federal,
  178 privados). A pasta do zip chama-se `..._defeso`; o conteúdo é o mesmo layout.
- **TLS:** o servidor do INEP não envia o certificado intermediário (RNP ICPEdu GR46 OV TLS CA 2025,
  emitido pela GlobalSign Root R46). Em vez de desligar a verificação, `certs/` guarda o
  intermediário público (SHA-256 E1:07:47:D4:DA:7B:AB:09:CB:A9:95:2F:01:9D:35:34:CB:9F:BA:07:0B:F1:3D:87:91:B1:69:9C:D2:FF:59:DD,
  válido até 19/11/2030) e a cadeia é validada até a raiz do sistema. Renovar o arquivo quando expirar.
- **Armazenamento:** só as linhas de Sorocaba, com hash do zip e MD5 declarado no manifesto. Os
  zips (até 112 MB) não entram no repositório. O fetch só baixa de novo se `Last-Modified` ou o
  tamanho mudar.
- **Concorrência:** QEdu e similares publicam IDEB por escola. A página do QEdu respondeu 403 ao
  `curl` (CloudFront), então a comparação é pela descrição conhecida, não por inspeção. Ângulo
  deste painel, que o equivalente não precisa ter: sem ranking nem nota agregada, ano de
  referência em cada dado, dado aberto em JSON com fonte e hash, página leve e sem JS obrigatório.
  Se o QEdu cobrir isso melhor, o painel perde razão de existir; reavaliar antes de promover.
- **Limitações:** infraestrutura é autodeclarada; IDEB ausente quase sempre significa poucos
  alunos avaliados. Sete escolas do IDEB 2025 não aparecem em atividade no Censo 2024 (abertas
  depois ou renomeadas) e ficam fora até o Censo seguinte.

---

## Limitação do ambiente de verificação (resolvida)

A verificação inicial da ANP foi feita sem acesso ao CSV primário (bloqueio de rede). Superada
em 2026-10-11: o arquivo "últimas 4 semanas" foi baixado e Sorocaba confirmada (ver ANP acima).
O caminho dos CSV semestrais e a série histórica anterior a 4 semanas continuam sem uso; o
histórico agora nasce da acumulação dos instantâneos em `data/raw/anp/`.

---

## IBGE — malha municipal (contorno no mapa da home)

**Status:** `verificada` em 2026-10-11. `servicodados.ibge.gov.br/api/v3/malhas/municipios/3552205`
com `qualidade=maxima`: um polígono, 472 pontos, 10 KB. Arquivo bruto em
`data/raw/ibge/malha_3552205.geojson` (commitável: sem dado pessoal), hash no manifesto. O
ponto marcado no mapa é calculado do polígono (sem rótulo); não é "centro" administrativo nem verificado
como tal. Substitui o contorno OpenStreetMap do protótipo para manter fonte oficial e evitar
a obrigação de atribuição ODbL.

---

# Candidatos a v2

Registrados em 2026-10-11. Nenhum entra em desenvolvimento antes dos três painéis do v1
estarem prontos (`project.md` §1 e §11). Status abaixo reflete só o que foi verificado.

## IBGE — perfil geográfico e econômico

**Status:** `verificada` e **implementada** (painel "A cidade", `scripts/fetch_perfil.py` e `build_perfil.py`). API SIDRA e API de localidades respondem sem cadastro. Respostas guardadas em `data/raw/ibge/perfil/` com SHA-256. Estimativa de população 2026: 766.390 (tabela 6579, variável 9324). PIB nominal 2018–2023 (tabela 5938). VAB por setor só tem valor em 2021; a página usa 2021 com o ano explícito.

- Código IBGE 3552205; microrregião, região imediata e intermediária de Sorocaba
  (`servicodados.ibge.gov.br/api/v1/localidades/municipios/3552205`).
- Censo 2022 (tabela 4714): população 723.682; área 449,872 km²; densidade 1.608,64 hab/km².
- PIB municipal 2023 (tabela 5938, variável 37): R$ 58.816.286 mil. Participação: 47,41% da
  microrregião, 21,45% da mesorregião, 1,71% de SP, 0,54% do Brasil.
- **Indisponível no IBGE** (retorna `...` em 2023): valor adicionado bruto por setor e
  impostos. Publicar `null` e estado vazio, nunca estimar.
- **Não existe** PIB per capita nessa tabela. Não calcular dividindo por população de outro
  ano; se necessário, usar a tabela oficial de per capita com fonte própria.
- CEMPRE (tabela 6449) foi **encerrado em 2021**: não usar como "economia atual".

## TSE, Câmara e Alesp — representantes

**Status:** `verificada` e **implementada** (painel "Representantes", `fetch_representantes.py` e `build_representantes.py`).

- **Municipais 2024:** `consulta_cand_2024.zip` (64 MB), arquivo `consulta_cand_2024_SP.csv`. Sorocaba no TSE é o código **71455** (`SG_UE`), diferente do IBGE. Eleitos: 1 prefeito, 1 vice, 25 vereadores (17 por quociente partidário, 8 por média). O arquivo mistura eleições suplementares de outros municípios; o filtro usa `SG_UE` e o ano da eleição, e o fetch falha se não houver exatamente 1 prefeito e 1 vice eleitos.
- **Deputados 2022 e 2026:** `votacao_candidato_munzona_AAAA.zip` (580 MB e 450 MB), arquivos `..._SP.csv` de 0,9 a 1,2 GB descompactados, lidos em fluxo. Votos nominais válidos somados por candidato nas zonas de Sorocaba (turno 1); só eleitos entram no repositório, e o total de votos por cargo vai à parte para o percentual. Resultado de 2026 disponível desde a apuração de 04/10/2026; os eleitos assumem em 01/02/2027.
- **Dado pessoal:** os arquivos do TSE trazem CPF, e-mail, título de eleitor e data de nascimento. Nada disso é gravado: o fetch seleciona 6 colunas (ano, cargo, nome de urna, partido, situação, turno ou votos) e um teste confere que não há sequência de 11 dígitos nem `@` no bruto.
- **Câmara:** `dadosabertos.camara.leg.br/api/v2/deputados?siglaUf=SP` lista 70 deputados em exercício na coleta.
- **Alesp:** o endereço que funciona é `https://www.al.sp.gov.br/repositorioDados/deputados/deputados.xml` (confirmado em 2026-10-11, 94 deputados, todos `EXE`). O `ckan.al.sp.gov.br` não respondeu. Só nome parlamentar, partido, situação e id são guardados.
- **Exercício:** conferido por nome contra as listas oficiais (igualdade de palavras, ou o nome menor, de 2+ palavras, contido no maior), exigindo correspondência única. Sem correspondência o campo fica `null` ("sem confirmação"): licença, renúncia ou nome de urna diferente do nome parlamentar (ex.: "Capitão Derrite" na urna) aparecem assim; o campo não afirma que alguém está fora do exercício. Nunca se afirma que alguém *não* está em exercício.
- **Vereadores:** só os eleitos; sem fonte confirmada para exercício ou suplentes. A Câmara Municipal não foi verificada.
- **Cadência:** o zip do TSE é regerado todo dia, então `Last-Modified` não serve para pular o download. O workflow roda mensalmente, rebaixa só a eleição em andamento (2026; 2022 e 2024 são encerradas e ficam no repositório, `--forcar` refaz) e regrava `verificado_em` no manifesto a cada execução, que o site mostra como data da conferência de exercício.
- **Posse:** a data de início do mandato só é exibida para prefeito, vice e vereadores (1º de janeiro). Para deputados o site mostra apenas o período em anos, porque a data de posse dos estaduais não foi verificada em fonte.
- **Base legal (LGPD):** nomes, partidos e votos de agentes políticos eleitos são dados tornados públicos pela Justiça Eleitoral (art. 7º, §§3º e 4º), publicados aqui com finalidade de transparência. Candidatos não eleitos não são gravados.

## SSP-SP — segurança pública

**Status:** `verificada` e **implementada** (painel "Segurança", `fetch_ssp.py` e `build_seguranca.py`).

- **Arquivo:** `www.ssp.sp.gov.br/assets/estatistica/transparencia/spDados/SPDadosCriminais_AAAA.xlsx` (uma planilha por ano, 126 a 218 MB, duas abas semestrais). A de 2026 foi atualizada em 08/10/2026, com dados até agosto. Um boletim por linha, com número do BO, endereço, coordenadas, hora, bairro e natureza.
- **Município:** o campo `NOME_MUNICIPIO` é o do registro e **não** serve de filtro (traz boletins de fatos em Piedade e Salto de Pirapora registrados em Sorocaba). O filtro correto é o código IBGE do local (`COD IBGE`, em 2022 `CD_IBGE`) igual a 3552205, que coincide com o município de circunscrição.
- **Colunas variam entre anos** (`CIDADE` x `NOME_MUNICIPIO`, `DESCR_PERIODO` x `DESC_PERIODO`, `CIRCUNCRIÇÃO` com erro de grafia). O fetch resolve por lista de alternativas e falha se faltar alguma.
- **Categorias:** `NATUREZA_APURADA` muda de grafia entre anos (`TRAFICO` x `TRÁFICO`, `HOMICIDIO` x `HOMICÍDIO`) e algumas categorias só existem a partir de 2023 (porte de arma, apreensão e porte de entorpecentes, homicídio culposo no trânsito). O painel usa só as categorias presentes em todos os anos, com grafia normalizada.
- **Horário:** `DESC_PERIODO` vem vazio em mais da metade dos boletins, mas a hora exata existe em muitos deles (em roubos, 343 de 443 no 1º semestre de 2026). A faixa do dia corresponde exatamente a blocos de 6 horas (madrugada 0–5, manhã 6–11, tarde 12–17, noite 18–23), então o build deriva a faixa da hora. A hora 00:00 exata é frequente (provável preenchimento padrão).
- **Mês:** usa `ANO_ESTATISTICA`/`MES_ESTATISTICA` (mês do registro na estatística oficial), não a data do fato. O mês mais recente sobe com registros atrasados.
- **Minimização:** só contagens agregadas por mês, hora, bairro e tipo de furto são gravadas. Número do BO, endereço e coordenadas não saem da memória do fetch; um teste confere o cabeçalho dos CSVs.
- **Bairro:** o campo é digitado (714 grafias distintas no 1º semestre de 2026 para uma cidade de cerca de 300 bairros). Sem ranking, em ordem alfabética, com piso de 50 roubos+furtos no ano; o resto vai para "demais".
- **Concorrência:** a própria SSP-SP publica estatísticas por município e há mapas de terceiros; o ângulo deste painel é a série longa, a limitação explícita de cada número e a recusa de ranking de bairros. Não foi feita comparação sistemática.
- **Limite:** contagem de registros não mede risco nem crime efetivo. Tráfico depende de ação policial.

## Comparativo entre municípios (IBGE e INEP)

**Status:** `verificada` e **implementada** (painel "Comparativo", `fetch_comparativo.py` e `build_comparativo.py`).

- **População:** Censos 1970–2010 (tabela 202, variável 93, `N6[all]`), contagem 2007 (tabela 793), Censo 2022 (tabela 4714) e estimativas anuais (tabela 6579, variável 9324). Anos sem população oficial por município (2023) ficam fora. Mudança de método entre estimativa e Censo pode mudar a posição sem mudança real.
- **PIB:** tabela 5938, variável 37, 2002–2023, todos os municípios (valores nominais).
- **PIB per capita:** calculado aqui, PIB do ano ÷ população do mesmo ano (ambos do IBGE), porque a tabela não publica per capita. Só nos anos com população do mesmo ano. O projeto não divide por população de outro ano.
- **IDEB municipal:** `divulgacao_anos_{iniciais,finais}_municipios_AAAA.zip` do INEP, rede **Pública**, edições 2005–2025, MD5 conferido. O INEP não publica ranking; a posição é calculada aqui. O IDEB tem uma casa decimal, então há muitos empates (63 municípios paulistas empatados com Sorocaba em 2025 nos anos iniciais), e o painel usa posição de competição (1, 2, 2, 4) e avisa dos empates.
- **Armazenamento:** `ano;codigo;valor` de todos os municípios, 8,8 MB em CSV. Sem nomes além dos 645 paulistas (para os vizinhos de ranking).
- **Ressalva de princípio:** ranking de tamanho (população, PIB) é fato, mas não é qualidade. IDEB reflete perfil socioeconômico. A página diz isso nos textos de cada indicador, sem adjetivar a posição.
- **Concorrência:** rankings municipais de população e PIB existem em publicações do IBGE e agregadores; o ângulo deste painel é a série longa da posição de uma cidade, no estado e no país, com as limitações à vista. Não foi feita comparação sistemática.

## Emendas parlamentares com destino a Sorocaba

**Status:** `pendente`. Fontes candidatas: Portal da Transparência e SIOP. Nada testado.
