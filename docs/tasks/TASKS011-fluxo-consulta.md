---
tipo: TASKS
numero: TASKS011
slug: fluxo-consulta
inv: INV009
spec: SPEC011
plan: PLN011
status: Done
version: 1.1.0
---

# TASKS011 — Fluxo de consulta (Fase 6)

Contexto completo em `docs/analysis/INV009-fluxo-consulta.md`, `docs/specs/SPEC011-fluxo-consulta.md` e `docs/plans/PLN011-fluxo-consulta.md` — leitura obrigatória antes de implementar, junto com `CLAUDE.md` e `docs/PATTERNS.md`. Este documento só decompõe o PLN em unidades executáveis; todo código-fonte (Antes/Depois completo) já está escrito no PLN, aqui só se referencia.

Candidatos a fase futura identificados durante o design (padronização de categoria; consulta por listagem/ranking individual) estão registrados em `docs/analysis/CONTEXT006-candidatos-fase-futura-fluxo-consulta.md` — **fora de escopo**, não implementar aqui.

## Decisão de Design (resumo, ver PLN011 para o racional completo)

- Classificação de intenção (`transacao`/`consulta`/`nenhuma`) e extração de filtros de consulta (período/categoria) acontecem na **mesma chamada de IA** que hoje só extrai transação — novo método `LLMProvider.interpret_text` substitui `extract_text_transactions`, retornando o DTO `InterpretacaoTexto`.
- Filtro de categoria em `get_totals_by_period` é feito **em memória**, reaproveitando `repository.dedup.normalize_description` — sem tocar o `GSI-Categoria`.
- Resposta de consulta com categoria mostra só o total daquela categoria; sem categoria, mostra o resumo completo (entradas/saídas/saldo), igual ao formato já usado hoje.

## T1 — DTO `InterpretacaoTexto` e novo contrato em `LLMProvider`

- [x] T1

**Objetivo:** introduzir o DTO de retorno e trocar `extract_text_transactions` por `interpret_text` na ABC.

**Arquivo:** `services/llm/provider.py`. Antes/Depois completo: PLN011, seção "`services/llm/provider.py`".

**TDD:**
1. `tests/services/llm/test_provider.py`: trocar `_ConcreteProvider.extract_text_transactions` por `async def interpret_text(self, text: str) -> InterpretacaoTexto: return InterpretacaoTexto(intencao="nenhuma")`. Testes de instanciação (`test_concrete_subclass_can_be_instantiated`, `test_abstract_class_cannot_be_instantiated_directly`) continuam passando sem mudança de asserts.
2. Implementar `InterpretacaoTexto` e trocar a assinatura abstrata em `services/llm/provider.py` (código exato no PLN011).

**Critério de aceitação:** `InterpretacaoTexto(intencao="transacao")` aceita `transacoes`/`periodo_inicio`/`periodo_fim`/`categoria` com defaults (`[]`/`None`/`None`/`None`); `InterpretacaoTexto(intencao="invalido")` levanta `ValidationError` (Literal). `pytest tests/services/llm/test_provider.py` verde.

## T2 — Prompt de interpretação de texto

- [x] T2

**Objetivo:** substituir `build_text_extraction_prompt` por `build_text_interpretation_prompt`, com o schema estendido.

**Arquivo:** `prompts.py`. Código exato (schema + prompt completo, preservando todas as regras de sinal/gíria/valor ausente já existentes): PLN011, seção "`prompts.py`".

