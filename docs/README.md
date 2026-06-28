# Convenções de Documentação (SDD)

## Roteamento por ambiguidade (não por número de arquivos)

- **Design conhecido** — causa-raiz clara, abordagem decidida, sem trade-off em aberto, nenhuma decisão que outras tasks vão herdar → gere apenas `TASKSXXX` autocontido.
- **Ambíguo** — abordagem em aberto, trade-off real, ou decisão que tasks futuras herdarão → gere `SPECXXX` + `PLNXXX` + `TASKSXXX` referenciando ambos.

Número de arquivos tocados é modificador de rigor (mais testes, mais cuidado no PLN), não gatilho de separação.

## Numeração

- `SPEC`, `PLN` e `TASKS` de um mesmo conjunto compartilham o número (ex: `SPEC001`, `PLN001`, `TASKS001`).
- `INV` tem série própria em `docs/analysis/INV*.md`.
- `ADR` tem série própria em `docs/adrs/ADR*.md`.

## Frontmatter (todos os docs)

```yaml
type:    # SPEC | PLN | TASKS | INV | ADR
version: # semver, ex: 1.0.0
author:  # nome
date:    # YYYY-MM-DD
status:  # Draft | Approved | In Progress | Done
# TASKS também referencia:
spec:    # docs/specs/SPECXXX-slug.md (se existir)
plan:    # docs/plans/PLNXXX-slug.md (se existir)
inv:     # docs/analysis/INVXXX-slug.md (se existir)
```

## Ciclo de status do TASKS

`Draft → Approved → In Progress → Done`

`/start-task` recusa rodar se `status: Draft`.

## ADR vs entrada em PATTERNS.md

Decisão reutilizável por tasks futuras → entrada de 3-4 linhas em `docs/PATTERNS.md` (padrão).
Só promova a `ADR` formal em `docs/adrs/` se `PATTERNS.md` ficar poluído de decisões.
