"""Chroma vector store persistence and retrieval management."""

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from langchain_chroma import Chroma
from langchain_core.documents import Document as LCDocument

from app.config import get_settings
from app.core.exceptions import VectorStoreError
from app.core.logging import logger
from app.providers.factory import ModelFactory

settings = get_settings()


class ChromaVectorStore:
    """Wrapper around Chroma vector database for persistent document index management."""

    COLLECTION_NAME = "rag_documents"

    def __init__(self, persist_dir: Optional[Path] = None):
        self.persist_dir = persist_dir or settings.CHROMA_PERSIST_DIR
        self._store: Optional[Chroma] = None

    def _get_store(self) -> Chroma:
        """Get or initialize the underlying Chroma client."""
        if self._store is None:
            try:
                embeddings = ModelFactory.get_embeddings()
                self._store = Chroma(
                    collection_name=self.COLLECTION_NAME,
                    embedding_function=embeddings,
                    persist_directory=str(self.persist_dir),
                )
            except Exception as e:
                logger.error(f"Failed to initialize Chroma vector store: {e}")
                raise VectorStoreError(f"Vector store initialization error: {str(e)}")
        return self._store

    def add_chunks(self, chunks: List[LCDocument], batch_size: int = 32) -> int:
        """Add document chunks to Chroma in batches to prevent embedding endpoint timeouts."""
        if not chunks:
            return 0
        try:
            store = self._get_store()
            total = len(chunks)
            total_batches = (total + batch_size - 1) // batch_size
            for idx in range(0, total, batch_size):
                batch = chunks[idx : idx + batch_size]
                ids = [chunk.metadata.get("chunk_id") for chunk in batch]
                store.add_documents(documents=batch, ids=ids)
                current_batch = (idx // batch_size) + 1
                logger.info(f"Indexed batch {current_batch}/{total_batches} ({len(batch)} chunks)")
            logger.info(f"Successfully indexed all {total} chunks into Chroma collection '{self.COLLECTION_NAME}'")
            return total
        except Exception as e:
            if "dimension" in str(e).lower() and store:
                logger.warning("Embedding dimension mismatch detected. Recreating Chroma collection for new model...")
                try:
                    store._client.delete_collection(self.COLLECTION_NAME)
                    self._store = None
                    new_store = self._get_store()
                    for idx in range(0, total, batch_size):
                        batch = chunks[idx : idx + batch_size]
                        ids = [chunk.metadata.get("chunk_id") for chunk in batch]
                        new_store.add_documents(documents=batch, ids=ids)
                    logger.info(f"Successfully re-indexed {total} chunks into new Chroma collection.")
                    return total
                except Exception as retry_err:
                    logger.error(f"Failed to recreate Chroma collection: {retry_err}", exc_info=True)
            logger.error(f"Failed to index chunks in Chroma: {e}", exc_info=True)
            raise VectorStoreError(f"Failed to index chunks: {str(e)}")

    def delete_document(self, document_id: str) -> bool:
        """Delete all vectors associated with a specific document ID."""
        try:
            store = self._get_store()
            # Query IDs belonging to this document_id
            collection = store._collection
            existing = collection.get(where={"document_id": document_id})
            ids_to_delete = existing.get("ids", [])

            if ids_to_delete:
                collection.delete(ids=ids_to_delete)
                logger.info(f"Deleted {len(ids_to_delete)} vectors for document {document_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete document vectors for {document_id}: {e}")
            raise VectorStoreError(f"Failed to delete document from vector store: {str(e)}")

    def similarity_search_with_score(
        self,
        query: str,
        k: int = 4,
        similarity_threshold: float = 0.3,
        document_ids: Optional[List[str]] = None,
    ) -> List[Tuple[LCDocument, float]]:
        """Retrieve most relevant document chunks filtered by threshold and optional document IDs.

        Returns:
            List of (Document, score) where score is similarity in [0, 1].
        """
        try:
            store = self._get_store()
            filter_dict = None
            if document_ids:
                if len(document_ids) == 1:
                    filter_dict = {"document_id": document_ids[0]}
                else:
                    filter_dict = {"document_id": {"$in": document_ids}}

            results = store.similarity_search_with_relevance_scores(
                query=query,
                k=k,
                filter=filter_dict,
            )

            # Filter by similarity score threshold
            filtered_results = []
            for doc, score in results:
                # Normalize or pass through score
                if score >= similarity_threshold:
                    filtered_results.append((doc, float(score)))

            logger.info(
                f"Query '{query[:30]}...' matched {len(results)} chunks, {len(filtered_results)} above threshold {similarity_threshold}"
            )
            return filtered_results
        except Exception as e:
            logger.error(f"Similarity search failed for query '{query}': {e}", exc_info=True)
            raise VectorStoreError(f"Vector search failed: {str(e)}")

    def check_health(self) -> Dict[str, Any]:
        """Verify vector store connectivity and collection status."""
        try:
            store = self._get_store()
            count = store._collection.count()
            return {
                "status": "healthy",
                "available": True,
                "collection": self.COLLECTION_NAME,
                "total_vectors": count,
                "persist_dir": str(self.persist_dir),
            }
        except Exception as e:
            return {
                "status": "unhealthy",
                "available": False,
                "message": str(e),
            }


# Global vector store instance
vector_store = ChromaVectorStore()