**TDD — reescrever `tests/test_prompts.py`:**
1. `test_build_text_interpretation_prompt_contains_date_text_and_intencao` — substitui o teste antigo de `e_transacao`; assert que o prompt contém a data, o texto do usuário, e a palavra `"intencao"`.
2. `test_build_text_interpretation_prompt_instructs_three_intencoes` — assert que `"transacao"`, `"consulta"` e `"nenhuma"` aparecem no prompt.
3. `test_build_text_interpretation_prompt_instructs_periodo_extraction` — assert que menções a `"periodo_inicio"`/`"periodo_fim"` e a instrução de não inventar período padrão aparecem (ex.: checar substring `"nunca invente um período padrão"` ou equivalente do texto final).
4. `test_build_text_interpretation_prompt_instructs_categoria_extraction` — assert que `"categoria"` aparece associado à extração de consulta.
5. Manter (adaptando ao novo nome de função) os testes já existentes: `test_build_document_extraction_prompt_contains_label_and_schema` (sem mudança), `test_build_text_interpretation_prompt_instructs_sign_convention` (`"boleto"`), `test_build_text_interpretation_prompt_instructs_conto_conversion` (`"conto"`, `"R$1"`), `test_build_text_interpretation_prompt_instructs_valor_ausente` (`"não a descarte"`).

**Critério de aceitação:** `pytest tests/test_prompts.py` verde; `build_document_extraction_prompt` continua sem nenhuma mudança de comportamento.

## T3 — `BedrockProvider.interpret_text`

- [x] T3

**Nota de execução:** `test_missing_expected_key_retries_and_raises_bedrock_output_error_if_persists` (item 7) precisou de payload diferente do sugerido literalmente. `InterpretacaoTexto.transacoes` tem default `[]` (T1), então `{"intencao": "transacao"}` já é válido — não reproduz mais "chave esperada faltando". Ajustado para `{"transacoes": []}` (omite a única chave obrigatória, `intencao`), preservando a intenção do teste. Mesma classe de ajuste autorizada previamente pelo usuário para correções mecânicas de payload após mudança de default do Pydantic (sem mudança de design/contrato) — aplicada sem bump de versão adicional.

**Objetivo:** portar a extração de texto do Bedrock para o novo contrato.

**Arquivo:** `services/llm/bedrock_provider.py`. Antes/Depois: PLN011, seção "`services/llm/bedrock_provider.py`". `TEXT_MODEL_ID` não muda.

**TDD — reescrever `tests/services/llm/test_bedrock_provider.py`** (os testes de retry/throttling/markdown-fence genéricos continuam válidos, só trocando o payload de resposta mockado de `{"e_transacao": ..., "transacoes": ...}` para `{"intencao": ..., "transacoes": ..., "periodo_inicio": ..., "periodo_fim": ..., "categoria": ...}` e o nome do método chamado):
1. `test_interpret_text_returns_transacao_intent_and_calls_converse_correctly` — substitui `test_extract_text_transactions_returns_transacoes_and_calls_converse_correctly`; resposta com `"intencao": "transacao"`, `result.intencao == "transacao"`, `result.transacoes[0].descricao == "mercado"`.
2. `test_interpret_text_returns_consulta_intent_with_periodo` — resposta `{"intencao": "consulta", "transacoes": [], "periodo_inicio": "2026-07-01", "periodo_fim": "2026-07-31", "categoria": null}`; assert `result.intencao == "consulta"`, `result.periodo_inicio == date(2026, 7, 1)`, `result.periodo_fim == date(2026, 7, 31)`, `result.categoria is None`.
3. `test_interpret_text_returns_consulta_intent_with_categoria` — mesmo shape com `"categoria": "mercado"`; assert `result.categoria == "mercado"`.
4. `test_interpret_text_returns_consulta_intent_without_periodo` — `"periodo_inicio": null, "periodo_fim": null`; assert ambos `None` (sem erro).
5. `test_interpret_text_returns_nenhuma_intent` — `{"intencao": "nenhuma", "transacoes": [], "periodo_inicio": null, "periodo_fim": null, "categoria": null}`; assert `result.intencao == "nenhuma"`.
6. `test_interpret_text_invalid_intencao_retries_and_raises_bedrock_output_error` — `"intencao": "invalido"` nas duas tentativas; assert `pytest.raises(BedrockOutputError)` e `client.converse.call_count == 2` (mesmo padrão do teste equivalente já existente para `tipo` inválido em `Transacao`).
7. Adaptar (só trocando o método chamado e o payload) todos os testes já existentes que não mudam de intenção: `_sets_max_tokens_to_avoid_truncation`, `_parses_response_wrapped_in_json_markdown_fence`, `_parses_response_wrapped_in_bare_markdown_fence`, `_does_not_set_temperature`, `test_throttling_retries_and_succeeds_on_third_attempt`, `test_throttling_on_all_attempts_propagates`, `test_validation_error_propagates_immediately_without_retry`, `test_malformed_output_retries_once_and_succeeds_on_second_attempt`, `test_malformed_output_on_both_attempts_raises_bedrock_output_error`, `test_missing_expected_key_retries_and_raises_bedrock_output_error_if_persists` (usar `intencao` em vez de `e_transacao` no payload de resposta).
8. `test_extract_document_transactions_*` (imagem/PDF/unsupported mime/temperatura zero) — **não mudam**, `extract_document_transactions` é intocado.

