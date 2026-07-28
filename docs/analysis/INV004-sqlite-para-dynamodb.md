---
type: INV
version: 1.0.0
author: Victor Veloso
date: 2026-07-27
status: Draft
fase: "Fase 3 — docs/analysis/plano-contexto.md"
---

# INV004 — Dados: SQLite → DynamoDB (+ lacuna de modelagem de orçamento)

## Contexto

Gatilho: usuário pediu para iniciar a Fase 3 do plano de migração serverless (`docs/analysis/plano-contexto.md`, seção "Fase 3 — Dados: SQLite → DynamoDB"), anexando um achado complementar (`docs/analysis/fase3-lacuna-dynamo-arquitetura.md`) que identifica uma lacuna: não existe, em lugar nenhum do sistema, modelagem de configuração de orçamento por usuário (os "5 baldes" e teto de dívida/crédito do sistema Notion que o bot substitui) — sem isso, o futuro "agente de conselho" (Fase 6b) não tem como calcular nada de forma determinística.

Branch atual: `main` (task ainda não tem branch própria — deve virar `feat/sqlite-para-dynamodb` antes de qualquer código, por convenção do `CLAUDE.md`).

Antes de investigar o código a fundo, uma rodada de `AskUserQuestion` resolveu três ambiguidades que o `plano-contexto.md` e o achado da lacuna deixavam em aberto (ver "Decisões de Produto Confirmadas" abaixo).

**Achado colateral relevante (não é uma pergunta, é um fato verificado em código):** existe um worktree paralelo não mesclado, `.worktrees/feature/nlp-query-totals` (branch `feature/nlp-query-totals`), que já implementa um fluxo de consulta (Fase 6a) **direto sobre o SQLite atual**, adiantado em relação à ordem do plano (que previa consulta só na Fase 6, depois do DynamoDB, "para não escrever a query duas vezes"). Esse branch adiciona `get_totals_by_period()` a `repository/transaction.py` e `get_totals()` a `services/transaction_service.py`, além de dois arquivos novos (`services/intent_service.py`, `services/query_service.py`) que chamam `google-genai` **diretamente**, sem passar pela abstração `LLMProvider` (violação do "Nunca Fazer" do `CLAUDE.md`: "Chamar Gemini fora de `ocr_service.py` ou `nlp_service.py`"). Essa violação já existia no branch antes desta investigação, é de outra task, e **não deve ser corrigida aqui** — só é citada porque a decisão de produto 1 (abaixo) manda o repository DynamoDB desta Fase 3 cobrir `get_totals_by_period()` também.

## Problema 1 — `repository/` não tem abstração de backend (só SQLAlchemy/SQLite)

### Descrição observada

`repository/transaction.py` recebe uma `AsyncSession` do SQLAlchemy no construtor e opera direto sobre `TransactionEntity`. Não existe nenhuma interface (`ABC`), nem `factory.py`, nem flag de ambiente equivalente a `DB_BACKEND` — ao contrário de `LLMProvider`/`LLM_PROVIDER` (Fase 1) e `StorageProvider`/`STORAGE_BACKEND` (Fase 2), que já seguem esse padrão.

### Análise de causa raiz

O projeto nunca teve um segundo backend de persistência, então a regra do `CLAUDE.md` ("Nunca: Adicionar `Protocol`/`ABC` ao repository sem uma segunda implementação real ou necessidade concreta") bloqueou a abstração até agora — corretamente, por `PATTERNS.md` ("Repository concreto sem interface"). A Fase 3 **é** essa segunda implementação real: a partir daqui a regra deixa de bloquear e passa a exigir a interface, mesmo padrão já usado para LLM e storage (`PATTERNS.md`, "Troca de provedor externo: interface + factory por flag de ambiente" já cita explicitamente `DB_BACKEND=sqlite|dynamo` como próxima aplicação). **Isto não é uma decisão em aberto — é Design Conhecido**, herdado do padrão já estabelecido.

### Arquivos relevantes (estado atual, literal)

