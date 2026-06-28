from models import Transacao


def split_message(text: str, limit: int = 4096) -> list[str]:
    if len(text) <= limit:
        return [text]

    block = []
    lines = text.split("\n")
    cur = ""

    for linha in lines:
        if len(cur) + len(linha) + 1 > limit:
            block.append(cur)
            cur = linha
        else:
            cur = f"{cur}\n{linha}" if cur else linha

    if cur:
        block.append(cur)

    return block
  
def formatter_message(transactions: list[Transacao]) -> str:
    if not transactions:
        return "Não encontrei nenhuma transação nessa imagem."

    lines = ["<b>📊 Extrato processado</b>", ""]
    enter = 0.0
    leave = 0.0

    for t in transactions:
        emoji = "🟢" if t.tipo == "entrada" else "🔴"
        if t.tipo == "entrada":
            enter += t.valor
        else:
            leave += t.valor
        lines.append(f"{emoji} {t.data.strftime('%d/%m/%Y')} — {t.descricao}: R$ {t.valor:.2f}")

    balance = enter - leave
    lines.append("")
    lines.append("<b>Resumo</b>")
    lines.append(f"🟢 Entradas: R$ {enter:.2f}")
    lines.append(f"🔴 Saídas: R$ {leave:.2f}")
    lines.append(f"💰 Saldo: R$ {balance:.2f}")

    return "\n".join(lines)