**Critério de aceitação:** `pytest tests/services/llm/test_bedrock_provider.py` verde.

## T4 — `GeminiProvider.interpret_text`

- [x] T4

**Objetivo:** paridade com Bedrock — `GeminiProvider` também implementa `interpret_text` (necessário porque `LLM_PROVIDER=gemini` continua sendo um valor válido em `run_polling/config.py`).

**Arquivo:** `services/llm/gemini_provider.py`. Antes/Depois: PLN011, seção "`services/llm/gemini_provider.py`".

**TDD — reescrever `tests/services/llm/test_gemini_provider.py`.** O arquivo usa um helper `_mock_client(response_text: str) -> Mock` que seta `client.models.generate_content.return_value = Mock(text=response_text)` — reaproveitar exatamente esse helper, só trocando o payload JSON e o método chamado (`provider.interpret_text(...)` em vez de `provider.extract_text_transactions(...)`):
1. `test_interpret_text_returns_transacao_intent_when_present` — substitui `test_extract_text_transactions_returns_transacoes_when_present`; payload `{"intencao": "transacao", "transacoes": [{"data": "2026-07-26", "descricao": "mercado", "valor": 30.0, "tipo": "saida", "categoria": "alimentacao"}], "periodo_inicio": null, "periodo_fim": null, "categoria": null}`; assert `result.intencao == "transacao"`, `result.transacoes[0].descricao == "mercado"`.
2. `test_interpret_text_returns_nenhuma_intent` — substitui `test_extract_text_transactions_returns_empty_when_not_transacao`; payload `{"intencao": "nenhuma", "transacoes": [], "periodo_inicio": null, "periodo_fim": null, "categoria": null}`; assert `result.intencao == "nenhuma"` e `result.transacoes == []`.
3. `test_interpret_text_returns_consulta_intent_with_periodo` — payload com `"intencao": "consulta"`, `"periodo_inicio": "2026-07-01"`, `"periodo_fim": "2026-07-31"`, `"categoria": null`; assert os dois campos viram `date(2026, 7, 1)`/`date(2026, 7, 31)`.
4. `test_interpret_text_returns_consulta_intent_with_categoria` — mesmo shape com `"categoria": "mercado"`; assert `result.categoria == "mercado"`.
5. `test_extract_document_transactions_image_jpeg_returns_transacoes_and_prompt_mentions_imagem` e `test_extract_document_transactions_pdf_prompt_mentions_pdf` — **não mudam**, `extract_document_transactions` é intocado.

**Critério de aceitação:** `pytest tests/services/llm/test_gemini_provider.py` verde.

## T5 — `nlp_service.interpret_text`

- [x] T5

**Objetivo:** expor o novo contrato ao handler, preservando a garantia de erro-nunca-vaza.

**Arquivo:** `services/nlp_service.py`. Antes/Depois: PLN011, seção "`services/nlp_service.py`".

**TDD — reescrever `tests/services/test_nlp_service.py`:**
1. `test_interpret_text_returns_provider_result` — substitui `test_extract_text_transactions_returns_provider_result`; fake provider com `interpret_text` retornando uma `InterpretacaoTexto(intencao="transacao", transacoes=[...])`; assert resultado igual.
2. `test_interpret_text_returns_nenhuma_when_provider_raises` — substitui `test_extract_text_transactions_returns_empty_list_when_provider_raises`; fake provider que levanta `RuntimeError`; assert `result == InterpretacaoTexto(intencao="nenhuma")`.

