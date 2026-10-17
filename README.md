# Production-Ready Document Ingestion and Real-Time RAG Agent

A modular, enterprise-grade Retrieval-Augmented Generation (RAG) system built with **FastAPI**, **LangChain**, **LangGraph**, **Chroma**, and **Ollama** (with pluggable external adapters for OpenAI and Anthropic).

Featuring asynchronous background document ingestion, multi-format parsing, anti-prompt injection grounding defenses, LangGraph stateful workflow routing, real-time Server-Sent Events (SSE) token streaming, and an interactive Jinja2 web interface.

---

## Architecture Overview

```
                          ┌──────────────────────────┐
                          │   Jinja2 Web Dashboard   │
                          │  (Vanilla JS + SSE Client)│
                          └────────────┬─────────────┘
                                       │ HTTP / SSE
                                       ▼
                          ┌──────────────────────────┐
                          │     FastAPI Gateway      │
                          │   (app/main.py & API)    │
                          └──────┬────────────┬──────┘
                                 │            │
            ┌────────────────────┘            └────────────────────┐
            ▼                                                      ▼
 ┌──────────────────────┐                               ┌──────────────────────┐
 │ Document Ingestion   │                               │ LangGraph RAG Agent  │
 │  Pipeline (Async)    │                               │   Stateful Workflow  │
 ├──────────────────────┤                               ├──────────────────────┤
 │ • Multi-Format Parse │                               │ • Query Validation   │
 │ • Provenance Chunk   │                               │ • Semantic Search    │
 │ • Vector Store Index │                               │ • Relevance Grading  │
 │ • DB Status Tracking │                               │ • Query Rewriting    │
 └──────────┬───────────┘                               │ • Grounded Synthesis │
            │                                           │ • Hallucination Audit│
            ▼                                           └──────────┬───────────┘
 ┌──────────────────────┐                                          │
 │  Persistence Layer   │◄─────────────────────────────────────────┘
 │ • Chroma Vector DB   │
 │ • SQLite / Postgres  │
 └──────────────────────┘
```

### Key Design Decisions

1. **Decoupled Asynchronous Ingestion**: File validation and storage occur immediately, while parsing, chunking, and vector embedding run via `BackgroundTasks` to keep HTTP endpoints responsive. Status progresses deterministically: `queued` ➔ `processing` ➔ `completed` / `failed`.
2. **LangGraph Stateful Agent Architecture**: Instead of a brittle single-pass chain, queries flow through a cyclic LangGraph state machine:
   - **Validation Node**: Identifies query intent (conversation vs. document Q&A).
   - **Retrieval Node**: Gathers top-k semantic vectors with metadata provenance.
   - **Relevance Grading Node**: Evaluates chunk usefulness.
   - **Query Rewriting Node**: Automatically reformulates ambiguous queries for a secondary retrieval attempt when initial relevance falls below threshold (capped by retry limit).
   - **Grounded Generation Node**: Synthesizes the answer strictly inside guarded `<retrieved_context>` XML fences.
   - **Audit Node**: Verifies claim grounding and prevents hallucinated citations.
3. **Prompt Injection & Untrusted Data Defense**: Document contents are treated as untrusted data. Explicit anti-injection system constraints instruct the model never to treat text inside `<retrieved_context>` as system commands or prompt overrides.
4. **Provider-Independent Model Factory**: Complete decoupling from LLM providers. Ollama is the default local runtime; Google Gemini (with gemini-2.5-flash), OpenAI, Anthropic, or OpenAI-compatible endpoints can be switched at runtime via UI or `.env`.
5. **Real-time SSE Streaming**: Emits incremental token streams (`event: token`), live status updates (`event: status`), and citation attribution (`event: citations`) with clean disconnect handling.

---

## Directory Structure

