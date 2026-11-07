# Production-Ready Document Ingestion and Real-Time RAG Agent

A modular, enterprise-grade Retrieval-Augmented Generation (RAG) system built with **FastAPI**, **LangChain**, **LangGraph**, **PostgreSQL**, and **Ollama** (with pluggable external adapters for OpenAI and Anthropic).

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
 │ • Postgresql Vector DB   │
 │ • SQLite / Postgres  │
 └──────────────────────┘
```

### Key Design Decisions

1. **Decoupled Asynchronous & Event-Driven Ingestion**: File validation and storage occur immediately, emitting an ingestion event to a durable RabbitMQ broker (`document_processing_queue`) with persistent delivery and automatic retry backoff. Independent, horizontally-scalable workers (`rag-worker`) consume jobs and execute parsing, chunking, and vector embedding (with seamless fallback to FastAPI background tasks if RabbitMQ is unavailable). Status progresses deterministically: `queued` ➔ `processing` ➔ `completed` / `failed`.
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
# Application Configuration
APP_NAME="Production RAG Agent"
APP_ENV=development
DEBUG=true
HOST=0.0.0.0
PORT=8000
SECRET_KEY=change-me-to-a-secure-random-32-byte-hex-string
ALLOWED_ORIGINS=http://localhost:8000,http://127.0.0.1:8000

# Data Directories
DATA_DIR=./data
UPLOAD_DIR=./data/uploads
# Database & Vector Store Configuration (PostgreSQL + pgvector)
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/rag_agent
POSTGRES_USER=postgres
POSTGRES_PASSWORD=postgres
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=rag_agent

# Database Connection Pooling & Concurrency Controls (Zero hardcoding)
POSTGRES_MAX_CONNECTIONS=300
POSTGRES_SHARED_BUFFERS=256MB
POSTGRES_WORK_MEM=16MB
DB_POOL_SIZE=15
DB_MAX_OVERFLOW=15
DB_POOL_TIMEOUT=20.0
DB_POOL_RECYCLE=1800

# LLM & Embedding Provider Settings
# Options: ollama, openai, anthropic, gemini, openai-compatible
DEFAULT_CHAT_PROVIDER=ollama
DEFAULT_CHAT_MODEL=llama3.2
DEFAULT_EMBEDDING_PROVIDER=gemini
DEFAULT_EMBEDDING_MODEL=models/gemini-embedding-001

# Local LLM Optimization Flags
USE_LOCAL_LLM=true
OLLAMA_BASE_URL=http://host.docker.internal:11434
OLLAMA_TIMEOUT=300.0
OLLAMA_KEEP_ALIVE=60m
EMBEDDING_BATCH_SIZE=8

# External Provider API Keys (Leave blank if using Ollama locally)
OPENAI_API_KEY=
OPENAI_BASE_URL=https://api.openai.com/v1
ANTHROPIC_API_KEY=
GEMINI_API_KEY=
GOOGLE_API_KEY=

# Ingestion & Chunking Settings
CHUNK_SIZE=800
CHUNK_OVERLAP=150
MAX_UPLOAD_SIZE_MB=25
ALLOWED_EXTENSIONS=pdf,docx,txt,md,csv,html
MAX_INGESTION_CONCURRENCY=3

# RabbitMQ High-Traffic Document Processing Queue & Broker
RABBITMQ_ENABLED=true
RABBITMQ_USER=rag_admin
RABBITMQ_PASSWORD=rag_secret_pass
RABBITMQ_PORT=5672
RABBITMQ_MGMT_PORT=15672
RABBITMQ_DEFAULT_VHOST=/
RABBITMQ_URL=amqp://rag_admin:rag_secret_pass@localhost:5672/
RABBITMQ_QUEUE_NAME=document_processing_queue
RABBITMQ_CHUNK_QUEUE_NAME=document_chunks_queue
RABBITMQ_PREFETCH_COUNT=2
RABBITMQ_MAX_RETRIES=3
RABBITMQ_RETRY_DELAY_SECONDS=5
RABBITMQ_EMBEDDED_WORKER=false
RABBITMQ_VM_MEMORY_HIGH_WATERMARK=0.7
RABBITMQ_DISK_FREE_LIMIT=2GB

# Multi-Worker Concurrent Chunk Processing & Auto-Partitioning
# Managed on a flag basis: initially keeps 1 worker, but when ENABLE_CONCURRENT_CHUNK_PROCESSING=true,
# divides large uploads into concurrent partitions (e.g., 9MB file / 3MB target = 3 concurrent chunks)
# and processes them asynchronously across worker containers so workers release early for incoming traffic.
ENABLE_CONCURRENT_CHUNK_PROCESSING=false
WORKER_CONCURRENCY=1
NUM_CHUNKING_WORKERS=1
CHUNK_PARTITION_SIZE_MB=3.0
CHUNK_PARTITION_THRESHOLD_MB=1.0

# Reverse Proxy / Load Balancer Settings (Nginx with SSE streaming and WebSocket support)
LOAD_BALANCER_ENABLED=false
PROXY_PORT=8181
ENABLE_LB_DEBUG_HEADERS=false
LB_ALGORITHM=round_robin

# ==============================================================================
# TIERED RATE LIMITING & ANTI-DDOS PROTECTION (Zero Hardcoding)
# ==============================================================================
# Nginx Reverse Proxy Tier (Identity & Device Aware with Corporate NAT / VPN Protection)
RATE_LIMIT_PUBLIC_RATE=20r/s
RATE_LIMIT_PUBLIC_BURST=30
RATE_LIMIT_API_RATE=10r/s
RATE_LIMIT_API_BURST=15
RATE_LIMIT_AUTH_RATE=5r/s
RATE_LIMIT_AUTH_BURST=10
RATE_LIMIT_STREAM_RATE=5r/s
RATE_LIMIT_STREAM_BURST=10
RATE_LIMIT_DEVICE_STREAM_MAX_CONNS=3
RATE_LIMIT_IP_STREAM_FLOOD=100

# Application Tier (FastAPI Sliding Window per Client IP / 60 seconds)
# Moderate for public routes; strictly low for protected routes
RATE_LIMIT_PUBLIC_MAX=120
RATE_LIMIT_API_MAX=60
RATE_LIMIT_LOGIN_MAX=10
RATE_LIMIT_REGISTER_MAX=5
RATE_LIMIT_REFRESH_MAX=30
RATE_LIMIT_UPLOAD_MAX=5
RATE_LIMIT_CHAT_MAX=15

# RAG & LangGraph Agent Settings
RETRIEVAL_TOP_K=4
SIMILARITY_THRESHOLD=0.3
MAX_RETRIEVAL_RETRIES=2
ENABLE_QUERY_REWRITING=true
ENABLE_ANSWER_GRADING=true

# LangSmith Observability & Tracing (Optional)
LANGCHAIN_TRACING_V2=false
LANGCHAIN_ENDPOINT=https://api.smith.langchain.com
LANGCHAIN_API_KEY=
LANGCHAIN_PROJECT=rag-agent-production
REDACT_SENSITIVE_TRACES=true

# LLM Request & Response Logging (For Docker inspection on non-prod environments)
# Automatically disabled on preprod and production to prevent secret leakage and compliance violations.
ENABLE_LLM_LOGGING=true
LLM_LOG_ENVIRONMENTS=local,development,dev,stage,staging,test
LLM_LOG_MAX_CHARS=10000
LLM_LOG_FORMAT=text

```