**Critério de aceitação:** `pytest tests/services/test_nlp_service.py` verde.

## T6 — Filtro de categoria em `get_totals_by_period` (ABC + DynamoDB + SQLite)

- [x] T6

**Objetivo:** `get_totals_by_period` aceita `categoria: str | None = None`, comparando com `normalize_description`.

**Arquivos:** `repository/provider.py`, `repository/dynamo_repository.py`, `repository/sqlite_repository.py`. Antes/Depois completo de cada um: PLN011, seções correspondentes.

**TDD:**
1. `tests/repository/test_provider.py`: atualizar `_ConcreteRepository.get_totals_by_period` para aceitar `categoria=None` (consistência de assinatura; não é estritamente exigido pelo Python ABC, mas evita divergência de assinatura entre o fake e o contrato real).
2. `tests/repository/test_dynamo_repository.py` — novos testes ao lado de `test_get_totals_by_period_sums_excludes_config_and_uses_sentinel`:
   - `test_get_totals_by_period_filters_by_categoria` — Items com `categoria` variada (`"mercado"`, `"lazer"`); chamar com `categoria="mercado"`; assert soma só considera os itens com essa categoria.
   - `test_get_totals_by_period_categoria_filter_is_normalized` — Item salvo com `categoria="Mercado"` (case diferente) ou com acento (ex. `"Alimentação"`); chamar com `categoria="mercado"`/`"alimentacao"`; assert que ainda encontra (normalização via `normalize_description`).
   - `test_get_totals_by_period_categoria_without_match_returns_zeros` — nenhum item bate com a categoria pedida; assert `{"entradas": 0.0, "saidas": 0.0}`.
3. `tests/repository/test_sqlite_repository.py` — ao lado de `test_get_totals_sums_entradas_and_saidas`, os três mesmos casos (filtra por categoria; normaliza; sem match retorna zero), usando `session_factory` e `_transacao(categoria=...)` já existentes no arquivo.

**Critério de aceitação:** `pytest tests/repository/test_dynamo_repository.py tests/repository/test_sqlite_repository.py tests/repository/test_provider.py` verde; os testes de `get_totals_by_period` já existentes (sem categoria) continuam passando sem alteração de asserts.

## T7 — `transaction_service.get_totals` repassa categoria

- [x] T7

**Nota de execução:** o teste já existente `test_get_totals_delegates_to_repository_and_returns_result` precisou de ajuste no assert (`assert_awaited_once_with(42, start, end)` → `..., None`), já que o código do PLN011 repassa `categoria` sempre posicionalmente (mesmo `None` por default). Ajuste mecânico, mesma categoria já autorizada em T3.

**Objetivo:** propagar o parâmetro `categoria` do service para o repository.

**Arquivo:** `services/transaction_service.py`. Antes/Depois: PLN011, seção correspondente.

**TDD — `tests/services/test_transaction_service.py`:**
1. Adicionar `test_get_totals_passes_categoria_to_repository` ao lado de `test_get_totals_delegates_to_repository_and_returns_result` — chamar `get_totals(42, start, end, categoria="mercado")`; assert `repository.get_totals_by_period.assert_awaited_once_with(42, start, end, "mercado")`.
2. O teste já existente (sem categoria) deve continuar passando chamando `get_totals(42, start, end)` — `categoria` default `None`, repassado como `None`.

**Critério de aceitação:** `pytest tests/services/test_transaction_service.py` verde.

## T8 — Formatação de resposta de consulta e fallback

- [x] T8

**Objetivo:** três funções novas em `message_service.py`.

**Arquivo:** `services/message_service.py`. Código exato: PLN011, seção "`services/message_service.py`".

