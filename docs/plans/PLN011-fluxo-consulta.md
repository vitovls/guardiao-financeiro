---
tipo: PLN
numero: PLN011
slug: fluxo-consulta
spec: SPEC011
inv: INV009
status: Draft
---

# PLN011 — Fluxo de consulta (Fase 6)

## Estratégia

Uma única mudança de contrato propaga por toda a cadeia handler → nlp_service → LLMProvider (e volta): a chamada de IA que hoje só extrai transação de texto passa a devolver uma **interpretação completa da mensagem** (intenção + transações + filtros de consulta), na mesma chamada, sem custo extra de Bedrock. `handlers/text_handler.py` passa a rotear com base nessa interpretação: `transacao` segue o fluxo hoje existente sem mudança de comportamento; `consulta` chama a camada de dados já pronta (`get_totals_by_period`, estendida com filtro de categoria); `nenhuma` (ou `transacao` sem itens) cai no mesmo fallback textual de hoje, com redação atualizada.

Sequência para uma mensagem de texto, depois desta fase:

```
texto ──► nlp_service.interpret_text ──► LLMProvider.interpret_text (1 chamada)
                                              │
                                              ▼
                                    InterpretacaoTexto
                                    (intencao, transacoes,
                                     periodo_inicio/fim, categoria)
                                              │
                    ┌─────────────────────────┼─────────────────────────┐
                    ▼                         ▼                         ▼
              intencao=transacao       intencao=consulta          intencao=nenhuma
              (fluxo já existente,      (sem período? pede         ou transacao
               dedup/pendência          período; senão chama       sem itens
               intocados)               get_totals + formata)      (fallback)
```

### DTO novo: `InterpretacaoTexto`

Vive em `services/llm/provider.py`, ao lado de `LLMProviderError`/`BedrockOutputError` — mesmo raciocínio já aplicado a `PendingConfirmation`/`TransactionSaveResult` em `repository/provider.py`: é o formato de retorno de uma camada específica, não um DTO de domínio puro como `Transacao` (que continua exclusivo de `models.py`).

```python
from datetime import date
from typing import Literal

from pydantic import BaseModel

from models import Transacao


class InterpretacaoTexto(BaseModel):
    intencao: Literal["transacao", "consulta", "nenhuma"]
    transacoes: list[Transacao] = []
    periodo_inicio: date | None = None
    periodo_fim: date | None = None
    categoria: str | None = None
```

## Antes/Depois por arquivo

### `services/llm/provider.py`

**Antes:**
```python
class LLMProvider(ABC):
    @abstractmethod
    async def extract_text_transactions(self, text: str) -> list[Transacao]:
        ...

    @abstractmethod
    async def extract_document_transactions(self, file_bytes: bytes, mime_type: str) -> list[Transacao]:
        ...
```

**Depois:**
```python
class LLMProvider(ABC):
    @abstractmethod
    async def interpret_text(self, text: str) -> InterpretacaoTexto:
        ...

    @abstractmethod
    async def extract_document_transactions(self, file_bytes: bytes, mime_type: str) -> list[Transacao]:
        ...
```
`extract_document_transactions` não muda em nenhum arquivo — foto/PDF ficam fora desta fase (SPEC011 R11). `InterpretacaoTexto` (bloco acima) entra neste arquivo.

### `prompts.py`

**Antes:** `build_text_extraction_prompt(today, text)` só pede `{"e_transacao": bool, "transacoes": [...]}`.

**Depois:** renomeia para `build_text_interpretation_prompt(today, text)`, schema estendido, preserva **literalmente** todas as regras já existentes (convenção de sinal, gíria "conto", valor ausente) dentro do ramo `"transacao"`, e adiciona os ramos `"consulta"`/`"nenhuma"`:

```python
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
```

`build_document_extraction_prompt` não muda.

### `services/llm/bedrock_provider.py`

