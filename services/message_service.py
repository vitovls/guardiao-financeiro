from models import DEFAULT_CATEGORIA
from repository.provider import TransactionSaveResult


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


def format_message(results: list[TransactionSaveResult]) -> str:
    if not results:
        return "Não encontrei nenhuma transação nessa imagem."

    lines = ["<b>📊 Extrato processado</b>", ""]
    income_total = 0.0
    expense_total = 0.0

    for r in results:
        t = r.transacao
        if r.status == "duplicata_exata":
            lines.append(
                f"⚠️ {t.data.strftime('%d/%m/%Y')} — {t.descricao}: R$ {t.valor:.2f} "
                "(não salva, já registrada — reenvie com alguma diferença se for uma compra real)"
            )
            continue

        emoji = "🟡" if r.status == "suspeita" else ("🟢" if t.tipo == "entrada" else "🔴")
        if t.tipo == "entrada":
            income_total += t.valor
        else:
            expense_total += t.valor
        notes = []
        if r.status == "suspeita":
            notes.append("parece semelhante a uma já registrada")
        if t.categoria == DEFAULT_CATEGORIA:
            notes.append(f'categoria não identificada, salva como "{DEFAULT_CATEGORIA}"')
        note = f" ({'; '.join(notes)})" if notes else ""
        lines.append(f"{emoji} {t.data.strftime('%d/%m/%Y')} — {t.descricao}: R$ {t.valor:.2f}{note}")

    balance = income_total - expense_total
    lines.append("")
    lines.append("<b>Resumo</b>")
    lines.append(f"🟢 Entradas: R$ {income_total:.2f}")
    lines.append(f"🔴 Saídas: R$ {expense_total:.2f}")
    lines.append(f"💰 Saldo: R$ {balance:.2f}")

    return "\n".join(lines)
