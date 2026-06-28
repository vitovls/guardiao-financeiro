# PATTERNS.md — Padrões e Decisões do Projeto

Leitura obrigatória em toda sessão de implementação.

## Padrões Estabelecidos

### DTO vs Entity — separação obrigatória

`models.Transacao` (Pydantic) é o contrato de extração do Gemini. `TransacaoEntity` (SQLAlchemy) é o que é persistido. Nunca fundir. O DTO não sabe que banco existe; a Entity não sabe que Gemini existe. A conversão ocorre no repository.

### Repository concreto sem interface

`repository/transacao.py` é uma classe concreta sem `Protocol`/`ABC`. Python tem duck typing: um teste pode passar um objeto fake com a mesma assinatura sem herança formal. Só revisar se aparecer uma segunda implementação real.

### Service como camada de orquestração intencional

`services/transaction_service.py` existe entre handler e repository por consistência arquitetural, não porque há lógica hoje. É o lugar reservado para dedup quando for implementado. Repasse direto é intencional, não cheiro de código.

### IA apenas na extração

`ocr_service.py` e `nlp_service.py` são os únicos pontos que chamam Gemini. Qualquer lógica de comparação, dedup ou decisão é determinística — sem chamada de IA, por determinismo, testabilidade e custo.

### Inserção em lote

`session.add()` para todas as entidades do lote, `session.commit()` uma vez só ao final. Nunca `commit()` dentro de loop.

### Arquivos temporários

Foto e PDF baixados para `fotos/` são removidos com `try/finally` imediatamente após o OCR, antes de qualquer outra operação.

## Decisões Estabelecidas

<!-- Preenchido pelo /map-task quando uma decisão for reutilizável por tasks futuras. -->
