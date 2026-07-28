import asyncio
import sys

from services.llm.bedrock_provider import BedrockProvider

_ROUNDS = 3


async def main(pdf_path: str) -> None:
    with open(pdf_path, "rb") as f:
        file_bytes = f.read()

    provider = BedrockProvider()

    for round_number in range(1, _ROUNDS + 1):
        transacoes = await provider.extract_document_transactions(file_bytes, "application/pdf")
        print(f"\n=== Rodada {round_number} — {len(transacoes)} transações ===")
        for t in transacoes:
            print(f"  {t.data} | {t.tipo} | R$ {t.valor:.2f} | {t.descricao!r}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Uso: python scripts/manual_test_document_extraction_variance.py <caminho-do-pdf>", file=sys.stderr)
        sys.exit(1)
    asyncio.run(main(sys.argv[1]))