---

## Running with Docker Compose

The application includes a production-grade multi-container architecture orchestrated via Docker Compose:

| Service | Container Name | Port(s) | Description |
| :--- | :--- | :--- | :--- |
| **`rag-agent`** | `rag-agent-app` | `8000:8000` | FastAPI Web API, SSE streaming, Jinja2 UI, and authentication |
| **`rabbitmq`** | `rag-rabbitmq` | `5672:5672`<br>`15672:15672` | AMQP 0-9-1 message broker and Web Management Console |
| **`rag-worker`** | `rag-worker` | Internal AMQP | Dedicated asynchronous consumer for parsing, chunking, and vector indexing |

### 1. Launch the Stack

Start the entire distributed architecture in detached mode:

```bash
docker compose up --build -d
```

### 2. RabbitMQ Production Features & Guarantees

- **Persistent Static Hostname (`hostname: rabbitmq`)**: Prevents RabbitMQ from creating volatile database folders indexed by ephemeral container IDs; durable queues and user permissions persist reliably across container restarts.
- **Dual Network Aliases (`rabbitmq`, `rag-rabbitmq`)**: Ensures microservices within the Docker bridge network can resolve the broker seamlessly.
- **Resource Guardrails & Backpressure**:
  - `RABBITMQ_VM_MEMORY_HIGH_WATERMARK=0.7`: Limits broker RAM usage and applies safe backpressure to publishers before memory exhaustion.
  - `RABBITMQ_DISK_FREE_LIMIT=2GB`: Prevents node crashes when host disk space is constrained.
  - Deploy limits capped at `1024M` memory.
