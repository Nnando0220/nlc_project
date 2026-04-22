# Auditor de Documentos com IA

Aplicacao web para processar lotes de documentos financeiros em `.txt` ou `.zip`, extrair campos com parser local + API de IA, detectar anomalias, acompanhar o progresso em tempo real e exportar os resultados em CSV para consumo no Power BI.

Este repositorio foi organizado para atender ao desafio da NLConsulting, com foco em:

- upload de lote
- processamento com IA real via API
- tratamento de arquivos problematicos
- deteccao de anomalias
- log de auditoria exportavel
- documentacao tecnica e operacional

## O que o sistema faz

- Recebe multiplos `.txt` ou um `.zip` contendo varios `.txt`
- Decodifica arquivos com fallback de encoding
- Extrai os campos principais com parser deterministico
- Usa API externa de IA para validar, normalizar e complementar os dados
- Classifica falhas da API externa sem quebrar o fluxo
- Detecta anomalias nos documentos processados
- Exibe progresso, documentos, alertas e ocorrencias da IA no dashboard
- Exporta `results.csv`, `anomalies.csv` e `audit.csv`

## Arquitetura

```text
frontend/   Next.js 16 + React 19
backend/    FastAPI + SQLAlchemy + Alembic
docs/       requisitos, arquitetura e checklists
```

Arquitetura logica:

1. O frontend envia o lote e acompanha o processamento.
2. O backend cria o lote, registra os documentos e executa o processamento em background.
3. O parser local tenta extrair o maximo de dados de forma deterministica.
4. O provedor de IA revisa os documentos elegiveis e devolve campos normalizados.
5. O motor de regras registra anomalias e o backend disponibiliza os dados para consulta e exportacao.

## Fluxo de processamento

1. Upload do lote
   - aceita `.txt` avulsos ou `.zip`
   - valida extensao, tamanho por arquivo e tamanho total do lote
2. Leitura e parse local
   - tenta `utf-8-sig`, `utf-8`, `cp1252` e `latin-1`
   - extrai pares `CHAVE: VALOR`
   - marca campos ausentes ou truncados
3. Validacao por IA
   - envia parser preliminar + texto relevante do documento
   - normaliza datas, valores e campos ambigos
   - usa fallback de modelo ou provedor quando necessario
4. Consolidacao final
   - preserva o parse local valido
   - usa a IA para complementar, nao para apagar evidencias corretas
5. Deteccao de anomalias
   - regras por documento e regras comparativas no universo do lote
6. Exibicao e exportacao
   - dashboard operacional no frontend
   - exportacao separada de resultados, anomalias e auditoria

## Escolha do prompt

O sistema usa a versao `nf-audit-v1`, gravada em `prompt_version` por documento processado.

Decisoes tecnicas da escolha do prompt:

- O parser local roda primeiro para reduzir custo, latencia e alucinacao.
- O prompt nao pede para o modelo "inventar" a nota fiscal; ele recebe:
  - campos ja extraidos localmente
  - lista de campos ausentes
  - lista de campos truncados
  - trecho compacto do texto bruto
- Quando nao existe evidencia suficiente, o contrato manda devolver `nao_extraido`.
- O fluxo `bulk` foi escolhido como padrao operacional para lotes maiores, porque reduz o numero de requisicoes mantendo rastreabilidade.
- A resposta da IA passa por validacao de formato; se vier malformada, o backend classifica a falha e segue com fallback local.

Em resumo, a estrategia do prompt busca equilibrar:

- uso real de API de IA
- rastreabilidade por documento
- throughput de lote
- protecao contra sobrescrita indevida do parser local

## Anomalias implementadas

O backend cobre as anomalias pedidas no desafio:

- `NF_DUPLICADA`
- `CNPJ_DIVERGENTE`
- `FORNECEDOR_SEM_HISTORICO`
- `EMISSAO_APOS_PAGAMENTO`
- `VALOR_FORA_FAIXA`
- `APROVADOR_NAO_RECONHECIDO`
- `STATUS_INCONSISTENTE`
- `ARQUIVO_NAO_PROCESSAVEL`

Tambem existe o caso operacional:

- `TIPO_DOCUMENTO_FORA_ESCOPO`

Esse caso evita marcar como "arquivo nao processavel" um documento que foi lido corretamente, mas nao era uma nota fiscal.

## Como rodar localmente

### Pre-requisitos

- Python 3.12+
- Node.js 20+
- npm 10+
- Docker Desktop opcional

### 1. Backend

No Windows:

```powershell
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
alembic upgrade head
uvicorn app.main:app --reload
```

API local:

- `http://localhost:8000`
- docs OpenAPI: `http://localhost:8000/docs`

### 2. Frontend

Em outro terminal:

```powershell
cd frontend
npm install
copy .env.example .env
npm run dev
```

App local:

- `http://localhost:3000`

### 3. Docker

Subida mais proxima de producao:

```bash
docker compose up --build
```

Subida de desenvolvimento com watch:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build
```

Quando quiser forcar releitura das variaveis e recriacao dos servicos:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build --force-recreate api frontend
```

## Variaveis de ambiente

### Backend

Arquivo base: `backend/.env.example`

Variaveis principais:

