TRANSACTION_SCHEMA = (
    '[{"data": "YYYY-MM-DD", "descricao": "", "valor": 0.0, "tipo": "entrada|saida", "categoria": ""}]'
)

INTERPRETATION_SCHEMA = (
    '{"intencao": "transacao"|"consulta"|"nenhuma", '
    f'"transacoes": {TRANSACTION_SCHEMA}, '
    '"periodo_inicio": "YYYY-MM-DD"|null, "periodo_fim": "YYYY-MM-DD"|null, '
    '"categoria": ""|null}'
)


def build_text_interpretation_prompt(today: str, text: str) -> str:
    return (
        f'A data de hoje é {today}. O usuário escreveu: "{text}". '
        f'Responda APENAS com JSON neste formato: {INTERPRETATION_SCHEMA}. '
        'Primeiro determine "intencao": '
        '"transacao" se a mensagem descreve um gasto ou recebimento '
        '(ex: "gastei 50 no mercado", "recebi 1000 de salário"); '
        '"consulta" se a mensagem pergunta por um resumo financeiro, total ou saldo '
        '(ex: "quanto gastei esse mês?", "quanto entrou em junho?", '
        '"quanto gastei em mercado esse mês?"); '
        '"nenhuma" para qualquer outra coisa (ex: saudação, pergunta não financeira). '
        'Quando "intencao" for "transacao": preencha "transacoes" com a lista de transações '
        'e deixe "periodo_inicio", "periodo_fim" e "categoria" como null. '
        'Se não houver data explícita na mensagem, use a data de hoje. '
        'Determine "tipo" pela direção do dinheiro em relação ao usuário, nunca pela '
        'palavra isolada: dinheiro chegando ou recebido (salário que "caiu", Pix '
        'recebido, estorno a favor do usuário) é "entrada"; dinheiro gasto, pago ou '
        'a pagar (compra, boleto que "venceu" e ainda não foi pago) é "saida" — um '
        'boleto vencido é uma saída a pagar, nunca uma entrada, mesmo que a frase '
        'não pareça um gasto à primeira vista. '
        '"Conto" é gíria brasileira para R$1 — converta multiplicando o número '
        'informado por 1 (ex.: "10 conto" equivale a R$10,00), nunca por 100 ou 1000. '
        'Se a mensagem claramente descrever uma transação mas não mencionar um '
        'valor numérico explícito, ainda marque "intencao" como "transacao" e inclua a '
        'transação com "valor": 0.0 — não a descarte só por falta de valor. '
        'Quando "intencao" for "consulta": deixe "transacoes" como uma lista vazia. '
        'Extraia o período financeiro mencionado em "periodo_inicio"/"periodo_fim" '
        '(ambos no formato YYYY-MM-DD, sempre um intervalo fechado): "esse mês"/"este '
        'mês" é do dia 1 ao último dia do mês corrente; um mês nomeado (ex: "junho") '
        'sem ano é o mês inteiro do ano corrente; "esse ano"/"este ano" é 1º de '
        'janeiro a 31 de dezembro do ano corrente; datas explícitas usam exatamente o '
        'que foi dito. Se não for possível identificar nenhum período (nem explícito '
        'nem relativo), deixe "periodo_inicio" e "periodo_fim" como null — nunca '
        'invente um período padrão. Se a mensagem mencionar uma categoria específica '
        'de gasto ou receita (ex: "em mercado", "com transporte"), preencha '
        '"categoria" com esse texto; caso contrário deixe "categoria" como null. '
        'Quando "intencao" for "nenhuma": "transacoes" deve ser lista vazia e '
        '"periodo_inicio", "periodo_fim", "categoria" devem ser null.'
    )


def build_document_extraction_prompt(document_label: str) -> str:
    return (
        f"Extraia as transações deste(a) {document_label} de extrato bancário. "
        "Uma transação é uma movimentação individual e específica de dinheiro — um Pix, "
        "uma compra no débito, uma transferência — sempre associada a um remetente, "
        "beneficiário ou estabelecimento nomeado. "
        'NÃO são transações, mesmo que tenham valor em R$: linhas de "Total de entradas" '
        'ou "Total de saídas" (são subtotais, não movimentações individuais), '
        '"Saldo inicial", "Saldo final", "Saldo do período" ou "Saldo do dia", qualquer '
        "coluna de saldo corrente/acumulado, e cabeçalhos de tabela/página ou rodapé com "
        "CNPJ/atendimento/SAC — ignore essas linhas completamente. "
        "Para cada transação, inclua na descrição o nome completo do remetente ou "
        "beneficiário e os detalhes de conta/agência exatamente como aparecem no "
        "documento — nunca resuma ou omita essas informações, mesmo que se repitam "
        "entre transações. "
        f"Responda APENAS com JSON: {TRANSACTION_SCHEMA}"
    )