- **Healthcheck & Startup Ordering**: Health checks via `rabbitmq-diagnostics -q ping` guarantee that the web app and workers only connect when the broker is fully responsive.
- **Direct Stdout Logging**: `RABBITMQ_LOGS=-` streams broker event logs straight to Docker logging.

### 3. Scaling Ingestion Workers

To scale up processing throughput during high-traffic ingestion batches, spin up multiple independent worker replicas:

```bash
# Scale to 4 parallel ingestion workers
docker compose up -d --scale rag-worker=4
```

### 4. Accessing Services

- **Web Application & UI**: [http://localhost:8000](http://localhost:8000)
- **Interactive Swagger Docs**: [http://localhost:8000/docs](http://localhost:8000/docs)
- **RabbitMQ Management Dashboard**: [http://localhost:15672](http://localhost:15672)
  - **Username**: `rag_admin` (or `${RABBITMQ_USER}`)
  - **Password**: `rag_secret_pass` (or `${RABBITMQ_PASSWORD}`)
- **AMQP Broker URI**: `amqp://rag_admin:rag_secret_pass@localhost:5672/`

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
- **Vector Store**: Postgresql persistence, chunk indexing, similarity search with threshold and filters, document deletion.
- **LLM Provider Factory**: Ollama, OpenAI, Anthropic adapters, error handling for missing keys.
- **LangGraph Workflow**: Query validation, greeting bypass, query rewrite retry loop, grounding checks.
- **API Endpoints**: Multipart file uploads, pagination, document deletion, re-indexing triggers.
- **SSE Streaming**: Event-stream connection validation (`status`, `token`, `citations`, `done`).
- **Security**: Directory traversal blocking, path sanitization, and prompt boundary validation.

---

## Frontend Asset Optimization & Build Pipeline

The project uses a non-destructive build pipeline that minifies CSS, bundles JavaScript modules with sourcemaps, and precompresses assets with Gzip and Brotli into `app/static/dist` without modifying original source files:

```bash
# Build production bundle with esbuild, sourcemaps, and precompression (.gz & .br)
npm run build

# Or using the built-in Python builder (zero external dependencies required)
python3 scripts/build_assets.py

# Watch mode for automatic incremental rebuilds during development
npm run watch

# Clean distribution artifacts
npm run clean
```

### Performance & Maintainability Guarantees:
- **Clean Development Sources**: Source files in `app/static/css/`, `app/static/js/`, and `app/templates/` remain readable, modular, and easy to maintain.
- **Request Reduction**: Bundles 21 separate HTTP asset requests down to 2 requests (`bundle.min.css` and `bundle.min.js`).
- **Zero-CPU Precompression**: High-efficiency `.gz` and `.br` files are written directly to disk.
- **Cache-Busting Manifest**: `manifest.json` tracks content hashes (`bundle.min.js?v=a1b2c3d4`) for immutable HTTP caching (`max-age=31536000`).
- **Dynamic Switch**: Set `USE_OPTIMIZED_ASSETS=true` in `.env` or set `APP_ENV=production` to serve optimized bundles.

---

## Versioned REST API Specification (`/api/v1`)

All endpoints are hosted under `/api/v1/*` with full backward-compatibility aliasing for legacy `/api/*` endpoints.

### API Discovery
- `GET /api/version`: Discovery endpoint listing active API versions and route capabilities.
- `GET /api/v1/version`: Detailed v1 contract, client compatibility, and semantic specifications.

### Authentication & Multi-Tenancy
- `POST /api/v1/auth/register`: Register user and issue JWT access, ID, and refresh tokens.
- `POST /api/v1/auth/login`: Authenticate credentials with rate-limiting.
- `POST /api/v1/auth/refresh`: Refresh expired access token with replay detection.
- `GET /api/v1/auth/me`: Current authenticated user session.
- `GET /api/v1/org/current`: Active organization workspace.
- `POST /api/v1/org/invites`: Send team member invites.

### Document Management & Grounding
- `POST /api/v1/documents/upload`: Upload documents (`multipart/form-data`).
- `GET /api/v1/documents`: List indexed documents with status filter.
- `GET /api/v1/documents/{id}/evidence`: Audit trail and chunk citations.
- `DELETE /api/v1/documents/{id}`: Delete file, database records, and Postgresql embeddings.

### Chat & Streaming
- `POST /api/v1/chat/message`: Standard JSON question answering.
- `POST /api/v1/chat/stream`: Real-time Server-Sent Events (SSE) streaming.
- `GET /api/v1/chat/conversations`: List user conversations.

### Plans, Invoicing & Razorpay Billing
- `GET /api/v1/pricing/plans`: Available subscription tiers (Starter, Pro, Enterprise).
- `GET /api/v1/pricing/razorpay/config`: Public key and currency configuration.
- `POST /api/v1/pricing/razorpay/create-order`: One-time checkout order.
- `POST /api/v1/pricing/razorpay/create-mandate`: Recurring subscription mandate.
- `GET /api/v1/pricing/invoices`: Tax invoice receipt records.

---

## Mobile Client Integration (Flutter, React Native, iOS, Android)

All `/api/v1` APIs are 100% compatible with mobile applications:

1. **Stateless JWT Bearer Auth**:
   Include header `Authorization: Bearer <access_token>` in all requests. Store tokens securely in iOS Keychain, Android Keystore, or Flutter Secure Storage.
2. **Server-Sent Events (SSE) Streaming**:
   Consume real-time AI responses via standard HTTP stream listeners (Flutter `http.Client.send()`, React Native `EventSource`, Swift `URLSession.bytes`, or Kotlin `OkHttp`).
3. **Multipart File Uploads**:
   Upload files from mobile camera/photo library directly to `POST /api/v1/documents/upload`.
4. **Auto-Generated Mobile SDKs**:
   Run OpenAPI Generator against `http://localhost:8000/openapi.json` to generate strongly-typed client code:
   ```bash
   # Flutter (Dart)
   openapi-generator-cli generate -i http://localhost:8000/openapi.json -g dart -o ./rag_mobile_client

   # React Native (TypeScript / Axios)
   openapi-generator-cli generate -i http://localhost:8000/openapi.json -g typescript-axios -o ./rag_rn_client

   # iOS (Swift 5)
   openapi-generator-cli generate -i http://localhost:8000/openapi.json -g swift5 -o ./rag_ios_client

   # Android (Kotlin)
   openapi-generator-cli generate -i http://localhost:8000/openapi.json -g kotlin -o ./rag_android_client
   ```

---

## Security Safeguards

- **Path Traversal Shield**: Paths are resolved using `verify_safe_path()` against designated data roots; any attempt to escape via `../` or null bytes is rejected.
- **Content Boundaries**: Retrieved chunks are rendered inside sanitized `<retrieved_context>` blocks with strict instructions treating content as untrusted evidence.
- **Credential Masking**: Structured logging uses regex-based redacting formatters to prevent API keys and bearer tokens from leaking into logs.
- **Safe Fallbacks**: If indexed evidence is insufficient, the agent explicitly admits lack of documentation rather than confabulating unsupported statements.
