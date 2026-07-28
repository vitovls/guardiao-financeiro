import asyncio

from services.nlp_service import extract_text_transactions

_CASOS = [
    "Meu salario caiu de 3700 reais",
    "Salario caiu 3700 reais",
    "Gastei com mercado",
    "Pix de 10 conto caiu aqui",
    "Boleto de 150 venceu hoje",
    "Estornou 40 conto que cobraram errado oh",
]


async def main() -> None:
    for texto in _CASOS:
        transacoes = await extract_text_transactions(texto)
        print(f"\n=== {texto!r} ===")
        if not transacoes:
            print("  (nenhuma transação — e_transacao: false)")
            continue
        for t in transacoes:
            print(f"  {t.tipo} | R$ {t.valor:.2f} | {t.descricao!r}")


if __name__ == "__main__":
    asyncio.run(main())