**Antes (linhas 81-84 e 95-97):**
```python
async def extract_text_transactions(self, text: str) -> list[Transacao]:
    prompt = build_text_extraction_prompt(date.today().isoformat(), text)
    messages = [{"role": "user", "content": [{"text": prompt}]}]
    return await self._call_with_malformed_retry(TEXT_MODEL_ID, messages, self._parse_text_response)

...

def _parse_text_response(self, response_data: dict) -> list[Transacao]:
    if not response_data.get("e_transacao"):
        return []
    return [Transacao(**item) for item in response_data["transacoes"]]
```

**Depois:**
```python
async def interpret_text(self, text: str) -> InterpretacaoTexto:
    prompt = build_text_interpretation_prompt(date.today().isoformat(), text)
    messages = [{"role": "user", "content": [{"text": prompt}]}]
    return await self._call_with_malformed_retry(TEXT_MODEL_ID, messages, self._parse_interpretation_response)

...

def _parse_interpretation_response(self, response_data: dict) -> InterpretacaoTexto:
    return InterpretacaoTexto(**response_data)
```
`_call_with_malformed_retry`, `_converse_with_retry`, retry/backoff de throttling, `_strip_markdown_fence`, `TEXT_MODEL_ID` (continua `us.meta.llama4-maverick-17b-instruct-v1:0`, reaproveitando a decisão já registrada em `PATTERNS.md`) e `extract_document_transactions`/`_parse_document_response` **não mudam** — `ValidationError` do Pydantic (agora podendo vir de `InterpretacaoTexto`, ex.: `"intencao"` fora do `Literal`) já é capturada pelo mesmo bloco `except (json.JSONDecodeError, KeyError, ValidationError)` que já existe, preservando o comportamento de retry em saída malformada.

### `services/llm/gemini_provider.py`

**Antes (linhas 19-28):**
```python
async def extract_text_transactions(self, text: str) -> list[Transacao]:
    prompt = build_text_extraction_prompt(date.today().isoformat(), text)
    response = self._client.models.generate_content(
        model=_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(response_mime_type="application/json"),
    )
    response_data = json.loads(response.text)
    if not response_data.get("e_transacao"):
        return []
    return [Transacao(**item) for item in response_data["transacoes"]]
```

**Depois:**
```python
async def interpret_text(self, text: str) -> InterpretacaoTexto:
    prompt = build_text_interpretation_prompt(date.today().isoformat(), text)
    response = self._client.models.generate_content(
        model=_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(response_mime_type="application/json"),
    )
    response_data = json.loads(response.text)
    return InterpretacaoTexto(**response_data)
```

### `services/nlp_service.py`

**Antes:**
```python
async def extract_text_transactions(text: str) -> list[Transacao]:
    try:
        return await _provider.extract_text_transactions(text)
    except Exception as exc:
        print(f"[nlp_service] falha ao extrair transação de texto: {exc}", file=sys.stderr)
        return []
```

**Depois:**
```python
async def interpret_text(text: str) -> InterpretacaoTexto:
    try:
        return await _provider.interpret_text(text)
    except Exception as exc:
        print(f"[nlp_service] falha ao interpretar mensagem de texto: {exc}", file=sys.stderr)
        return InterpretacaoTexto(intencao="nenhuma")
```
Mesmo princípio já estabelecido: erro de provedor nunca vaza ao handler — antes virava "sem transação", agora vira "nenhuma" (efeito equivalente no fallback do usuário).

### `repository/provider.py`

**Antes (linhas 49-51):**
```python
    @abstractmethod
    async def get_totals_by_period(
        self, telegram_user_id: int, start: date, end: date
    ) -> dict[str, float]: ...
```

**Depois:**
```python
    @abstractmethod
    async def get_totals_by_period(
        self, telegram_user_id: int, start: date, end: date, categoria: str | None = None
    ) -> dict[str, float]: ...
```

### `repository/dynamo_repository.py`

**Antes (linhas 273-294):** já lido no INV009 — soma `entradas`/`saidas` iterando `response["Items"]`, pulando `_ESPECIAIS`.