**`repository/transaction.py`** (main, arquivo inteiro):
```python
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.entities.transaction import TransactionEntity
from models import Transacao


class TransactionRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def save_transactions(self, transactions: list[Transacao], telegram_user_id: int) -> None:
        for transaction in transactions:
            self.session.add(TransactionEntity(
                telegram_user_id=telegram_user_id,
                data=transaction.data,
                descricao=transaction.descricao,
                valor=transaction.valor,
                tipo=transaction.tipo,
                categoria=transaction.categoria,
            ))
        await self.session.commit()

    async def find_by_user(self, telegram_user_id: int) -> list[Transacao]:
        result = await self.session.execute(
            select(TransactionEntity).where(
                TransactionEntity.telegram_user_id == telegram_user_id
            )
        )
        entities = result.scalars().all()
        return [
            Transacao(
                data=e.data,
                descricao=e.descricao,
                valor=e.valor,
                tipo=e.tipo,
                categoria=e.categoria,
            )
            for e in entities
        ]
```

**`services/transaction_service.py`** (main, arquivo inteiro):
```python
from database.connection import async_session
from models import Transacao
from repository.transaction import TransactionRepository


async def save_transactions(transactions: list[Transacao], telegram_user_id: int) -> None:
    async with async_session() as session:
        repository = TransactionRepository(session)
        await repository.save_transactions(transactions, telegram_user_id)


async def get_transactions(telegram_user_id: int) -> list[Transacao]:
    async with async_session() as session:
        repository = TransactionRepository(session)
        return await repository.find_by_user(telegram_user_id)
```

**`repository/transaction.py`** na branch não mesclada `feature/nlp-query-totals` acrescenta (relevante por causa da Decisão de Produto 1, abaixo):
```python
from datetime import date
from sqlalchemy import func, select
# ...

    async def get_totals_by_period(
        self, telegram_user_id: int, start: date, end: date
    ) -> dict[str, float]:
        result = await self.session.execute(
            select(TransactionEntity.tipo, func.sum(TransactionEntity.valor))
            .where(
                TransactionEntity.telegram_user_id == telegram_user_id,
                TransactionEntity.data >= start,
                TransactionEntity.data <= end,
            )
            .group_by(TransactionEntity.tipo)
        )
        key_map = {"entrada": "entradas", "saida": "saidas"}
        totals: dict[str, float] = {"entradas": 0.0, "saidas": 0.0}
        for tipo, total in result.all():
            key = key_map.get(tipo)
            if key:
                totals[key] = total or 0.0
        return totals
```

**`database/entities/transaction.py`** (main, arquivo inteiro — modelo Entity a espelhar no design do Item DynamoDB):
```python
from datetime import date, datetime
from sqlalchemy import Date, DateTime, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from database.base import Base


class TransactionEntity(Base):
    __tablename__ = "transacoes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_user_id: Mapped[int] = mapped_column(Integer, index=True)

    data: Mapped[date] = mapped_column(Date)
    descricao: Mapped[str] = mapped_column(String)
    valor: Mapped[float] = mapped_column(Float)
    tipo: Mapped[str] = mapped_column(String)
    categoria: Mapped[str] = mapped_column(String, default="")

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
```

**`models.py`** (main, arquivo inteiro — DTO `Transacao`, contrato que atravessa as camadas, não muda nesta fase):
```python
from datetime import date
from typing import Literal
from pydantic import BaseModel


class Transacao(BaseModel):
    data: date
    descricao: str
    valor: float
    tipo: Literal["entrada", "saida"]
    categoria: str = ""
```

**`database/connection.py`** (main, arquivo inteiro — ponto de integração que precisa de tratamento especial sob `DB_BACKEND=dynamo`, ver "Perguntas em Aberto"):
```python
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from database.base import Base

DATABASE_URL="sqlite+aiosqlite:///guardiao.db"
engine = create_async_engine(DATABASE_URL, echo=False)
async_session = async_sessionmaker(engine, expire_on_commit=False)

async def init_db() -> None:
    """Cria as tabelas se ainda não existirem."""
    async with engine.begin() as conn:
      await conn.run_sync(Base.metadata.create_all)
```
`main.py` linha 13 chama `asyncio.run(init_db())` incondicionalmente na inicialização — hoje faz sentido (`create_all` do SQLAlchemy), mas não faz sentido para DynamoDB (a tabela é provisionada manualmente via AWS CLI, por `PATTERNS.md` "Criação de recursos AWS é sempre ação manual do usuário").