**TDD — `tests/services/test_message_service.py`** (arquivo já existe com testes de `format_message`/`format_pending_message`/`split_message`; adicionar, não remover):
1. `test_format_no_intent_message_mentions_transacao_and_consulta_examples` — assert que a mensagem contém um exemplo de transação e um de consulta (ex.: `"Gastei"` e `"Quanto"`, ou os textos exatos do PLN).
2. `test_format_missing_period_message_asks_for_period` — assert texto contém `"período"`.
3. `test_format_query_message_without_categoria_shows_entradas_saidas_saldo` — `totals={"entradas": 1000.0, "saidas": 300.0}`; assert as 3 linhas (entradas, saídas, saldo=700.0) aparecem formatadas como `R$ X.XX`.
4. `test_format_query_message_without_categoria_and_zero_totals_shows_explicit_no_transactions` — `totals={"entradas": 0.0, "saidas": 0.0}`; assert mensagem explícita de "não teve nenhuma transação" (R9), **não** `"R$ 0.00"` isolado.
5. `test_format_query_message_with_categoria_shows_only_categoria_total` — `categoria="mercado"`, `totals={"entradas": 0.0, "saidas": 320.0}`; assert menção a `"mercado"` e ao valor `320.00`, e que **não** menciona "saldo"/entradas gerais.
6. `test_format_query_message_with_categoria_and_zero_totals_shows_explicit_no_transactions` — mesmo caso de (4) mas com `categoria` preenchida.
7. `test_format_query_message_with_categoria_and_both_entradas_and_saidas_shows_both` — `categoria="freelance"`, `totals={"entradas": 500.0, "saidas": 50.0}` (caso raro de categoria com movimento nos dois sentidos); assert que ambos os valores aparecem.
8. `test_format_query_message_same_month_uses_month_year_label` e `test_format_query_message_different_months_uses_date_range_label` — cobrir `_periodo_label` indiretamente (start/end no mesmo mês vs. em meses diferentes).

**Critério de aceitação:** `pytest tests/services/test_message_service.py` verde; `format_message`/`format_pending_message`/`split_message` continuam com os mesmos testes/comportamento de hoje.

## T9 — Roteamento por intenção em `handlers/text_handler.py`

- [x] T9

**Nota de execução:** `InterpretacaoTexto(intencao="transacao", transacoes=["transacao-fake"])` (sentinela string, item 1/5 do TDD) viola a validação Pydantic de `transacoes: list[Transacao]`. Usado `InterpretacaoTexto.model_construct(...)` (bypassa validação) para preservar o mesmo sentinela literal `"transacao-fake"` e os asserts já descritos no TASKS. Ajuste mecânico, mesma categoria já autorizada em T3/T7.

**Objetivo:** amarrar tudo — a mensagem de texto passa a rotear por `intencao`.

**Arquivo:** `handlers/text_handler.py`. Código exato (arquivo inteiro): PLN011, seção "`handlers/text_handler.py`".