**Depois:** mesmo método, um parâmetro a mais e um `continue` a mais no loop (reaproveita `normalize_description`, já importado no arquivo):
```python
async def get_totals_by_period(
    self, telegram_user_id: int, start: date, end: date, categoria: str | None = None
) -> dict[str, float]:
    try:
        response = self._table.query(
            KeyConditionExpression=(
                Key("userId").eq(str(telegram_user_id))
                & Key("sortKey").between(f"{start.isoformat()}#", f"{end.isoformat()}#{_HIGH_SENTINEL}")
            )
        )
    except ClientError as exc:
        raise RepositoryError(f"falha ao consultar totais por período: {exc}") from exc

    categoria_norm = normalize_description(categoria) if categoria else None
    totals = {"entradas": 0.0, "saidas": 0.0}
    key_map = {"entrada": "entradas", "saida": "saidas"}
    for item in response.get("Items", []):
        if item["sortKey"].startswith(_ESPECIAIS):
            continue
        if categoria_norm and normalize_description(item.get("categoria", "")) != categoria_norm:
            continue
        key = key_map.get(item.get("tipo"))
        if key:
            totals[key] += float(item["valor"])
    return totals
```

### `repository/sqlite_repository.py`

**Antes (linhas 92-108):** `SELECT tipo, SUM(valor) ... GROUP BY tipo` via `func.sum`.

**Depois:** abandona `GROUP BY` em favor de iterar as entidades em Python — só assim o filtro de categoria usa a mesma normalização (`normalize_description`) que o DynamoDB, em vez de um `WHERE categoria == ...` de comparação exata que divergiria de comportamento entre os dois backends:
```python
async def get_totals_by_period(
    self, telegram_user_id: int, start: date, end: date, categoria: str | None = None
) -> dict[str, float]:
    categoria_norm = normalize_description(categoria) if categoria else None
    async with self._session_factory() as session:
        result = await session.execute(
            select(TransactionEntity).where(
                TransactionEntity.telegram_user_id == telegram_user_id,
                TransactionEntity.data >= start,
                TransactionEntity.data <= end,
            )
        )
        key_map = {"entrada": "entradas", "saida": "saidas"}
        totals = {"entradas": 0.0, "saidas": 0.0}
        for entity in result.scalars().all():
            if categoria_norm and normalize_description(entity.categoria) != categoria_norm:
                continue
            key = key_map.get(entity.tipo)
            if key:
                totals[key] += entity.valor
        return totals
```
Import `func` sai de `from sqlalchemy import func, select` (fica só `select`); import de `normalize_description` entra (mesmo módulo `repository.dedup` já usado nas linhas 9-14 deste arquivo para dedup).

### `services/transaction_service.py`

**Antes (linhas 18-20):**
```python
async def get_totals(telegram_user_id: int, start: date, end: date) -> dict[str, float]:
    repository = get_transaction_repository()
    return await repository.get_totals_by_period(telegram_user_id, start, end)
```

**Depois:**
```python
async def get_totals(
    telegram_user_id: int, start: date, end: date, categoria: str | None = None
) -> dict[str, float]:
    repository = get_transaction_repository()
    return await repository.get_totals_by_period(telegram_user_id, start, end, categoria)
```

### `services/message_service.py`

Três funções novas, mesmo estilo de `format_message`/`format_pending_message` já existentes:

```python
_MESES_PT = {
    1: "janeiro", 2: "fevereiro", 3: "março", 4: "abril",
    5: "maio", 6: "junho", 7: "julho", 8: "agosto",
    9: "setembro", 10: "outubro", 11: "novembro", 12: "dezembro",
}


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
```
`format_message`/`format_pending_message`/`split_message` não mudam.

### `handlers/text_handler.py`

**Antes (arquivo inteiro, 25 linhas):** ver INV009 Bloco 2 — chama `extract_text_transactions` incondicionalmente, sempre trata como transação.

