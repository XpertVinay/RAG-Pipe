"""Unit tests for document chunking."""

from app.ingestion.chunker import DocumentChunker
from app.ingestion.parsers import ParsedPage


def test_chunker_metadata_and_split():
    """Verify chunk generation, overlap, and provenance metadata."""
    chunker = DocumentChunker(chunk_size=100, chunk_overlap=20)

    long_text = "This is sentence one. " * 20
    pages = [
        ParsedPage(text=long_text, page_number=1),
        ParsedPage(text="Short second page.", page_number=2),
    ]

    chunks = chunker.chunk_document(
        document_id="doc-123",
        filename="test.txt",
        file_type="txt",
        pages=pages,
    )

    assert len(chunks) > 1
    # Check first chunk metadata
    first = chunks[0]
    assert first.metadata["document_id"] == "doc-123"
    assert first.metadata["filename"] == "test.txt"
    assert first.metadata["page"] == 1
    assert first.metadata["chunk_index"] == 0
    assert first.metadata["chunk_id"] == "doc-123_c0"
    assert first.metadata["total_chunks"] == len(chunks)

    # Check page 2 chunk
    last = chunks[-1]
    assert last.metadata["page"] == 2
    assert "Short second page." in last.page_content
