from datetime import date, timedelta

from models import DEFAULT_CATEGORIA
from repository.provider import PendingConfirmation, TransactionSaveResult

_JANELA_CURTA = timedelta(minutes=5)

_MESES_PT = {
    1: "janeiro", 2: "fevereiro", 3: "março", 4: "abril",
    5: "maio", 6: "junho", 7: "julho", 8: "agosto",
    9: "setembro", 10: "outubro", 11: "novembro", 12: "dezembro",
}


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
        if r.status in ("suspeita", "duplicata_exata"):
            lines.append(
                f"🟡 {t.data.strftime('%d/%m/%Y')} — {t.descricao}: R$ {t.valor:.2f} "
                "(aguardando sua confirmação, veja a mensagem abaixo)"
            )
            continue

        emoji = "🟢" if t.tipo == "entrada" else "🔴"
        if t.tipo == "entrada":
            income_total += t.valor
        else:
            expense_total += t.valor
        notes = []
        if t.categoria == DEFAULT_CATEGORIA:
            notes.append(f'categoria não identificada, salva como "{DEFAULT_CATEGORIA}"')
        if t.valor == 0.0:
            notes.append("valor não identificado, revise")
        note = f" ({'; '.join(notes)})" if notes else ""
        lines.append(f"{emoji} {t.data.strftime('%d/%m/%Y')} — {t.descricao}: R$ {t.valor:.2f}{note}")

    balance = income_total - expense_total
    lines.append("")
    lines.append("<b>Resumo</b>")
    lines.append(f"🟢 Entradas: R$ {income_total:.2f}")
    lines.append(f"🔴 Saídas: R$ {expense_total:.2f}")
    lines.append(f"💰 Saldo: R$ {balance:.2f}")

    return "\n".join(lines)


def format_pending_message(pendencia: PendingConfirmation) -> str:
    t = pendencia.transacao
    motivo_label = "um lançamento idêntico" if pendencia.motivo == "duplicata_exata" else "um lançamento parecido"
    linhas = [
        f"🟡 Encontrei {motivo_label} ao tentar registrar:",
        f"{t.data.strftime('%d/%m/%Y')} — {t.descricao}: R$ {t.valor:.2f}",
    ]
    if pendencia.similar_criado_em is not None:
        intervalo = abs(pendencia.criado_em - pendencia.similar_criado_em)
        if intervalo <= _JANELA_CURTA:
            linhas.append("Foi enviado bem perto de um lançamento parecido — pode ter sido sem querer.")
        else:
            linhas.append("Já existe um lançamento parecido registrado antes.")
    linhas.append("Confirma que quer registrar mesmo assim?")
    return "\n".join(linhas)


def _periodo_label(start: date, end: date) -> str:
    if start.month == end.month and start.year == end.year:
        return f"{_MESES_PT[start.month]}/{start.year}"
    return f"{start.strftime('%d/%m/%Y')} a {end.strftime('%d/%m/%Y')}"


def format_no_intent_message() -> str:
    return (
        "Não identifiquei uma transação nem uma consulta nessa mensagem."
        " Tente algo como 'Gastei 30 reais no mercado' ou 'Quanto gastei esse mês?'"
    )


def format_missing_period_message() -> str:
    return "Qual período você quer consultar? Ex: 'esse mês', 'junho', 'este ano'."


def format_query_message(start: date, end: date, categoria: str | None, totals: dict[str, float]) -> str:
    periodo = _periodo_label(start, end)
    entradas = totals["entradas"]
    saidas = totals["saidas"]

    if categoria:
        if entradas == 0.0 and saidas == 0.0:
            return f'Você não teve nenhuma transação em "{categoria}" em {periodo}.'
        if saidas and not entradas:
            return f'Você gastou R$ {saidas:.2f} em "{categoria}" em {periodo}.'
        if entradas and not saidas:
            return f'Você recebeu R$ {entradas:.2f} em "{categoria}" em {periodo}.'
        return (
            f'Em "{categoria}" em {periodo}:\n'
            f"🟢 Entradas: R$ {entradas:.2f}\n"
            f"🔴 Saídas: R$ {saidas:.2f}"
        )

    if entradas == 0.0 and saidas == 0.0:
        return f"Você não teve nenhuma transação em {periodo}."

    saldo = entradas - saidas
    return (
        f"<b>📊 Resumo de {periodo}</b>\n\n"
        f"🟢 Entradas: R$ {entradas:.2f}\n"
        f"🔴 Saídas: R$ {saidas:.2f}\n"
        f"💰 Saldo: R$ {saldo:.2f}"
    )
