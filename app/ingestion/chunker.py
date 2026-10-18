"""Document chunking with recursive text splitting and metadata enrichment."""

import uuid
from typing import Any, Dict, List, Optional
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document as LCDocument

from app.config import get_settings
from app.core.security import sanitize_retrieved_text
from app.ingestion.parsers import ParsedPage

settings = get_settings()


class DocumentChunker:
    """Chunks parsed document pages into semantically coherent segments."""

    def __init__(self, chunk_size: int = None, chunk_overlap: int = None):
        self.chunk_size = chunk_size or settings.CHUNK_SIZE
        self.chunk_overlap = chunk_overlap or settings.CHUNK_OVERLAP
        self.splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
            separators=["\n\n", "\n", ". ", "? ", "! ", " ", ""],
            keep_separator=True,
        )

    def chunk_document(
        self,
        document_id: str,
        filename: str,
        file_type: str,
        pages: List[ParsedPage],
        user_id: Optional[str] = None,
        uploader_username: Optional[str] = None,
        is_persistent: bool = True,
        is_shared: bool = True,
    ) -> List[LCDocument]:
        """Split parsed pages into LangChain Document chunks with complete provenance metadata."""
        chunks: List[LCDocument] = []
        global_index = 0

        for page in pages:
            raw_text = sanitize_retrieved_text(page.text)
            if not raw_text:
                continue

            # Split text of this page
            page_chunks = self.splitter.split_text(raw_text)

            for split_text in page_chunks:
                clean_chunk = split_text.strip()
                if not clean_chunk:
                    continue

                chunk_id = f"{document_id}_c{global_index}"
                metadata: Dict[str, Any] = {
                    "document_id": document_id,
                    "chunk_id": chunk_id,
                    "filename": filename,
                    "file_type": file_type,
                    "page": page.page_number,
                    "chunk_index": global_index,
                    "source": filename,
                    "user_id": user_id or "anonymous",
                    "uploader_username": uploader_username or "anonymous",
                    "is_persistent": is_persistent,
                    "is_shared": is_shared,
                }
                # Include any custom page metadata
                if page.metadata:
                    metadata.update(page.metadata)

                chunks.append(
                    LCDocument(
                        page_content=clean_chunk,
                        metadata=metadata,
                    )
                )
                global_index += 1

        # Populate total chunks count across all chunks
        total = len(chunks)
        for c in chunks:
            c.metadata["total_chunks"] = total

        return chunks
