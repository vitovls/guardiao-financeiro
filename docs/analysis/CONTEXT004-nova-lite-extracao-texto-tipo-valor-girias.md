---
type: CONTEXT
version: 1.0.0
author: Victor Veloso
date: 2026-07-28
status: Draft
origem: "Descoberto durante teste manual de TASKS007-nova-lite-classificacao-texto.md (cenários adicionais de texto, além dos 7 casos diagnosticados no INV005)"
---

# CONTEXT004 — `nova-lite` erra tipo/sinal, valor e gírias monetárias na extração de texto

## Problema

`services/nlp_service.py` → `BedrockProvider.extract_text_transactions` (`TEXT_MODEL_ID = "us.amazon.nova-lite-v1:0"`, trocado em `TASKS007`) resolveu o falso-negativo de classificação booleana diagnosticado no `INV005`/`CONTEXT001`, mas variantes de texto mais informais/coloquiais expõem falhas **diferentes**, na extração dos campos (`tipo`, `valor`, `e_transacao`), não só no booleano "é transação?":

- **Falso negativo ainda ocorre em frase mais elaborada**: `"Meu salario caiu de 3700 reais"` → `e_transacao: false` (não reconhecida), mesmo sendo claramente uma transação de entrada.
- **Sinal/tipo trocado (entrada↔saída)**:
  - `"Salario caiu 3700 reais"` → registrada como `saida` de **-R$3700** (devia ser `entrada` de R$3700).
  - `"Boleto de 150 venceu hoje"` → registrada como `entrada` de R$150 (um boleto a pagar é `saida`, não `entrada`).
- **Valor não extraído quando implícito**: `"Gastei com mercado"` (sem valor explícito no texto) → registrada com `valor = 0.00`.
- **Gíria monetária ("conto") mal convertida**:
  - `"Pix de 10 conto caiu aqui"` → virou `entrada` de **R$1000,00** (10 conto deveria corresponder a R$10, não R$1000 — magnitude 100x errada).
  - `"Estornou 40 conto que cobraram errado oh"` → virou `entrada` de **R$4000** (mesma distorção de magnitude, ~100x).

**Não é a mesma causa raiz do `INV005`/`CONTEXT001`.** Aquele diagnóstico foi sobre a confiabilidade do booleano `e_transacao` em frases diretas e literais (`"gastei 10 reais no mercado"`), confirmado como problema do modelo `nova-micro` via A/B (mesmo prompt, `nova-lite` acertava). Aqui `nova-lite` já é o modelo em uso (trocado no `TASKS007`) e ainda assim erra — mas em dimensões diferentes: sinal/tipo, valor numérico e interpretação de gíria, que podem ser tanto limitação do modelo quanto ausência de instrução explícita no prompt (`build_text_extraction_prompt`, `prompts.py`).

## Evidência coletada

Relato do usuário durante teste manual exploratório do `TASKS007` (cenário 4, fluxo de texto via Telegram, `LLM_PROVIDER=bedrock` real, `nova-lite`), fora dos 7 casos formalmente cobertos pelo `INV005`. Ainda não reproduzido de forma controlada (sem variação de `temperature`, sem múltiplas rodadas por input, sem comparação A/B de prompt) — ver seção seguinte.

| Input | Resultado observado | Resultado esperado |
|---|---|---|
| `"Meu salario caiu de 3700 reais"` | Não reconhecida (`e_transacao: false`) | `entrada`, R$3700 |
| `"Salario caiu 3700 reais"` | `saida`, -R$3700 | `entrada`, R$3700 |
| `"Gastei com mercado"` | `saida`, R$0,00 | Ambíguo — sem valor explícito no texto (ver "Não investigado") |
| `"Pix de 10 conto caiu aqui"` | `entrada`, R$1000,00 | `entrada`, R$10,00 |
| `"Boleto de 150 venceu hoje"` | `entrada`, R$150,00 | `saida`, R$150,00 |
| `"Estornou 40 conto que cobraram errado oh"` | `entrada`, R$4000,00 | `entrada`, R$40,00 |

## Causa raiz

**Não investigada ainda.** Hipóteses a explorar, sem confirmação:

- `build_text_extraction_prompt` (`prompts.py`) pode não instruir explicitamente as convenções de sinal/tipo para verbos como "caiu" (entrada), "venceu"/"boleto" (saída antes do pagamento) — diferente de `TASKS007`, onde ficou confirmado via A/B que o prompt não era a causa (mesmo prompt funcionava em `nova-lite`); aqui não há esse A/B ainda.
- Gírias monetárias brasileiras ("conto" = R$1, tradicionalmente, ou R$1000 a depender da região/época) não estão documentadas em nenhum lugar do prompt — o modelo pode estar aplicando uma conversão arbitrária (aparenta ser ×100 em ambos os casos observados, mas com apenas 2 amostras não dá para confirmar um padrão).
- Ausência de valor explícito no texto (`"Gastei com mercado"`) pode não ter instrução clara sobre o que fazer — `valor = 0.00` pode ser o comportamento "correto" na ausência de especificação de contrato, ou pode ser necessário decidir um comportamento de produto (rejeitar a mensagem? pedir valor? usar `0.00` como sinal de "revisar"), um pouco como já existe para `categoria` vazia (`DEFAULT_CATEGORIA`, ver `docs/PATTERNS.md`).

## Não investigado ainda (próximos passos pra quem pegar isso)

- Reproduzir cada um dos 6 casos com múltiplas chamadas (`temperature: 0` e também sem fixar) para separar não-determinismo de erro sistemático.
- Testar variações do prompt (`build_text_extraction_prompt`) instruindo explicitamente convenções de sinal por verbo/contexto (ex.: "caiu"/"recebi" = entrada; "venceu"/"paguei"/"comprei" = saída) e ver se resolve sem trocar de modelo.
- Decidir e documentar o significado de "conto" no domínio do produto (não é universal no português do Brasil) — se o produto quer suportar gíria, precisa de uma tabela de conversão explícita no prompt, não inferência livre do modelo.
- Decidir o comportamento de produto para valor ausente/implícito (`"Gastei com mercado"`) — hoje cai silenciosamente em `0.00`, sem alerta ao usuário (diferente do padrão já estabelecido para categoria vazia).
- Confirmar se essas falhas também ocorrem em `nova-pro` (tier acima de `nova-lite`) ou se são específicas deste tier — daria pista se é limitação de modelo ou de prompt.

## Recomendação

Investigar como task própria (`/map-task`), fora do escopo de `TASKS007` (que resolveu só o booleano `e_transacao` das 7 frases do `INV005`, não a extração de tipo/valor/gírias). Prioridade sugerida: média-alta — afeta a confiabilidade dos valores registrados (sinal trocado é pior que não reconhecer, pois entra silenciosamente errado no saldo), mas exige decisões de produto (convenção de gíria, tratamento de valor ausente) antes de virar código, não só ajuste técnico.