**Padrão de referência a replicar** (`services/llm/provider.py` + `factory.py`, já usado por LLM e storage):
```python
# services/llm/provider.py
from abc import ABC, abstractmethod
from models import Transacao

class LLMProviderError(Exception):
    """Erro genérico de provider de LLM, tratado pelos services (nunca vaza ao handler)."""

class LLMProvider(ABC):
    @abstractmethod
    async def extract_text_transactions(self, text: str) -> list[Transacao]: ...
    @abstractmethod
    async def extract_document_transactions(self, file_bytes: bytes, mime_type: str) -> list[Transacao]: ...
```
```python
# services/llm/factory.py
from run_polling.config import LLM_PROVIDER
from services.llm.bedrock_provider import BedrockProvider
from services.llm.gemini_provider import GeminiProvider
from services.llm.provider import LLMProvider

def get_llm_provider() -> LLMProvider:
    if LLM_PROVIDER == "gemini":
        return GeminiProvider()
    if LLM_PROVIDER == "bedrock":
        return BedrockProvider()
    raise ValueError(f"LLM_PROVIDER inválido: {LLM_PROVIDER!r} (esperado 'gemini' ou 'bedrock')")
```
Implementações concretas recebem o client via injeção no construtor (`__init__(self, client=None)`), testável sem monkeypatch — mesmo padrão a seguir para `SqliteTransactionRepository`/`DynamoTransactionRepository`.

## Problema 2 — Dedup determinística de 3 estados nunca foi implementada

### Descrição observada

`plano-contexto.md` (seção 1, "Pontos fortes a preservar") descreve "Deduplicação determinística de 3 estados (NOVA / SUSPEITA / DUPLICATA EXATA), sem IA" como algo que **já existe e funciona** no monólito atual. Não existe. Busquei por `duplicat`, `DUPLICATA`, `SUSPEITA`, `dedup` em todo o código-fonte (`.py`, main e worktree) e não há nenhuma ocorrência.

### Análise de causa raiz

`docs/PATTERNS.md`, seção "Service como camada de orquestração intencional", confirma isto explicitamente: `services/transaction_service.py` "existe entre handler e repository por consistência arquitetural, não porque há lógica hoje. É o lugar reservado para dedup **quando for implementado**." Ou seja, o próprio projeto já documentava a ausência antes desta investigação — `plano-contexto.md` descreveu uma aspiração (o que o Notion/Cowork antigo fazia manualmente, ou o que se pretende construir) como se fosse comportamento atual do bot Python.

Isso muda a natureza da tarefa "Fase 3" em relação ao que o plano assumia: o critério de saída original ("dedup funcionando igual, mesmos 3 estados, mesmos resultados nos mesmos casos de teste [do SQLite]") pressupõe uma implementação de referência para comparar — que não existe. **Não há o que portar; há o que projetar.** Confirmado com o usuário (Decisão de Produto 3, abaixo): a regra ainda não está definida, vira Pergunta em Aberto para o SPEC resolver.

### Arquivos relevantes

Nenhum arquivo de produção contém lógica de dedup hoje. `services/transaction_service.py` (ver Problema 1) é o único ponto que `PATTERNS.md` já reserva para essa lógica.

## Problema 3 — Modelagem de orçamento (baldes) ausente do schema DynamoDB do template

### Descrição observada

Confirma, lendo o template `docs/guardiao-financeiro-stack.yml` (que existe no repo — no HEAD atual, `docs/guardiao-financeiro-stack.yml`, 14956 bytes), exatamente o que `fase3-lacuna-dynamo-arquitetura.md` já apontava: a única tabela definida modela transações.

