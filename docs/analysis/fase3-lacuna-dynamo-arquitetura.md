# Achado — lacuna arquitetural no agente de conselho

> Contexto adicional ao `plano-migracao-guardiao-financeiro.md` (não substitui, complementa). Investigando mais a fundo o desenho do "agente de conselho", encontrei um ponto que a arquitetura atual (código, DynamoDB, plano de fases) ainda não cobre.

## O que já estava certo

O agente de conselho ("posso comprar X sem comprometer?", "quanto posso gastar com lazer nesse fds?") entra no mesmo fork de classificação que registro e consulta — isso está correto, porque essa etapa decide **intenção do usuário**, não arquitetura de execução. As três mensagens ("gastei 50 no ifood" / "quanto gastei com delivery?" / "posso comprar um fone de 200?") são igualmente identificáveis pela Nova Micro na classificação.

Onde ele deixa de ser igual a consulta é na **execução**: consulta é uma operação atômica (uma query, um resultado). Conselho é uma **composição** — provavelmente precisa rodar uma ou mais consultas (saldo disponível, gasto já feito na categoria/balde do mês, teto do balde), aplicar regras de orçamento, e só então deixar o LLM narrar o veredito em cima de números já calculados. Isso já estava certo no diagrama (a seta de "Agente de conselho" reusando a Lambda de consulta como ferramenta, não reimplementando a query).

## O ponto que faltava

O sistema atual (Notion + Cowork que o bot substitui) organiza o orçamento em **"5 baldes"** e tem uma tabela de acompanhamento de dívida/crédito (referida como "Serasa" na estrutura consultada). Isso é **configuração de orçamento por usuário** — tetos por balde/categoria, prioridades — e hoje **não existe em lugar nenhum do schema**:

- O SQLite atual só guarda a transação em si (data, valor, categoria/descrição).
- O desenho de DynamoDB do template (PK `userId`, SK `timestamp#transactionId`, GSI por `categoria`) também só modela **transações**, não **configuração de orçamento**.
- As regras de comportamento do agente (arquivo estilo CLAUDE.md) descrevem *como o agente deve se comportar*, mas não *onde os limites numéricos de cada balde ficam persistidos* — hoje isso provavelmente só existe na cabeça do usuário ou espalhado no Notion antigo.

Sem esse dado modelado, o agente de conselho não tem como calcular "sobrou quanto no balde de lazer" de forma determinística — ele teria que ou (a) pedir esse número ao usuário toda vez, ou (b) o LLM "chutar" um teto, o que quebra o invariante de que **cálculo financeiro é determinístico, IA só narra**.

## Implicação prática

A Fase 6 do plano ("fluxo de consulta") precisa, na prática, virar duas etapas distintas:

- **6a — Consulta pura**: já estava bem desenhada (Nova Micro extrai filtros → Query no DynamoDB/GSI → Lambda agrega → resposta). Sem mudanças.
- **6b — Conselho**: depende de 6a estar pronta **e** de uma nova modelagem de dados que ainda não existe: uma entidade de configuração de orçamento por usuário (ex: item `userId` + `sortKey = "CONFIG#orcamento"` na mesma tabela, ou tabela separada) guardando os baldes, tetos por categoria e as regras que hoje vivem só no Notion/CLAUDE.md.

Sem essa modelagem, 6b não tem fundação pra ser implementada com a mesma garantia de confiabilidade que o resto do sistema já tem (dedup determinística, validação de saída do LLM, ferramentas retornando dado estruturado).

## Não decidido ainda (fica para quando chegar a hora)

- Formato exato da entidade de orçamento (uma linha por balde vs. um blob JSON com todos os baldes do usuário)
- Se a migração desse dado do Notion pra DynamoDB é manual (você digita uma vez) ou se precisa de algum importador
- Se o "agente de conselho" é uma Lambda nova reusando a Lambda de consulta como subrotina, ou uma orquestração adicional dentro do próprio Step Functions