- `OPENROUTER_API_KEY`
- `GROQ_API_KEY`
- `HUGGINGFACE_API_KEY`
- `DATABASE_URL`
- `CORS_ALLOWED_ORIGINS`

Observacao:

- as chaves de API ficam apenas no backend
- modelos, prompt, fallback e tuning de IA usam defaults internos do codigo
- nenhuma credencial de provedor deve ser exposta ao frontend

### Frontend

Arquivo base: `frontend/.env.example`

Variaveis principais:

- `NEXT_PUBLIC_API_BASE_URL`
- `INTERNAL_API_BASE_URL`
- `NEXT_PUBLIC_UPLOAD_MAX_FILE_SIZE_BYTES`
- `NEXT_PUBLIC_UPLOAD_MAX_TOTAL_SIZE_BYTES`

## Seguranca

O projeto atende aos pontos principais do requisito 5.1:

- chaves de API ficam no backend
- upload valida tipo e tamanho antes do processamento
- o frontend tambem valida os arquivos para feedback imediato
- erros de timeout, rate limit, resposta invalida e falhas HTTP da IA sao tratados sem quebrar o app
- o usuario recebe mensagens publicas seguras, sem stack trace
- CORS e cabecalhos de seguranca sao configurados no backend

## Rastreabilidade e auditabilidade

O projeto atende aos pontos principais do requisito 5.2:

- cada documento registra:
  - nome do arquivo
  - timestamp de processamento
  - versao do prompt
- cada anomalia registra:
  - regra disparada
  - campos de evidencia
  - valores de evidencia
  - confianca
- o log de auditoria e exportado separadamente em `audit.csv`
- campos sem evidencia ficam explicitamente como `nao_extraido`

## Capricho e UX

O frontend foi organizado em uma jornada simples:

1. `Enviar arquivos`
2. `Acompanhar`
3. `Detalhe do documento`
4. `Exportar`

O dashboard mostra:

- progresso do lote
- ETA
- documentos processados
- anomalias
- ocorrencias da IA externa
- filtros operacionais
- exportacoes prontas

## Exportacoes e Power BI

CSV gerados pelo backend:

- `results.csv`
  - uma linha por documento processado
  - inclui status, campos extraidos e metadados operacionais
- `anomalies.csv`
  - uma linha por anomalia detectada
  - inclui regra, severidade, confianca e evidencias
- `audit.csv`
  - uma linha por evento de auditoria
  - inclui estagio, resultado, provider, modelo efetivo e codigos de falha

Esses arquivos foram pensados para alimentar o dashboard Power BI pedido no desafio, com pelo menos:

- cards de resumo
- grafico por tipo de anomalia
- tabela detalhada de anomalias
- visual por fornecedor
- tabela de log de auditoria

## Endpoints principais

- `POST /api/v1/nf-audits/uploads`
- `GET /api/v1/nf-audits/batches/{batch_id}`
- `GET /api/v1/nf-audits/batches/{batch_id}/progress`
- `GET /api/v1/nf-audits/batches/{batch_id}/documents`
- `GET /api/v1/nf-audits/batches/{batch_id}/anomalies`
- `POST /api/v1/nf-audits/batches/{batch_id}/cancel`
- `POST /api/v1/nf-audits/batches/{batch_id}/exports/results.csv`
- `POST /api/v1/nf-audits/batches/{batch_id}/exports/anomalies.csv`
- `POST /api/v1/nf-audits/batches/{batch_id}/exports/audit.csv`

## Estrutura do projeto

```text
system/
|-- frontend/
|   |-- src/app/
|   |-- src/components/
|   |-- src/lib/
|   `-- src/services/
|-- backend/
|   |-- alembic/
|   |-- app/api/
|   |-- app/core/
|   |-- app/db/
|   |-- app/schemas/
|   `-- app/services/
|-- docs/
|-- docker-compose.yml
`-- docker-compose.dev.yml
```

Arquivos importantes:

- `backend/alembic/schema.sql`
- `backend/app/services/file_processor.py`
- `backend/app/services/openrouter_service.py`
- `backend/app/services/anomaly_service.py`
- `backend/app/api/routes/nf_audits.py`
- `frontend/src/app/upload/page.tsx`
- `frontend/src/app/dashboard/page.tsx`
- `frontend/src/app/reports/page.tsx`

## Testes e validacao

Backend:

```powershell
cd backend
python -m pytest
```

Frontend:

```powershell
cd frontend
npm run build
```

## Documentacao complementar

Materiais adicionais no repositorio:

- `docs/architecture.md`
- `docs/matriz-requisitos-entrega.md`
- `docs/pre-deploy-checklist.md`
- `docs/postman-api-test-guide.md`
- `docs/codebase-audit.md`

## Entrega

Os entregaveis externos do desafio devem ser publicados fora do codigo-fonte:

- URL publica funcional da aplicacao
- repositorio GitHub com historico de commits
- dashboard Power BI publicado ou arquivo `.pbix`
- relatorio final das anomalias encontradas

Este README cobre a parte tecnica do projeto: arquitetura, execucao local, estrategia do prompt, seguranca, rastreabilidade, exportacoes e organizacao do codigo.