```yaml
# docs/guardiao-financeiro-stack.yml, linhas 51-83
  # ---------------------------------------------------------------------
  # 2. Banco de dados de transacoes
  #    Schema pensado para consultas reais de um bot financeiro:
  #    PK = userId (particiona por usuario)
  #    SK = timestamp#transactionId (ordena por data, permite range query)
  #    GSI por categoria, para perguntas tipo "quanto gastei em mercado".
  # ---------------------------------------------------------------------
  MyDynamoDBTable:
    Type: AWS::DynamoDB::Table
    Properties:
      TableName: !Sub 'GuardiaoFinanceiro-Transacoes-${Environment}'
      BillingMode: PAY_PER_REQUEST
      AttributeDefinitions:
        - AttributeName: userId
          AttributeType: S
        - AttributeName: sortKey
          AttributeType: S
        - AttributeName: categoria
          AttributeType: S
      KeySchema:
        - AttributeName: userId
          KeyType: HASH
        - AttributeName: sortKey
          KeyType: RANGE
      GlobalSecondaryIndexes:
        - IndexName: GSI-Categoria
          KeySchema:
            - AttributeName: userId
              KeyType: HASH
            - AttributeName: categoria
              KeyType: RANGE
          Projection:
            ProjectionType: ALL
```

### Análise de causa raiz

É uma tabela single-table (PK `userId` compartilhada entre tipos de item, diferenciados pelo prefixo do `sortKey`) — o desenho já suporta, sem qualquer mudança de `AttributeDefinitions`/`KeySchema`/GSI, guardar um item de configuração por usuário (ex.: `sortKey = "CONFIG#orcamento"`) ao lado dos itens de transação (`sortKey = "{timestamp}#{transactionId}"`): DynamoDB não exige que todo item tenha os atributos do GSI (`categoria`) — um item de config simplesmente não aparece no `GSI-Categoria`, sem erro (índice esparso). Ou seja, tecnicamente a lacuna se resolve **sem mudança estrutural na tabela**, só com uma nova convenção de `sortKey` e um novo shape de Item — mas o **formato exato** dessa entidade (uma linha por balde vs. um blob JSON com todos os baldes) é uma decisão de produto que `fase3-lacuna-dynamo-arquitetura.md` explicitamente deixou como "Não decidido ainda". Confirmado com o usuário (Decisão de Produto 2, abaixo): modelar agora, na Fase 3.

### Arquivos relevantes

`docs/guardiao-financeiro-stack.yml` (linhas 51-83, acima). Nenhum arquivo Python tem qualquer referência a orçamento/baldes/tetos — busquei por `orcamento`, `orçamento`, `balde`, `budget` em `.py` e não há ocorrência.

## Relação entre os problemas

Os três problemas são sequenciais, não independentes: Problema 1 (abstração de backend) é a fundação técnica — sem ela não há onde a Fase 3 escrever nada. Problema 2 (dedup) e Problema 3 (orçamento) são dois tipos de dado que vão morar na mesma tabela nova, mas com naturezas opostas: dedup é uma regra de **integridade de escrita** (decide se uma transação entra ou não), enquanto orçamento é uma **entidade de configuração nova** (não deriva de nada que já existe, é dado novo que o usuário vai fornecer). Ambos, no entanto, compartilham o mesmo bloqueio: nenhum dos dois tem uma decisão de formato fechada — por isso os dois viram Pergunta em Aberto para o SPEC, não Decisão de Design direto no TASKS.

## Decisões de Produto Confirmadas (usuário, nesta sessão — rodada de `AskUserQuestion`)

1. **Escopo do repository inclui `get_totals_by_period`.** Mesmo a branch `feature/nlp-query-totals` estando não mesclada, o repository DynamoDB desta Fase 3 deve cobrir `save_transactions`, `find_by_user` **e** `get_totals_by_period` (ver Problema 1) — evita reescrever o repository DynamoDB duas vezes quando a branch de consulta for mesclada.
2. **Orçamento (baldes) é modelado agora, na Fase 3**, não adiado para a Fase 6b. A entidade entra no desenho do schema desta fase (ver Problema 3), incluindo suporte básico de leitura/escrita no repository — a lógica de cálculo/conselho em si (Fase 6b) continua fora de escopo.
3. **Dedup ainda não tem regra definida.** Vira Pergunta em Aberto formal (ver abaixo), a ser resolvida no SPEC — isso por si só já indica rota **Ambígua** (INV→SPEC→PLN→TASKS), não a rota curta.