**TDD — reescrever `tests/handlers/test_text_handler.py`.** O arquivo usa `monkeypatch.setattr(text_handler, "<nome>", AsyncMock/Mock(...))` para substituir as funções importadas em `handlers/text_handler.py` (não classes/objetos — são funções soltas), e um helper `_build_update(text=...)` que monta `update.effective_user.id = 42`, `update.update_id = 1`, `update.message.text = text`, `update.message.reply_text = AsyncMock()`. Reaproveitar esse mesmo helper. Todo `monkeypatch.setattr(text_handler, "extract_text_transactions", ...)` vira `monkeypatch.setattr(text_handler, "interpret_text", ...)` retornando uma `InterpretacaoTexto` (importar de `services.llm.provider`) em vez de uma lista:
1. `test_happy_path_saves_transactions_and_replies_with_formatted_message` — adaptar: `interpret_text` mockado retorna `InterpretacaoTexto(intencao="transacao", transacoes=["transacao-fake"])` (mesmo valor sentinela usado hoje); resto do teste (asserts de `save_transactions`, `format_message`, `reply_text`) não muda.
2. `test_no_transactions_identified_replies_and_does_not_save` — renomear para `test_transacao_intent_sem_transacoes_replies_fallback_and_does_not_save`; `interpret_text` retorna `InterpretacaoTexto(intencao="transacao", transacoes=[])`; trocar o assert de texto de `"não foi identificada"` para o novo texto de `format_no_intent_message()` (mockar essa função também, como já é feito com `format_message` no teste de pendência, e assertar `reply_text` chamado com o valor mockado — evita acoplar o teste ao texto literal).
3. `test_nenhuma_intent_replies_fallback` (novo) — `interpret_text` retorna `InterpretacaoTexto(intencao="nenhuma")`; mockar `format_no_intent_message`; assert `reply_text` chamado com o valor mockado, `save_transactions` não chamado.
4. `test_already_processed_update_skips_extraction` — trocar `extract_text_transactions` por `interpret_text` no monkeypatch e no assert (`interpret_text.assert_not_awaited()`); resto igual.
5. `test_pending_result_sends_extra_message_with_keyboard` — trocar o monkeypatch de `extract_text_transactions` por `interpret_text` retornando `InterpretacaoTexto(intencao="transacao", transacoes=["transacao-fake"])`; resto igual.
6. `test_consulta_sem_periodo_pede_periodo` (novo) — `interpret_text` retorna `InterpretacaoTexto(intencao="consulta", periodo_inicio=None, periodo_fim=None)`; mockar `format_missing_period_message`; assert `reply_text` chamado com o valor mockado e `get_totals` (monkeypatch em `text_handler`) **não** chamado.
7. `test_consulta_com_periodo_chama_get_totals_e_formata` (novo) — `interpret_text` retorna `InterpretacaoTexto(intencao="consulta", periodo_inicio=date(2026, 7, 1), periodo_fim=date(2026, 7, 31), categoria=None)`; mockar `get_totals` (`AsyncMock(return_value={"entradas": 0.0, "saidas": 100.0})`) e `format_query_message`; assert `get_totals.assert_awaited_once_with(42, date(2026, 7, 1), date(2026, 7, 31), None)` e `format_query_message` chamado com os mesmos 4 argumentos + o resultado de `get_totals`.
8. `test_consulta_com_categoria_repassa_categoria` (novo) — mesmo caso de (7) com `categoria="mercado"`; assert `get_totals` chamado com `categoria="mercado"` como último argumento.

**Critério de aceitação:** `pytest tests/handlers/test_text_handler.py` verde.

## Ordem de Execução

T1 → T2 → T3 → T4 → T5 → T6 → T7 → T8 → T9. Cada T é um commit próprio (TDD: teste vermelho → implementação → verde).

**Nota (v1.1.0):** `LLMProvider.interpret_text` é um único método abstrato compartilhado por `BedrockProvider`/`GeminiProvider`/`nlp_service` (que instancia o provider concreto no nível de módulo via `factory.py`), sem shim de compatibilidade intermediário (decisão já registrada em PLN011, Risco 1). Trocar a assinatura na ABC (T1) torna `BedrockProvider`/`GeminiProvider` não instanciáveis até cada um implementar o novo método (T3/T4), e qualquer teste que importe `nlp_service`/`handlers.text_handler` quebra na coleta até T5. Isso foi descoberto empiricamente ao rodar a suíte completa após T1 (37 falhas) — não é regressão a corrigir, é consequência estrutural aceita da troca de contrato sem shim. Por isso: **de T1 a T4, o gate é o critério de aceitação específico já escrito em cada T** (comando `pytest` escopado ao(s) arquivo(s) daquele T). **Correção empírica (confirmada ao final de T5):** `handlers/text_handler.py` só é tocado em T9 e ainda importa `extract_text_transactions` de `nlp_service` — então `tests/handlers/test_text_handler.py` continua quebrado na coleta até T9, mesmo com a cadeia ABC→Bedrock→Gemini→nlp_service já consistente desde T5. De **T5 a T8**, o gate é `pytest` completo **ignorando `tests/handlers/test_text_handler.py`** (confirmado: os outros 149 testes passam já em T5); a suíte inteira sem exceção (incluindo esse arquivo) só volta a ser o gate a partir de **T9**.

## Regra do Escoteiro / Testes

