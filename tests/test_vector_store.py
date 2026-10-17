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