## Observações de Runtime / Notas técnicas

- Conta AWS `413948096391`, profile CLI `guardiao-dev`, região `us-east-2` — já configurados (Fase 0), reaproveitados sem mudança (`PATTERNS.md`, "Região AWS fixada").
- IAM: a policy atual (`scripts/aws/iam-policy-guardiao-dev.json`) só tem Bedrock + S3. Fase 3 precisa de um novo `Sid` com `dynamodb:GetItem`/`PutItem`/`Query` no ARN da tabela e `${Arn}/index/*` — por `PATTERNS.md` ("IAM mínimo incremental por fase"), nunca substituir a policy existente, só ampliar. O `MyStateMachineRole` do template (linhas 108-115) já mostra a ação/recurso certos como referência.
- `database/connection.py::init_db()` (chamado incondicionalmente em `main.py:13`) roda `Base.metadata.create_all`, que não faz sentido sob `DB_BACKEND=dynamo` (a tabela é criada manualmente via AWS CLI, nunca por código, por `PATTERNS.md`). Precisa de tratamento — provavelmente condicionar a chamada ao backend ativo, ou tornar `init_db` um no-op para `dynamo`. Fica para o PLN decidir o "como" (não é uma pergunta de produto, é detalhe de implementação).
- `main` não tem nenhum teste de `repository/` hoje (`tests/repository/` não existe na main; existe só na branch `feature/nlp-query-totals`, cobrindo `get_totals_by_period`). A Fase 3 introduz o primeiro `tests/repository/` da main — sem regressão a proteger, mas também sem exemplo formal a seguir além do que a branch não mesclada já fez.
- Script de migração de dados (SQLite → DynamoDB, já previsto na lista de tarefas do `plano-contexto.md`) migra as **transações existentes** em `guardiao.db`. A configuração de orçamento (baldes/tetos) não tem fonte estruturada nenhuma para migrar automaticamente — hoje só existe no Notion antigo, na cabeça do usuário. Ver Pergunta em Aberto 3.
- Achado colateral já registrado no Contexto: `feature/nlp-query-totals` chama `google-genai` direto, fora de `LLMProvider` — violação real do `CLAUDE.md`, mas de outra task, fora de escopo aqui.

## Ajustes do usuário (pós-apresentação do INV, antes do SPEC)

1. **Migração de transações do Notion — fora de escopo, não é para ser projetada.** As transações hoje cadastradas no Notion são dado transacional (a mesma coisa que texto/foto/PDF já cobrem), não configuração. O caminho é o usuário exportar/enviar esse conteúdo (ex.: arquivo `.md`) pelo fluxo normal de extração via LLM — não existe (nem deve existir) um importador dedicado "transação vinda do Notion". Isso **remove** a antiga Pergunta em Aberto 3 (abaixo, agora resolvida como N/A) e reduz o escopo desta fase: não há necessidade de nenhum design de importação de transações.
2. **Modelagem crítica exige embasamento em como aplicações financeiras reais fazem isso** — tanto para dedup quanto para orçamento — antes de fechar qualquer formato. O usuário apontou `docs/analysis/contexto-conversas-claude.md` como a base já existente para aprofundar (ver item 2, "Fundação de dados e dedup", 28/06/2026), não como a decisão final.
3. **Novo invariante de produto: toda configuração (orçamento e qualquer outra do mesmo tipo) precisa ser explicitamente mostrada ao usuário, com aprovação, antes de qualquer escrita.** Confirmado com o usuário (rodada de `AskUserQuestion`) que isso **não é escopo de execução da Fase 3** — a Fase 3 continua sendo só schema + repository, sem fluxo de chat para ler/editar baldes. O invariante é registrado agora para não se perder, e vale para quando a **Fase 6b** (agente de conselho) construir o fluxo real de leitura/escrita de configuração via conversa: nenhuma mudança de configuração pode ser persistida sem antes mostrar ao usuário o que vai mudar e obter confirmação explícita. Propagado também para `docs/analysis/contexto-conversas-claude.md` (novo item na lista "Invariantes do projeto"), já que é uma regra que atravessa fases, não só esta.

