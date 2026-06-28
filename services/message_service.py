from models import Transacao


def split_message(text: str, limit: int = 4096) -> list[str]:
    if len(text) <= limit:
        return [text]

    block = []
    lines = text.split("\n")
    cur = ""

    for line in lines:
        if len(cur) + len(line) + 1 > limit:
            block.append(cur)
            cur = line
        else:
            cur = f"{cur}\n{line}" if cur else line

    if cur:
        block.append(cur)

    return block


def format_message(transactions: list[Transacao]) -> str:
    if not transactions:
        return "Não encontrei nenhuma transação nessa imagem."

    lines = ["<b>📊 Extrato processado</b>", ""]
    income_total = 0.0
    expense_total = 0.0

    for t in transactions:
        emoji = "🟢" if t.tipo == "entrada" else "🔴"
        if t.tipo == "entrada":
            income_total += t.valor
        else:
            expense_total += t.valor
        lines.append(f"{emoji} {t.data.strftime('%d/%m/%Y')} — {t.descricao}: R$ {t.valor:.2f}")

    balance = income_total - expense_total
    lines.append("")
    lines.append("<b>Resumo</b>")
    lines.append(f"🟢 Entradas: R$ {income_total:.2f}")
    lines.append(f"🔴 Saídas: R$ {expense_total:.2f}")
    lines.append(f"💰 Saldo: R$ {balance:.2f}")

    return "\n".join(lines)
