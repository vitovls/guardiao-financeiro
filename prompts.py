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
        "Se não houver data explícita na mensagem, use a data de hoje."
    )


def build_document_extraction_prompt(document_label: str) -> str:
    return (
        f"Extraia as transações deste(a) {document_label} de extrato bancário. "
        f"Responda APENAS com JSON: {TRANSACTION_SCHEMA}"
    )
