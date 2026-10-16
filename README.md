# PropertyLedger

### Real Estate Finance Automation Assistant

PropertyLedger is a full-stack application that helps users investigate real estate finance records using natural-language questions. It combines structured financial data, document retrieval, and relationship traversal to return answers with supporting evidence.

It supports questions about properties, projects, vendors, invoices, purchase orders, payments, and budgets.

## Features

- Identify unpaid invoices, purchase-order variances, and cost-code budget overruns.
- Retrieve relevant passages from contracts, approval records, procedures, and reconciliation notes.
- Connect financial records to supporting documents using stable business identifiers.
- Trace relationships between properties, projects, invoices, vendors, and purchase orders.
- Apply consistent business definitions across query paths.
- Return supporting evidence and a workflow execution trace.
- Validate optional LLM-generated SQL before read-only execution, with deterministic fallback.

## Project Workflow

```text
User asks a question in the React interface
                    |
                    v
FastAPI receives and analyzes the question
                    |
                    v
Identify intent, business terms, and entity IDs
                    |
                    v
Select required sources and validate the execution plan
                    |
          +---------+---------+
          |         |         |
          v         v         v
     Finance SQL  Document   Neo4j
       queries    retrieval  traversal
          |         |         |
          +---------+---------+
                    |
                    v
Combine results and link supporting evidence
                    |
                    v
Return an answer, source references, and execution trace
```

Ambiguous requests can require clarification. Unsupported requests and missing evidence produce explicit outcomes.

### Document Ingestion

```text
Source documents → Parse and chunk → Generate embeddings
→ Build a versioned search corpus → Activate the completed corpus
```

The PostgreSQL ingestion workflow supports queued jobs, retries, worker leases, and recovery after interrupted processing.

## Technology Stack

| Layer | Technologies |
| --- | --- |
| Frontend | React, TypeScript, Vite |
| Backend | Python, FastAPI |
| Workflow orchestration | LangGraph |
| Structured data | PostgreSQL; CSV-loaded SQLite for local development |
| Document search | Sentence Transformers, FAISS, PostgreSQL pgvector and full-text search |
| Relationship queries | Neo4j, Cypher |
| Optional text-to-SQL | Gemini, SQLGlot validation |
| Database migrations | Alembic, SQLAlchemy |
| Verification | pytest, workflow verification and load-testing scripts |

## Repository Structure

```text
backend/
  app/
    contracts/       Schema and evaluation contracts
    database/        PostgreSQL schema and role setup
    documents/       Parsing, retrieval, indexing, ingestion jobs
    evidence/        Links between records and document evidence
    graph/           Neo4j loading and traversal
    selection/       Question analysis and source planning
    semantic_query/  Query planning, SQL generation, and validation
    semantics/       Business definitions
    workflow/        Validated LangGraph workflow
    main.py          FastAPI application
  migrations/        Versioned database migrations
  scripts/           Indexing, workers, verification, and benchmarks
  tests/             Automated backend tests
  requirements.txt

frontend/
  src/               React interface
  package.json
  package-lock.json

data/
  structured/        CSV finance records
  documents/         Supporting document corpus

docs/                Architecture, data model, and evaluation notes
.env.example         Configuration template
```

## Local Setup

Install Python, Node.js, and npm before starting.

### 1. Configure the environment

From the repository root:

```powershell
Copy-Item .env.example .env
```

The default configuration uses SQLite and FAISS for local development, with LLM text-to-SQL disabled.

Neo4j is required for graph traversal. PostgreSQL with pgvector is required for the durable document-search and ingestion configuration. Gemini credentials are required when enabling LLM text-to-SQL.

### 2. Start the backend

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r backend\requirements.txt
cd backend
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Backend: http://127.0.0.1:8000  
API documentation: http://127.0.0.1:8000/docs

Initial document-search setup may download the embedding model.

### 3. Start the frontend

In a separate terminal, from the repository root:

```powershell
cd frontend
npm ci
npm run dev
```

Frontend: http://localhost:5173

The frontend connects to `http://127.0.0.1:8000` by default. Set `VITE_API_BASE_URL` to use another backend address.

## Example Questions

- Which PR204 invoices are unpaid?
- What does the finance procedure require before invoice approval?
- Which documents are missing before INV5003 can proceed?
- What evidence supports the dispute for INV5004?

## Optional Infrastructure Setup

### PostgreSQL and Document Search

Configure the database URLs in `.env`, then run from `backend/`:

```powershell
python -m alembic upgrade head
python scripts\initialize_postgres.py
python scripts\index_postgres_documents.py
python scripts\compare_document_search.py
```

Set `DOCUMENT_SEARCH_BACKEND=postgres` after configuring and indexing the PostgreSQL document store.

For queued document ingestion:

```powershell
python scripts\enqueue_document_index.py
python scripts\run_document_worker.py
```

Use the supplied PostgreSQL role script to configure restricted query access, with separate credentials for indexing and migrations.

### Neo4j

Start a Neo4j instance and configure its connection settings in `.env`. From `backend/`, build and verify the graph:

```powershell
python -m app.graph.loader
python scripts\check_graph_projection.py
```

Graph rebuilds use versioned projections with validation before activation.

### LLM Text-to-SQL

Configure `GEMINI_API_KEY` and select a rollout mode:

- `off`: deterministic queries.
- `shadow`: evaluate generated SQL while retaining deterministic answers.
- `active`: execute accepted generated SQL with deterministic fallback.

Active mode requires PostgreSQL. Generated SQL passes backend validation for read-only behavior, approved schema usage, scope, parameters, and query cost.

## Verification

Backend tests:

```powershell
cd backend
python -m pytest -q
```

Frontend production build:

```powershell
cd frontend
npm run build
```

