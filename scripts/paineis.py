"""Conteúdo editorial dos painéis (títulos, perguntas, glossário, limitações)."""

from __future__ import annotations

PAINEIS = {
    "emprego": {
        "nav": "Emprego",
        "titulo": "O trabalho em Sorocaba",
        "h1": "Sorocaba está gerando mais ou menos empregos?",
        "pergunta": "O mercado de trabalho de Sorocaba está crescendo ou encolhendo? Quais setores estão contratando?",
        "fonte": "Novo CAGED — Ministério do Trabalho e Emprego",
        "cta": "Explorar emprego",
        "tom": "secundario",
        "descricao": "Acompanhe admissões, desligamentos, saldo de empregos e os setores que movimentam o mercado de trabalho local.",
        "meta_desc": "Admissões, desligamentos, saldo de empregos e setores do mercado de trabalho de Sorocaba, com fonte e data de referência.",
        "palavras": ["emprego", "empregos", "trabalho", "vagas", "caged", "admissões", "setores", "salário"],
        "blocos": [
            ("Saldo mensal de empregos", "Evolução de até 24 meses, conforme os dados publicados.", "barras"),
            ("Admissões e desligamentos", "Quantas pessoas foram contratadas e desligadas em cada mês.", "linha"),
            ("Setores econômicos", "Quais setores criam ou reduzem vagas no período.", "barras"),
            ("Salário de admissão", "Faixa salarial de quem foi contratado, quando disponível.", "barras"),
        ],
        "glossario": [
            ("Saldo de empregos", "Admissões menos desligamentos. Saldo positivo significa que houve mais contratações do que demissões no período; negativo, o contrário."),
            ("Admissão", "Registro de uma contratação com carteira assinada."),
            ("Desligamento", "Encerramento de um vínculo formal, por demissão, pedido do trabalhador ou outros motivos."),
        ],
        "limitacoes": [
            "Considera apenas empregos formais (carteira assinada).",
            "Os números podem ser revisados pela fonte após a publicação.",
        ],
    },
    "combustivel": {
        "nav": "Combustível",
        "titulo": "O preço ao longo do tempo",
        "h1": "Como os preços dos combustíveis mudam ao longo do tempo?",
        "pergunta": "Como os preços dos postos pesquisados evoluíram ao longo do tempo? Quais estão acima ou abaixo da referência municipal?",
        "fonte": "Levantamento de Preços de Combustíveis — ANP",
        "cta": "Explorar combustíveis",
        "tom": "acento",
        "etiqueta": "Histórico, não só a cotação da semana",
        "descricao": "Entenda como os preços dos combustíveis variam entre os postos pesquisados e como mudam ao longo das semanas.",
        "meta_desc": "Evolução histórica dos preços de combustíveis nos postos pesquisados pela ANP em Sorocaba, comparada à referência municipal.",
        "palavras": ["combustível", "combustíveis", "gasolina", "etanol", "diesel", "postos", "preço", "anp"],
        "blocos": [
            ("Evolução por posto pesquisado", "Trajetória semanal de preço de cada estabelecimento com observações suficientes.", "linha"),
            ("Comparação com a referência municipal", "Quais postos ficaram acima ou abaixo da referência calculada sobre a amostra.", "barras"),
        ],
        "glossario": [
            ("Pesquisa amostral", "A ANP visita apenas alguns postos a cada semana. Por isso, falamos em “menor preço entre os postos pesquisados nesta semana”, nunca no posto mais barato de toda Sorocaba."),
            ("Referência municipal (mediana)", "O preço do meio quando os valores pesquisados são colocados em ordem: metade dos postos está acima e metade abaixo."),
            ("Tamanho da amostra", "Quantos postos foram pesquisados na semana. Amostras pequenas pedem mais cautela na comparação."),
        ],
        "limitacoes": [
            "Nem todos os postos da cidade são pesquisados.",
            "Se a fonte não publicar dados recentes, mantemos a última referência válida com sua data.",
            "Não usamos médias de outras regiões para preencher lacunas.",
        ],
    },
    "escolas": {
        "nav": "Escolas",
        "titulo": "Conheça as escolas da cidade",
        "h1": "O que os dados mostram sobre cada escola?",
        "pergunta": "Quais indicadores ajudam a conhecer as escolas de Sorocaba e como consultar informações sobre uma escola específica?",
        "fonte": "Censo Escolar e IDEB — INEP",
        "cta": "Explorar escolas",
        "tom": "card",
        "descricao": "Consulte indicadores educacionais, matrículas, infraestrutura e informações disponíveis sobre cada escola.",
        "meta_desc": "Consulte matrículas, infraestrutura e IDEB das escolas de Sorocaba, com o ano de referência de cada indicador.",
        "palavras": ["escola", "escolas", "ideb", "matrículas", "educação", "bairro", "ensino", "inep"],
        "blocos": [
            ("Matrículas", "Número de alunos por etapa de ensino, com ano de referência.", "barras"),
            ("IDEB — anos iniciais e finais", "Evolução do indicador por edição, quando disponível.", "linha"),
        ],
        "glossario": [
            ("IDEB", "Índice que combina aprovação escolar e desempenho em avaliações nacionais. É um indicador entre vários e não resume sozinho a qualidade de uma escola."),
            ("Ano de referência", "Cada indicador é publicado em um calendário próprio. Mostramos sempre o ano a que cada número se refere."),
            ("Sem ranking", "Não classificamos escolas como boas ou ruins. Os indicadores ajudam a conhecer a escola e a buscar mais informações."),
        ],
        "limitacoes": [
            "Algumas escolas não têm IDEB calculado em todas as edições.",
            "Dados de infraestrutura são declarados pelas próprias escolas no Censo Escolar.",
        ],
        "busca": True,
    },
}
