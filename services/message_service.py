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