- `pytest` (suíte inteira) 100% verde ao final de cada T a partir do T5 (T1-T4 usam o critério de aceitação escopado de cada T — ver nota em "Ordem de Execução"), sem exceção.
- Nenhuma chamada real a LLM/AWS em teste automatizado — só providers/clients mockados (`docs/PATTERNS.md`, "Test runner do projeto").
- Toda lógica pura nova (formatação, filtro de categoria, roteamento) tem teste automatizado; só o comportamento fim-a-fim com Bedrock/DynamoDB reais fica para os Cenários de Teste Manual.

## Cenários de Teste Manual

Rodar com o bot real (`LLM_PROVIDER=bedrock`, `DB_BACKEND=dynamo`, produção ou ambiente equivalente), após a suíte automatizada 100% verde:

1. [x] Enviar "Gastei 30 reais no mercado" — confirmar que salva exatamente como hoje (sem regressão, SPEC011 critério 1). **PASSOU** (executado pelo usuário).
2. [x] Enviar "quanto gastei em julho de 2026?" (ou mês/ano correntes) — confirmar resumo de entradas/saídas/saldo condizente com os dados reais do usuário. **PASSOU**.
3. [x] Enviar uma consulta por categoria usando uma categoria real já salva pelo usuário (ex.: "quanto gastei em X esse mês?") — confirmar que mostra só o total daquela categoria. **PASSOU**.
4. [x] Enviar uma consulta sem período reconhecível (ex.: "quanto eu já gastei no total?") — confirmar que pede o período, sem tentar adivinhar. **PASSOU**.
5. [x] Enviar uma consulta de período/categoria sem nenhuma transação correspondente — confirmar mensagem explícita de "não teve nenhuma transação", nunca "R$ 0,00" seco. **PASSOU**.
6. [x] Enviar "oi" ou uma pergunta não financeira — confirmar fallback mencionando os dois tipos de uso (transação e consulta). **PASSOU**.
7. [x] Enviar uma foto ou PDF de extrato — confirmar que o fluxo de OCR continua idêntico, sem qualquer menção a intenção/consulta (SPEC011 R11). **PASSOU**.

Todos os 7 cenários executados e confirmados pelo usuário em 2026-08-05.

## Fora de Escopo

Mesmos Non-Goals de SPEC011: listagem de transações individuais, sinônimos/correspondência aproximada de categoria, uso do `GSI-Categoria`, período padrão implícito, mudanças em `GeminiProvider`/`BedrockProvider` além do contrato de interpretação, Fase 6b (conselhos financeiros), remoção de `GeminiProvider`/`GEMINI_API_KEY`. Candidatos a fase futura documentados em `docs/analysis/CONTEXT006-candidatos-fase-futura-fluxo-consulta.md`.

## Validação Final contra SPEC011

- [x] R1-R3 (classificação de intenção): T1, T2, T3, T4, T9. Confirmado via suíte automatizada (173 testes verdes).
- [x] R4-R6 (extração de filtros de consulta, normalização de categoria): T2, T3, T4, T6. Confirmado via suíte automatizada.
- [x] R7-R10 (agregação e resposta): T6, T7, T8. Confirmado via suíte automatizada.
- [x] R11 (foto/PDF intocados): confirmado por `git diff --stat` — `handlers/photo_handler.py`, `handlers/pdf_handler.py`, `services/ocr_service.py` sem nenhuma alteração.
- [x] R12 (dedup/pendência/salvamento intocados quando `transacao`): T9 (fluxo de transação delega exatamente às mesmas funções de hoje, testes de dedup/pendência de T3/T6 inalterados e verdes).
- [x] Critérios de aceitação 1-9 de SPEC011: automatizados cobertos (T1-T9) e Cenários de Teste Manual 1-7 executados pelo usuário — todos passaram.
- [x] `docs/PATTERNS.md` já atualizado (feito no PLN011) com as duas decisões reutilizáveis ("Classificação de intenção..." e "Filtro de categoria em consulta...") — nenhuma decisão reutilizável nova surgiu durante a implementação (só ajustes mecânicos de teste, registrados nas notas de T3/T7/T9).