## Pesquisa de Mercado — Base para o SPEC

Pesquisa feita para embasar (não substituir) a Decisão de Produto que falta. Duas fontes buscadas: deduplicação de transações financeiras em escala (fintech infra) e modelagem de orçamento por envelope (o padrão exato dos "5 baldes").

### Dedup — o que já estava pensado (`contexto-conversas-claude.md`, item 2)

- Taxonomia de 4 tipos de duplicidade: (1) reenvio de arquivo idêntico, (2) sobreposição de período entre extratos, (3) transação real repetida no mesmo dia (ex.: dois cafés de R$8 — não é duplicata), (4) ruído de OCR (mesma transação, texto ligeiramente diferente).
- Camadas de defesa já esboçadas: hash dos bytes crus do arquivo (camada 0, pré-LLM) → assinatura da transação (`data + valor + tipo + descrição normalizada`, comparada contra janela de 60–90 dias do mesmo usuário) → 3 estados (NOVA/SUSPEITA/DUPLICATA EXATA) em vez de decisão binária.
- Motivo já decidido: 100% determinística, sem IA na comparação (dado financeiro não admite não-determinismo).

### Dedup — o que a prática de mercado confirma/ajusta

Fonte: [Deduplication at Scale, Modern Treasury](https://www.moderntreasury.com/journal/deduplication-at-scale) — empresa de infraestrutura de pagamentos, artigo técnico sobre dedup de transações bancárias em produção.

- **Fingerprint em campos canônicos estáveis primeiro.** O padrão da indústria é gerar um hash a partir de campos que não mudam entre reenvios (ex.: conta, data, valor) — valor (`amount`) é citado como o atributo mais estável para o primeiro sinal de duplicidade. Isso **confirma** a escolha já esboçada internamente (`data + valor` como núcleo da assinatura), e sugere que `descrição normalizada`/`categoria` funcionam melhor como critério de desempate secundário do que como parte do hash primário.
- **Colisão de hash não é veredito final — escalona para uma checagem secundária.** Em vez de um único hash binário, o sistema gera um hash secundário com atributos adicionais quando a primeira comparação colide, só então decide bloquear ou inserir. Isso mapeia diretamente para os 3 estados já pensados: hash primário bate → candidato a DUPLICATA EXATA/SUSPEITA → comparação secundária decide qual dos dois.
- **Tolerância é sensível à magnitude do valor, não só à janela de tempo.** Citação direta: *"Two duplicate-looking $5 ACH bank fee records are likely real unique payments, whereas two duplicate high value wires are much more likely to be real duplicate records."* — ou seja, valores pequenos e repetidos no mesmo dia são mais provavelmente legítimos (bate com o exemplo dos "dois cafés de R$8" que a conversa original já tinha citado independentemente). Isso é um dado a mais para o SPEC considerar: a regra de SUSPEITA pode precisar de um limiar de valor, não só de uma janela de dias.
- Não há indicação de janela de tempo fixa nem de fuzzy-match de texto no artigo — a escolha de 60–90 dias e a normalização de descrição continuam sendo decisão do projeto, não algo "resolvido" pela pesquisa.

### Orçamento (baldes) — o que a prática de mercado (envelope budgeting) confirma

Fonte: [Envelope budgeting, Actual Budget](https://actualbudget.org/docs/getting-started/envelope-budgeting/) (open-source, mesma família conceitual do YNAB) e [The Cash Envelope System, YNAB](https://www.ynab.com/blog/what-is-a-cash-envelope-system).

- **"Balde" = "categoria/envelope"** é literalmente o nome técnico do padrão que o Notion antigo já implementava artesanalmente — não é uma abstração nova, é o padrão estabelecido chamado *envelope budgeting* / *zero-based budgeting*.
- **Cada envelope é uma entidade com identidade própria**, não um campo solto: tem nome, um valor alocado por período ("teto"), e um saldo disponível que é *derivado* (alocado − gasto no período), não necessariamente armazenado. Isso pesa a favor de **um Item por balde** (`sortKey = "CONFIG#balde#{nome}"`) em vez de um blob único — cada envelope tem ciclo de vida próprio (pode ser criado/editado/removido individualmente), o que casa melhor com granularidade de Item do DynamoDB do que com um blob monolítico.
- **Rollover é um comportamento configurável por envelope**, não um valor fixo: o sistema permite tanto "sobra acumula pro próximo período" quanto "estouro desconta do próximo período". Se o Guardião for reproduzir o comportamento dos "5 baldes" do Notion, essa é uma decisão de produto que o SPEC precisa registrar explicitamente por balde (ou globalmente) — a pesquisa não decide, só mostra que é uma variável real do domínio, não um detalhe negligenciável.
- O saldo disponível sendo *derivado* (não armazenado) é relevante para a Fase 3: se seguido, a tabela não precisa persistir "quanto sobrou", só o teto — o "quanto foi gasto" já vem do agregado de transações por categoria (o mesmo `GSI-Categoria`/`get_totals_by_period` que já está no escopo). Isso reduz o que precisa ser escrito no Item de config ao essencial: nome, teto, período de referência, e (talvez) política de rollover.

## Perguntas em Aberto

1. ~~Regra de dedup determinística~~ — **Resolvida em `SPEC006-sqlite-para-dynamodb.md`**: fingerprint `data+valor+tipo+descrição normalizada` como `sortKey`; DUPLICATA EXATA sempre bloqueia e pede confirmação do usuário (mesmo em casos legítimos como "dois cafés de R$8" — aceito como caso raro, decisão explícita do usuário); SUSPEITA via janela de 60–90 dias + similaridade de descrição ≥ 0.8 (`difflib`).
2. ~~Formato exato da entidade de orçamento~~ — **Resolvida em `SPEC006-sqlite-para-dynamodb.md`**: um único Item de configuração (`sortKey = "CONFIG#{nome}"`), campo `periodo` (`"mensal"` para balde, `"unico"` para dívida) distingue o comportamento sem precisar de schemas separados — dívida reaproveita o mesmo desenho de balde, confirmado por pesquisa (YNAB modela debt payoff na mesma estrutura de categoria/envelope, mudando só o *target type*). Saldo sempre derivado, nunca armazenado.
3. ~~Migração dos dados de orçamento do Notion~~ — **N/A, removida.** Ver "Ajustes do usuário" acima: transações do Notion entram pelo fluxo normal de extração via LLM (upload de arquivo), sem importador dedicado. Não sobra nenhum critério de aceitação de "migração" para o SPEC cobrir aqui.
4. **Comportamento de `init_db()` sob `DB_BACKEND=dynamo`** — no-op vs. condicional vs. outra estratégia. → **Resolver no PLN** (decisão técnica, não de produto).

## Próximos Passos

Causa raiz de cada problema está fechada (sei exatamente o que existe, o que não existe, e por quê), mas duas das três frentes (dedup, orçamento) dependem de decisões de produto que o usuário confirmou não estarem prontas ainda — isso é definição de rota **Ambígua**, não Design Conhecido, mesmo com a abstração de backend (Problema 1) sendo Design Conhecido isolada.

**Classificação: Ambíguo.**

Rota proposta: **rota completa** — INV004 (este documento) → `SPEC006-sqlite-para-dynamodb.md` (requisitos: regra de dedup, formato da entidade de orçamento, critério de aceitação da migração) → gate → `PLN006-sqlite-para-dynamodb.md` (estratégia: estrutura do `repository/` novo, decisão sobre `init_db`, script de migração, ordem de execução) → gate → `TASKS006-sqlite-para-dynamodb.md`.

⏸ Aguardando confirmação do usuário sobre a classificação antes de escrever o SPEC.
