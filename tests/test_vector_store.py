"""Unit tests for Chroma vector store operations."""

from pathlib import Path
from langchain_core.documents import Document as LCDocument

from app.ingestion.vector_store import ChromaVectorStore


def test_chroma_vector_store_operations(temp_dir: Path):
    """Verify adding chunks, similarity search, and deleting from Chroma."""
    store = ChromaVectorStore(persist_dir=temp_dir / "chroma")

    chunk1 = LCDocument(
        page_content="LangChain is a framework for developing LLM applications.",
        metadata={"chunk_id": "doc1_c0", "document_id": "doc1", "filename": "doc1.txt", "page": 1},
    )
    chunk2 = LCDocument(
        page_content="PostgreSQL is an advanced relational database management system.",
        metadata={"chunk_id": "doc2_c0", "document_id": "doc2", "filename": "doc2.txt", "page": 1},
    )

    # 1. Add chunks
    added_count = store.add_chunks([chunk1, chunk2])
    assert added_count == 2

    # 2. Similarity search
    results = store.similarity_search_with_score(
        query="framework for LLM",
        k=2,
        similarity_threshold=-1.0,  # Match all in mock
    )
    assert len(results) > 0

    # 3. Document filter
    filtered = store.similarity_search_with_score(
        query="database",
        k=2,
        similarity_threshold=-1.0,
        document_ids=["doc2"],
    )
    assert len(filtered) == 1
    assert filtered[0][0].metadata["document_id"] == "doc2"

    # 4. Delete document
    deleted = store.delete_document("doc1")
    assert deleted is True

# Check health
    health = store.check_health()
    assert health["status"] == "healthy"
    assert health["total_vectors"] == 1


def test_is_transient_db_error_detection():
    """Verify transient error detection for recovery mode and connection issues."""
    from app.ingestion.vector_store import is_transient_db_error

    # Direct messages
    assert is_transient_db_error(Exception("FATAL: the database system is in recovery mode"))
    assert is_transient_db_error(Exception("the database system is starting up"))
    assert is_transient_db_error(Exception("(psycopg.OperationalError) connection failed: Broken pipe"))
    assert is_transient_db_error(Exception("server closed the connection unexpectedly"))
    assert is_transient_db_error(Exception("connection refused"))

    # Nested cause
    inner = Exception("FATAL: the database system is in recovery mode")
    outer = Exception("Vector store initialization error")
    outer.__cause__ = inner
    assert is_transient_db_error(outer)

    # Non-transient error
    assert not is_transient_db_error(ValueError("Invalid embedding dimensions: expected 768, got 1536"))


def test_similarity_search_transient_retry(temp_dir: Path, monkeypatch):
    """Verify that similarity_search_with_score retries on transient errors and succeeds."""
    from langchain_chroma import Chroma

    store = ChromaVectorStore(persist_dir=temp_dir / "chroma_retry")

    chunk = LCDocument(
        page_content="Resilient vector retrieval system.",
        metadata={"chunk_id": "c1", "document_id": "d1"},
    )
    store.add_chunks([chunk])

    attempts = 0
    original_search = Chroma.similarity_search_with_relevance_scores

    def flaky_search(self, *args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise Exception("connection closed by server: FATAL: the database system is in recovery mode")
        return original_search(self, *args, **kwargs)

    monkeypatch.setattr(Chroma, "similarity_search_with_relevance_scores", flaky_search)

    # Search should catch transient error, backoff, and succeed on retry
    results = store.similarity_search_with_score("resilient", k=1, similarity_threshold=-1.0)
    assert len(results) == 1
    assert attempts == 2


def test_get_store_transient_retry(temp_dir: Path, monkeypatch):
    """Verify that _get_store retries on transient database initialization failures."""
    from langchain_chroma import Chroma

    store = ChromaVectorStore(persist_dir=temp_dir / "chroma_init_retry")
    attempts = 0

    real_init = Chroma.__init__

    def flaky_init(self, *args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise Exception("(psycopg.OperationalError) connection failed: FATAL: the database system is in recovery mode")
        real_init(self, *args, **kwargs)

    monkeypatch.setattr(Chroma, "__init__", flaky_init)

    # Should retry and succeed on attempt 2
    inst = store._get_store(max_retries=2, retry_delay=0.1)
    assert inst is not None
    assert attempts == 2