```
RAG-agent/
├── app/
│   ├── agent/                 # LangGraph RAG workflow, nodes, state, prompts, streaming
│   ├── api/                   # REST routes (documents, chat, settings, health)
│   ├── core/                  # Security guards, exception hierarchy, logging, tracing
│   ├── ingestion/             # Parsers (PDF, DOCX, TXT, MD, CSV, HTML), chunker, vector store
│   ├── models/                # SQLAlchemy database models (Document, Chunk, Conversation, Message)
│   ├── providers/             # LLM & Embedding provider abstraction (Ollama, OpenAI, Anthropic, Gemini)
│   ├── schemas/               # Pydantic request/response models
│   ├── static/                # Modern CSS design system and client-side JS (API, SSE)
│   ├── templates/             # Jinja2 templates (dashboard, modals, base)
│   ├── config.py              # Pydantic BaseSettings environment validation
│   ├── database.py            # Async SQLAlchemy engine and session factory
│   └── main.py                # FastAPI app initialization and lifespan
├── tests/                     # Comprehensive automated pytest suite (29 test cases)
├── data/                      # Local uploads, Chroma vectors, and SQLite DB (gitignored)
├── Dockerfile                 # Production multi-stage Docker container
├── docker-compose.yml         # Containerized app + local Ollama service
├── requirements.txt           # Pinned production requirements
└── .env.example               # Template environment configuration
```

---

## Supported Document Types

| Format | Extension | Parser Engine | Metadata Preserved |
| :--- | :--- | :--- | :--- |
| **PDF** | `.pdf` | `pypdf` | Filename, page number, chunk index |
| **Word** | `.docx` | `python-docx` | Paragraphs, tables, chunk index |
| **Plain Text** | `.txt` | Native UTF-8 Reader | Filename, chunk index |
| **Markdown** | `.md` | Native Reader | Headings, lists, code fences |
| **CSV** | `.csv` | Python `csv` | Columns, row key-values |
| **HTML** | `.html` | `beautifulsoup4` | Body text (scripts/styles stripped) |

---

## Quickstart

### 1. Prerequisites
- **Python 3.12+**
- (Optional for local inference) **Ollama** installed and running:
  ```bash
  ollama pull llama3.2
  ollama pull nomic-embed-text
  ```

### 2. Local Setup
```bash
# Clone or navigate to the repository
cd RAG-agent

# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Copy environment variables
cp .env.example .env
```

### 3. Run Application
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```
Open your browser to:
- **Web Dashboard**: [http://localhost:8000](http://localhost:8000)
- **Interactive Swagger API Docs**: [http://localhost:8000/docs](http://localhost:8000/docs)
- **Redoc Documentation**: [http://localhost:8000/redoc](http://localhost:8000/redoc)

---

## Configuration Reference (`.env`)

```ini
# Application
APP_NAME="Production RAG Agent"
APP_ENV=development
DEBUG=true
PORT=8000

# Storage
DATABASE_URL=sqlite+aiosqlite:///./data/sqlite.db
UPLOAD_DIR=./data/uploads
CHROMA_PERSIST_DIR=./data/chroma

# Default Providers (ollama | openai | anthropic | gemini | openai-compatible)
DEFAULT_CHAT_PROVIDER=ollama
DEFAULT_CHAT_MODEL=llama3.2
DEFAULT_EMBEDDING_PROVIDER=ollama
DEFAULT_EMBEDDING_MODEL=nomic-embed-text

# Ollama Endpoint
OLLAMA_BASE_URL=http://localhost:11434

# External Provider API Keys (leave blank if running Ollama locally)
OPENAI_API_KEY=
OPENAI_BASE_URL=https://api.openai.com/v1
ANTHROPIC_API_KEY=
GEMINI_API_KEY=

# Ingestion Parameters
CHUNK_SIZE=800
CHUNK_OVERLAP=150
MAX_UPLOAD_SIZE_MB=25

# Retrieval & LangGraph Retry Limit
RETRIEVAL_TOP_K=4
SIMILARITY_THRESHOLD=0.3
MAX_RETRIEVAL_RETRIES=2

