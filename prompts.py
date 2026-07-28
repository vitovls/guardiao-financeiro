TRANSACTION_SCHEMA = (
    '[{"data": "YYYY-MM-DD", "descricao": "", "valor": 0.0, "tipo": "entrada|saida", "categoria": ""}]'
)


def build_text_extraction_prompt(today: str, text: str) -> str:
    return (
        f'A data de hoje é {today}. O usuário escreveu: "{text}". '
        f'Responda APENAS com JSON neste formato: {{"e_transacao": true|false, "transacoes": {TRANSACTION_SCHEMA}}}. '
        'Marque "e_transacao" como false se a mensagem não descrever um gasto ou '
        'recebimento (ex: saudação, pergunta, conversa solta). Nesse caso, '
        '"transacoes" deve ser uma lista vazia. '
        "Se não houver data explícita na mensagem, use a data de hoje. "
        'Determine "tipo" pela direção do dinheiro em relação ao usuário, nunca pela '
        'palavra isolada: dinheiro chegando ou recebido (salário que "caiu", Pix '
        'recebido, estorno a favor do usuário) é "entrada"; dinheiro gasto, pago ou '
        'a pagar (compra, boleto que "venceu" e ainda não foi pago) é "saida" — um '
        'boleto vencido é uma saída a pagar, nunca uma entrada, mesmo que a frase '
        'não pareça um gasto à primeira vista. '
        '"Conto" é gíria brasileira para R$1 — converta multiplicando o número '
        'informado por 1 (ex.: "10 conto" equivale a R$10,00), nunca por 100 ou 1000. '
        'Se a mensagem claramente descrever uma transação mas não mencionar um '
        'valor numérico explícito, ainda marque "e_transacao" como true e inclua a '
        'transação com "valor": 0.0 — não a descarte só por falta de valor.'
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