**Depois:**
```python
from telegram import Update
from telegram.ext import ContextTypes

from handlers.pending_handler import build_confirmation_keyboard
from services.llm.provider import InterpretacaoTexto
from services.message_service import (
    format_message,
    format_missing_period_message,
    format_no_intent_message,
    format_pending_message,
    format_query_message,
    split_message,
)
from services.nlp_service import interpret_text
from services.transaction_service import claim_update, get_totals, save_transactions


async def get_message(update: Update, context: ContextTypes):
    user_id = update.effective_user.id
    if not await claim_update(user_id, update.update_id):
        return

    text = update.message.text
    interpretacao = await interpret_text(text)

    if interpretacao.intencao == "consulta":
        await _handle_query(update, user_id, interpretacao)
        return

    if interpretacao.intencao != "transacao" or not interpretacao.transacoes:
        await update.message.reply_text(format_no_intent_message())
        return

    results = await save_transactions(interpretacao.transacoes, user_id)

    msg = format_message(results)
    for block in split_message(msg):
        await update.message.reply_text(block, parse_mode="HTML")

    for r in results:
        if r.pendencia:
            await update.message.reply_text(
                format_pending_message(r.pendencia),
                reply_markup=build_confirmation_keyboard(r.pendencia.id),
            )


async def _handle_query(update: Update, user_id: int, interpretacao: InterpretacaoTexto) -> None:
    if interpretacao.periodo_inicio is None or interpretacao.periodo_fim is None:
        await update.message.reply_text(format_missing_period_message())
        return

    totals = await get_totals(
        user_id, interpretacao.periodo_inicio, interpretacao.periodo_fim, interpretacao.categoria
    )
    msg = format_query_message(
        interpretacao.periodo_inicio, interpretacao.periodo_fim, interpretacao.categoria, totals
    )
    await update.message.reply_text(msg)
```
Uma mensagem de texto que a IA classifica como `transacao` mas devolve `transacoes` vazia cai no mesmo fallback de `nenhuma` — mesmo comportamento observável de hoje (mensagem sem transação identificável responde com o texto de fallback), só que agora compartilhado com o caso `nenhuma` explícito.

## Alternativas Consideradas e Descartadas

1. **Duas chamadas de IA separadas** (classificar intenção primeiro, extrair filtros/transação depois): descartada em favor de uma única chamada — decisão do usuário em INV009, dobraria custo/latência de toda mensagem de texto, inclusive as que já são transação hoje.
2. **Query direta no `GSI-Categoria`** do DynamoDB: descartada em favor de filtrar em memória sobre o `Query` por período já existente — decisão do usuário em INV009; volume baixo de bot pessoal não justifica mais um caminho de leitura para manter.
3. **Filtro de categoria via `WHERE categoria == ...` no SQL do SQLite** (mantendo `GROUP BY`): descartada porque criaria comportamento diferente entre backends — comparação exata no SQL vs. comparação normalizada (`normalize_description`) no DynamoDB. Escolhido: mesma lógica de comparação (normalizada) nos dois backends, centralizada em `repository/dedup.py`, ao custo de trocar `GROUP BY` por iteração em Python no SQLite (aceitável — volume baixo, e SQLite já é o backend legado/de transição, não o de produção).
4. **Resposta de consulta por categoria sempre no formato completo (entradas/saídas/saldo)**: descartada — decisão do usuário em INV009/SPEC011 R8, mostra só o total relevante da categoria.
5. **Reaproveitar `normalize_description` para normalizar categoria** (em vez de escrever uma função nova `normalize_categoria`): escolhida — a função já trata acentos, case e pontuação, é testada, e evita duplicar a mesma lógica de normalização de texto num segundo lugar do código.
6. **Manter `extract_text_transactions` como método separado ao lado de um novo método de classificação**: descartada pelo mesmo motivo da alternativa 1 — exigiria rodar classificação antes de saber qual extração chamar, dobrando chamadas de IA por mensagem.

## Arquivos a Modificar