# LangSmith Observability (Optional)
LANGCHAIN_TRACING_V2=false
LANGCHAIN_API_KEY=
LANGCHAIN_PROJECT=rag-agent-production
```

---

## Running with Docker Compose

Run the entire stack (FastAPI web application + Ollama) containerized:

```bash
docker compose up --build -d
```

Pull the local models inside the Ollama container:
```bash
docker exec -it rag-ollama ollama pull llama3.2
docker exec -it rag-ollama ollama pull nomic-embed-text
```

The app will be available at [http://localhost:8000](http://localhost:8000).

---

## Testing & Quality Assurance

The test suite includes **deterministic mocks** so unit and workflow tests can run offline without requiring external API keys or a running Ollama daemon.

```bash
source .venv/bin/activate
pytest -v
```

Test coverage includes:
- **Parsers**: PDF, DOCX, TXT, MD, CSV, HTML sanitization, whitespace normalization, and empty file rejection.
- **Chunker**: Recursive splitting, chunk IDs, and provenance metadata retention.
- **Vector Store**: Chroma persistence, chunk indexing, similarity search with threshold and filters, document deletion.
- **LLM Provider Factory**: Ollama, OpenAI, Anthropic adapters, error handling for missing keys.
- **LangGraph Workflow**: Query validation, greeting bypass, query rewrite retry loop, grounding checks.
- **API Endpoints**: Multipart file uploads, pagination, document deletion, re-indexing triggers.
- **SSE Streaming**: Event-stream connection validation (`status`, `token`, `citations`, `done`).
- **Security**: Directory traversal blocking, path sanitization, and prompt boundary validation.

---

## REST API Specification

### Document Management
- `POST /api/documents/upload`: Upload one or multiple documents.
- `GET /api/documents`: List indexed documents with status filter (`queued`, `processing`, `completed`, `failed`).
- `GET /api/documents/{id}`: Detailed metadata and extracted chunks.
- `POST /api/documents/{id}/reprocess`: Trigger background re-ingestion.
- `DELETE /api/documents/{id}`: Delete file, database records, and Chroma vector embeddings.

### Chat & Retrieval
- `POST /api/chat/conversations`: Create conversation session.
- `GET /api/chat/conversations`: List user conversations.
- `GET /api/chat/conversations/{id}`: View conversation history.
- `DELETE /api/chat/conversations/{id}`: Remove conversation and messages.
- `POST /api/chat/query`: Standard JSON question answering.
- `POST /api/chat/stream`: Real-time Server-Sent Events (SSE) streaming endpoint.

### System Settings & Health
- `GET /api/settings`: Current active configuration and provider capabilities.
- `POST /api/settings`: Update active model/provider runtime preferences.
- `GET /api/health`: Deep health check across SQLite DB, Chroma vector database, and LLM providers.

---

## Server-Sent Events (SSE) Protocol

When querying `/api/chat/stream`, events are framed as follows:

```
event: status
data: {"message": "Retrieving relevant context from indexed documents..."}

event: citations
data: {"citations": [{"document_id": "...", "filename": "q3_report.pdf", "page": 4, "excerpt": "...", "relevance_score": 0.88}]}

event: token
data: {"token": "The"}

event: token
data: {"token": " revenue"}

event: done
data: {"answer": "The revenue grew by 18% in Q3.", "citations": [...], "conversation_id": "..."}
```

---

## Security Safeguards

- **Path Traversal Shield**: Paths are resolved using `verify_safe_path()` against designated data roots; any attempt to escape via `../` or null bytes is rejected.
- **Content Boundaries**: Retrieved chunks are rendered inside sanitized `<retrieved_context>` blocks with strict instructions treating content as untrusted evidence.
- **Credential Masking**: Structured logging uses regex-based redacting formatters to prevent API keys and bearer tokens from leaking into logs.
- **Safe Fallbacks**: If indexed evidence is insufficient, the agent explicitly admits lack of documentation rather than confabulating unsupported statements.
