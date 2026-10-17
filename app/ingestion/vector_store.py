"""Chroma vector store persistence and retrieval management with model-aware collections and auto-healing."""

import json
import re
import sqlite3
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
    """Wrapper around Chroma vector database with dynamic collection isolation and auto-sync."""

    def __init__(self, persist_dir: Optional[Path] = None):
        self.persist_dir = persist_dir or settings.CHROMA_PERSIST_DIR
        self._store: Optional[Chroma] = None
        self._current_collection_name: Optional[str] = None

    def get_collection_name(self) -> str:
        """Derive a safe collection name, preserving legacy rag_documents for ollama/768-dim embeddings."""
        prov = (settings.DEFAULT_EMBEDDING_PROVIDER or "ollama").lower()
        if "ollama" in prov:
            return "rag_documents"
        model = (settings.DEFAULT_EMBEDDING_MODEL or "default").lower()
        model_clean = re.sub(r"[^a-zA-Z0-9_]", "_", model).strip("_")
        return f"rag_{prov}_{model_clean}"

    def _get_store(self) -> Chroma:
        """Get or initialize the underlying Chroma client with the active embedding model."""
        target_name = self.get_collection_name()

        # Re-initialize if embedding configuration or collection target changed
        if self._store is None or self._current_collection_name != target_name:
            try:
                embeddings = ModelFactory.get_embeddings()
                self._store = Chroma(
                    collection_name=target_name,
                    embedding_function=embeddings,
                    persist_directory=str(self.persist_dir),
                )
                self._current_collection_name = target_name
                logger.info(f"Initialized Chroma vector store on collection '{target_name}' at '{self.persist_dir}'")
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
            logger.info(f"Successfully indexed all {total} chunks into Chroma collection '{self.get_collection_name()}'")
            return total
        except Exception as e:
            if "dimension" in str(e).lower() and self._store:
                logger.warning("Embedding dimension mismatch detected in add_chunks. Recreating Chroma collection...")
                try:
                    self._store._client.delete_collection(self.get_collection_name())
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

    def sync_from_sqlite(self, document_ids: Optional[List[str]] = None, limit: Optional[int] = None) -> int:
        """Synchronize document chunks from SQLite into the active Chroma collection."""
        db_path = settings.DATA_DIR / "sqlite.db"
        if not db_path.exists():
            return 0

        try:
            conn = sqlite3.connect(str(db_path))
            cur = conn.cursor()
            query = "SELECT id, document_id, chunk_index, content, chunk_metadata FROM document_chunks"
            params: List[Any] = []

            if document_ids:
                placeholders = ",".join("?" for _ in document_ids)
                query += f" WHERE document_id IN ({placeholders})"
                params.extend(document_ids)

            query += " ORDER BY chunk_index ASC"
            if limit:
                query += f" LIMIT {int(limit)}"

            cur.execute(query, params)
            rows = cur.fetchall()
            conn.close()

            if not rows:
                return 0

            chunks_to_add: List[LCDocument] = []
            for row in rows:
                c_id, doc_id, c_idx, content, raw_meta = row
                try:
                    meta = json.loads(raw_meta) if isinstance(raw_meta, str) else (raw_meta or {})
                except Exception:
                    meta = {}
                meta["chunk_id"] = c_id
                meta["document_id"] = doc_id
                meta["chunk_index"] = c_idx

                chunks_to_add.append(LCDocument(page_content=content, metadata=meta))

            logger.info(f"Syncing {len(chunks_to_add)} chunks from SQLite into collection '{self.get_collection_name()}'")
            return self.add_chunks(chunks_to_add)
        except Exception as e:
            logger.error(f"Error syncing chunks from SQLite: {e}", exc_info=True)
            return 0

    def similarity_search_with_score(
        self,
        query: str,
        k: int = 4,
        similarity_threshold: float = 0.25,
        document_ids: Optional[List[str]] = None,
    ) -> List[Tuple[LCDocument, float]]:
        """Retrieve most relevant document chunks with automatic healing and sync on missing vectors."""
        try:
            store = self._get_store()

            # If collection is empty, auto-sync from SQLite
            try:
                count = store._collection.count()
            except Exception:
                count = 0

            if count == 0:
                logger.info("Collection is empty. Attempting auto-sync from SQLite chunks...")
                synced = self.sync_from_sqlite(document_ids=document_ids)
                logger.info(f"Auto-synced {synced} chunks from SQLite.")
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
                if score >= similarity_threshold:
                    filtered_results.append((doc, float(score)))

            logger.info(
                f"Query '{query[:30]}...' matched {len(results)} chunks, {len(filtered_results)} above threshold {similarity_threshold}"
            )
            return filtered_results

        except Exception as e:
            error_str = str(e).lower()
            if "dimension" in error_str or "expecting embedding" in error_str:
                logger.warning(f"Dimension mismatch detected in search: {e}. Auto-healing collection...")
                try:
                    if self._store:
                        self._store._client.delete_collection(self.get_collection_name())
                        self._store = None
                    self.sync_from_sqlite(document_ids=document_ids)
                    new_store = self._get_store()
                    results = new_store.similarity_search_with_relevance_scores(
                        query=query,
                        k=k,
                        filter=filter_dict,
                    )
                    filtered = [(doc, float(s)) for doc, s in results if s >= similarity_threshold]
                    logger.info(f"Auto-healed search succeeded with {len(filtered)} results.")
                    return filtered
                except Exception as heal_err:
                    logger.error(f"Auto-heal failed: {heal_err}", exc_info=True)

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
                "collection": self.get_collection_name(),
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
