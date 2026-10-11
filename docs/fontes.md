# Catálogo de fontes — Sorocaba em Dados

Registro de verificação de cada fonte antes da implementação. Nenhum painel entra em
desenvolvimento sem uma entrada aqui com status `verificada`.

Convenção de status: `verificada` | `parcial` | `rejeitada` | `pendente`.

---

## ANP — Levantamento de Preços de Combustíveis (LPC)

**Status:** `parcial` — fonte confirmada, posicionamento do painel precisa mudar. Ver
"Conclusão" abaixo.

**Verificado em:** 2026-10-11

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

**Status:** `pendente`

A verificar antes de implementar:
- [ ] Ano mais recente de IDEB divulgado
- [ ] Disponibilidade de IDEB por escola para Sorocaba (não só agregado municipal)
- [ ] Layout do Censo Escolar e quais variáveis de infraestrutura são publicáveis
- [ ] Concorrência: QEdu e similares já cobrem isso — mesmo risco do combustível,
      **checar antes de construir**

---

## Limitação do ambiente de verificação

Esta verificação foi feita sem acesso direto ao CSV primário: o ambiente usado bloqueia
`www.gov.br` por política de rede. As conclusões sobre presença de Sorocaba na amostra e
tamanho da amostra vieram de agregador terceiro e de documentação oficial da ANP, não do dado
bruto.

**Portanto a entrada da ANP permanece `parcial` até alguém rodar, em máquina sem esse bloqueio:**

```bash
# baixar o semestre e contar postos de Sorocaba na semana mais recente
curl -O https://www.gov.br/anp/pt-br/centrais-de-conteudo/dados-abertos/arquivos/shpc/dsas/ca/ca-2026-02.csv
```

e confirmar: (a) Sorocaba presente, (b) data da coleta mais recente, (c) contagem de CNPJs
distintos. Só então o status vira `verificada` e o painel sai do bloqueio.