| Arquivo | Mudança |
|---|---|
| `services/llm/provider.py` | novo DTO `InterpretacaoTexto`; `extract_text_transactions` → `interpret_text` na ABC |
| `prompts.py` | `build_text_extraction_prompt` → `build_text_interpretation_prompt`; novo `INTERPRETATION_SCHEMA` |
| `services/llm/bedrock_provider.py` | `extract_text_transactions`/`_parse_text_response` → `interpret_text`/`_parse_interpretation_response` |
| `services/llm/gemini_provider.py` | idem |
| `services/nlp_service.py` | `extract_text_transactions` → `interpret_text`; fallback de erro vira `InterpretacaoTexto(intencao="nenhuma")` |
| `repository/provider.py` | `get_totals_by_period` ganha parâmetro `categoria` na ABC |
| `repository/dynamo_repository.py` | `get_totals_by_period` filtra por categoria normalizada |
| `repository/sqlite_repository.py` | `get_totals_by_period` reescrito (sem `GROUP BY`), filtra por categoria normalizada |
| `services/transaction_service.py` | `get_totals` repassa `categoria` |
| `services/message_service.py` | novas `format_no_intent_message`, `format_missing_period_message`, `format_query_message`, `_periodo_label` |
| `handlers/text_handler.py` | roteamento por `intencao`, nova função `_handle_query` |
| `tests/test_prompts.py` | reescrito para `build_text_interpretation_prompt` |
| `tests/services/llm/test_provider.py` | `_ConcreteProvider` implementa `interpret_text` |
| `tests/services/llm/test_bedrock_provider.py` | reescrito para `interpret_text`; novos casos (consulta com/sem período, com/sem categoria, `nenhuma`, `intencao` inválida) |
| `tests/services/llm/test_gemini_provider.py` | idem |
| `tests/services/test_nlp_service.py` | reescrito para `interpret_text` |
| `tests/services/test_transaction_service.py` | novo teste de `get_totals` com `categoria` |
| `tests/repository/test_dynamo_repository.py` | novos testes de `get_totals_by_period` com categoria (match/sem match/normalização) |
| `tests/repository/test_sqlite_repository.py` | idem |
| `tests/services/test_message_service.py` | novos testes das 3 funções de formatação novas |
| `tests/handlers/test_text_handler.py` | reescrito para cobrir roteamento pelas 3 intenções |
| `docs/PATTERNS.md` | duas novas entradas em "Decisões Estabelecidas" (ver seção abaixo) |

Nenhum arquivo de `handlers/photo_handler.py`, `handlers/pdf_handler.py`, `services/ocr_service.py` é tocado (SPEC011 R11).

## Riscos

1. **Mudança de assinatura ampla e simultânea** (ABC + 2 providers + service + handler + prompt + ~10 arquivos de teste) — sem etapa intermediária de compatibilidade, porque não há consumidor externo do método além do próprio `text_handler`. Mitigação: TDD arquivo por arquivo, suíte completa (`pytest`) rodada a cada T do TASKS, mesmo padrão já usado nas fases anteriores.
2. **Não-determinismo do modelo em extração de período/categoria** — mesma classe de risco já documentada em `INV005`-`INV007` (Nova/Llama podem interpretar "esse mês" ou uma categoria de forma inconsistente entre rodadas). Mitigação: cenários de teste manual reais pós-implementação (mesmo padrão já usado em todas as fases anteriores), sem tentar resolver com mais regras de prompt do que o necessário nesta primeira versão.
3. **Correspondência de categoria pode falhar silenciosamente** (categoria da pergunta não bate com nenhuma categoria salva, por causa da falta de padronização documentada como limitação aceita em SPEC011) — resposta cairá no caminho "não teve nenhuma transação", o que é tecnicamente correto dado os dados, mas pode confundir o usuário achando que não gastou nada quando na verdade gastou sob outro nome de categoria. Não é um risco novo desta implementação, é a limitação já aceita — só reafirmando a visibilidade aqui.
4. **`SqliteTransactionRepository.get_totals_by_period` deixa de agregar no banco (`GROUP BY`) e passa a trazer todas as linhas do período para Python** — troca de desempenho aceitável para o volume de um bot pessoal, mas registrada conscientemente (alternativa 3 acima) para não ser redescoberta como "regressão" numa leitura futura do código.
