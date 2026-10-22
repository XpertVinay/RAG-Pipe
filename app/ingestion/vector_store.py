"""PostgreSQL pgvector persistence and retrieval management with model-aware collections and auto-sync."""

import json
import re
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from sqlalchemy import create_engine, text
from langchain_core.documents import Document as LCDocument

from app.config import get_settings
from app.core.exceptions import VectorStoreError
from app.core.logging import logger
from app.providers.factory import ModelFactory

settings = get_settings()


class PostgresVectorStore:
    """High-performance vector store backed by PostgreSQL pgvector with dynamic collection isolation."""

    def __init__(self, persist_dir: Optional[Path] = None):
        self.persist_dir = persist_dir or settings.CHROMA_PERSIST_DIR
        self._store: Optional[Any] = None
        self._current_collection_name: Optional[str] = None

    @property
    def is_postgres(self) -> bool:
        """Return True if database URL indicates PostgreSQL."""
        url = settings.DATABASE_URL.lower()
        return "postgres" in url or "postgresql" in url

    def get_collection_name(self) -> str:
        """Derive a safe collection name based on active embedding provider and model."""
        prov = (settings.DEFAULT_EMBEDDING_PROVIDER or "ollama").lower()
        if "ollama" in prov:
            return "rag_documents"
        model = (settings.DEFAULT_EMBEDDING_MODEL or "default").lower()
        model_clean = re.sub(r"[^a-zA-Z0-9_]", "_", model).strip("_")
        return f"rag_{prov}_{model_clean}"

    def reset_connection(self) -> None:
        """Reset the cached PGVector or Chroma store and cleanly dispose underlying connection pools."""
        try:
            if self._store is not None and hasattr(self._store, "_engine") and self._store._engine:
                self._store._engine.dispose()
        except Exception as e:
            logger.debug(f"Vector store engine disposal notice: {e}")
        self._store = None
        self._current_collection_name = None

    def _get_store(self) -> Any:
        """Get or initialize the underlying PGVector (or Chroma fallback) store."""
        target_name = self.get_collection_name()

        # Re-initialize if embedding configuration or collection target changed
        if self._store is None or self._current_collection_name != target_name:
            try:
                embeddings = ModelFactory.get_embeddings()

                if self.is_postgres:
                    from langchain_postgres import PGVector

                    conn_str = settings.vector_database_url
                    engine_args = {
                        "pool_pre_ping": True,
                        "pool_recycle": 300,
                        "pool_size": 10,
                        "max_overflow": 20,
                    }
                    self._store = PGVector(
                        embeddings=embeddings,
                        connection=conn_str,
                        collection_name=target_name,
                        use_jsonb=True,
                        engine_args=engine_args,
                    )
                    self._current_collection_name = target_name
                    logger.info(f"Initialized PostgreSQL pgvector store on collection '{target_name}' with pool_pre_ping=True")
                else:
                    from langchain_chroma import Chroma

                    self._store = Chroma(
                        collection_name=target_name,
                        embedding_function=embeddings,
                        persist_directory=str(self.persist_dir),
                    )
                    self._current_collection_name = target_name
                    logger.info(f"Initialized Chroma vector store on collection '{target_name}' at '{self.persist_dir}'")

            except Exception as e:
                logger.error(f"Failed to initialize vector store: {e}")
                self.reset_connection()
                raise VectorStoreError(f"Vector store initialization error: {str(e)}")

        return self._store

    def add_chunks(self, chunks: List[LCDocument], batch_size: Optional[int] = None, max_retries: int = 3) -> int:
        """Add document chunks to vector database in batches with auto-reconnect resilience."""
        if not chunks:
            return 0

        effective_batch_size = batch_size or getattr(settings, "EMBEDDING_BATCH_SIZE", 8)
        store = self._get_store()
        total = len(chunks)
        total_batches = (total + effective_batch_size - 1) // effective_batch_size

        for idx in range(0, total, effective_batch_size):
            batch = chunks[idx : idx + effective_batch_size]
            ids = [chunk.metadata.get("chunk_id") for chunk in batch]
            current_batch = (idx // effective_batch_size) + 1

            batch_attempt = 0
            batch_success = False
            last_err = None

            while batch_attempt < max_retries and not batch_success:
                batch_attempt += 1
                try:
                    store.add_documents(documents=batch, ids=ids)
                    batch_success = True
                    logger.info(f"Indexed batch {current_batch}/{total_batches} ({len(batch)} chunks)")
                except Exception as e:
                    last_err = e
                    err_str = str(e).lower()
                    is_transient = any(
                        k in err_str
                        for k in (
                            "timed out",
                            "timeout",
                            "connecttimeout",
                            "readtimeout",
                            "closed the connection",
                            "operationalerror",
                            "broken pipe",
                            "connection refused",
                            "terminat",
                            "server closed",
                            "connection lost",
                            "disconnected",
                            "remote disconnected",
                        )
                    )
                    if is_transient and batch_attempt < max_retries:
                        wait_sec = 2.0 * batch_attempt
                        logger.warning(
                            f"Transient indexing error on batch {current_batch}/{total_batches} (attempt {batch_attempt}/{max_retries}): {e}. "
                            f"Retrying in {wait_sec:.1f}s..."
                        )
                        time.sleep(wait_sec)
                        self.reset_connection()
                        store = self._get_store()
                    else:
                        break

            if not batch_success:
                logger.error(f"Failed to index batch {current_batch}/{total_batches} in vector store after {batch_attempt} attempts: {last_err}", exc_info=True)
                self.reset_connection()
                raise VectorStoreError(f"Failed to index chunks: {str(last_err)}")

        logger.info(f"Successfully indexed all {total} chunks into collection '{self.get_collection_name()}'")
        return total

    def delete_document(self, document_id: str) -> bool:
        """Delete all vectors associated with a specific document ID."""
        try:
            if self.is_postgres:
                engine = create_engine(settings.vector_database_url, pool_pre_ping=True)
                try:
                    with engine.connect() as conn:
                        result = conn.execute(
                            text("DELETE FROM langchain_pg_embedding WHERE cmetadata->>'document_id' = :doc_id"),
                            {"doc_id": document_id},
                        )
                        conn.commit()
                        deleted_count = result.rowcount
                    logger.info(f"Deleted {deleted_count} vectors from PostgreSQL for document {document_id}")
                    return True
                finally:
                    engine.dispose()
            else:
                store = self._get_store()
                collection = getattr(store, "_collection", None)
                if collection:
                    existing = collection.get(where={"document_id": document_id})
                    ids_to_delete = existing.get("ids", [])
                    if ids_to_delete:
                        collection.delete(ids=ids_to_delete)
                        logger.info(f"Deleted {len(ids_to_delete)} vectors for document {document_id}")
                return True
        except Exception as e:
            logger.error(f"Failed to delete document vectors for {document_id}: {e}")
            raise VectorStoreError(f"Failed to delete document from vector store: {str(e)}")

    def copy_document_vectors(
        self,
        source_doc_id: str,
        target_doc_id: str,
        new_filename: Optional[str] = None,
    ) -> int:
        """Duplicate existing vector embeddings from source document to target document without re-embedding."""
        try:
            if self.is_postgres:
                engine = create_engine(settings.vector_database_url, pool_pre_ping=True)
                try:
                    with engine.connect() as conn:
                        rows = conn.execute(
                            text(
                                "SELECT collection_id, embedding, document, cmetadata FROM langchain_pg_embedding WHERE cmetadata->>'document_id' = :source_id"
                            ),
                            {"source_id": source_doc_id},
                        ).fetchall()
                        if not rows:
                            return 0

                        for row in rows:
                            meta = row[3]
                            if isinstance(meta, str):
                                meta = json.loads(meta)
                            elif not isinstance(meta, dict):
                                meta = dict(meta or {})
                            else:
                                meta = dict(meta)

                            meta["document_id"] = target_doc_id
                            if new_filename:
                                meta["filename"] = new_filename
                            chunk_idx = meta.get("chunk_index", 0)
                            meta["chunk_id"] = f"{target_doc_id}_chunk_{chunk_idx}"

                            new_id = str(uuid.uuid4())
                            conn.execute(
                                text("""
                                    INSERT INTO langchain_pg_embedding (id, collection_id, embedding, document, cmetadata)
                                    VALUES (:id, :collection_id, :embedding, :document, :cmetadata)
                                """),
                                {
                                    "id": new_id,
                                    "collection_id": row[0],
                                    "embedding": row[1],
                                    "document": row[2],
                                    "cmetadata": json.dumps(meta),
                                },
                            )
                        conn.commit()
                        logger.info(
                            f"Fast-copied {len(rows)} vectors in PostgreSQL from {source_doc_id} to {target_doc_id} (skipped LLM embedding)"
                        )
                        return len(rows)
                finally:
                    engine.dispose()
            else:
                store = self._get_store()
                collection = getattr(store, "_collection", None)
                if collection:
                    existing = collection.get(
                        where={"document_id": source_doc_id},
                        include=["embeddings", "documents", "metadatas"],
                    )
                    ids = existing.get("ids", [])
                    embeddings = existing.get("embeddings", [])
                    documents = existing.get("documents", [])
                    metadatas = existing.get("metadatas", [])

                    if ids and embeddings and documents and metadatas:
                        new_ids = []
                        new_metadatas = []
                        for i, meta in enumerate(metadatas):
                            m = dict(meta)
                            m["document_id"] = target_doc_id
                            if new_filename:
                                m["filename"] = new_filename
                            chunk_idx = m.get("chunk_index", i)
                            new_chunk_id = f"{target_doc_id}_chunk_{chunk_idx}"
                            m["chunk_id"] = new_chunk_id
                            new_ids.append(new_chunk_id)
                            new_metadatas.append(m)

                        collection.add(
                            ids=new_ids,
                            embeddings=embeddings,
                            documents=documents,
                            metadatas=new_metadatas,
                        )
                        logger.info(
                            f"Fast-copied {len(new_ids)} vectors in Chroma from {source_doc_id} to {target_doc_id} (skipped LLM embedding)"
                        )
                        return len(new_ids)
                return 0
        except Exception as e:
            logger.warning(f"Note during copy_document_vectors from {source_doc_id} to {target_doc_id}: {e}")
            return 0

    def sync_from_database(self, document_ids: Optional[List[str]] = None, limit: Optional[int] = None) -> int:
        """Synchronize document chunks from relational database into the active vector collection."""
        try:
            engine = create_engine(
                settings.vector_database_url if self.is_postgres else f"sqlite:///{settings.DATA_DIR / 'sqlite.db'}",
                pool_pre_ping=True,
            )
            try:
                with engine.connect() as conn:
                    query = "SELECT id, document_id, chunk_index, content, chunk_metadata FROM document_chunks"
                    params: Dict[str, Any] = {}

                    if document_ids:
                        query += " WHERE document_id = ANY(:doc_ids)" if self.is_postgres else " WHERE document_id IN :doc_ids"
                        params["doc_ids"] = document_ids

                    query += " ORDER BY chunk_index ASC"
                    if limit:
                        query += f" LIMIT {int(limit)}"

                    rows = conn.execute(text(query), params).fetchall()
            finally:
                engine.dispose()

            if not rows:
                return 0

            chunks_to_add: List[LCDocument] = []
            for row in rows:
                c_id, doc_id, c_idx, content, raw_meta = row
                try:
                    meta = json.loads(raw_meta) if isinstance(raw_meta, str) else (raw_meta or {})
                except Exception:
                    meta = {}
                meta["chunk_id"] = str(c_id)
                meta["document_id"] = str(doc_id)
                meta["chunk_index"] = c_idx

                chunks_to_add.append(LCDocument(page_content=content, metadata=meta))

            logger.info(f"Syncing {len(chunks_to_add)} chunks into vector collection '{self.get_collection_name()}'")
            return self.add_chunks(chunks_to_add)
        except Exception as e:
            logger.error(f"Error syncing chunks from database: {e}", exc_info=True)
            return 0

    # Backwards-compatibility alias
    sync_from_sqlite = sync_from_database

    def similarity_search_with_score(
        self,
        query: str,
        k: int = 4,
        similarity_threshold: float = 0.25,
        document_ids: Optional[List[str]] = None,
        max_retries: int = 2,
    ) -> List[Tuple[LCDocument, float]]:
        """Retrieve most relevant document chunks with automatic threshold filtering and auto-reconnect."""
        attempt = 0
        while attempt < max_retries:
            attempt += 1
            try:
                store = self._get_store()

                filter_dict = None
                if document_ids:
                    if len(document_ids) == 1:
                        filter_dict = {"document_id": document_ids[0]}
                    else:
                        filter_dict = {"document_id": {"$in": document_ids}}

                if self.is_postgres:
                    results = store.similarity_search_with_score(
                        query=query,
                        k=k,
                        filter=filter_dict,
                    )
                else:
                    results = store.similarity_search_with_relevance_scores(
                        query=query,
                        k=k,
                        filter=filter_dict,
                    )

                # Filter by similarity score threshold
                filtered_results = []
                for doc, score in results:
                    sim = float(score)
                    if self.is_postgres:
                        sim = max(0.0, 1.0 - (score / 2.0)) if score <= 2.0 else score
                    if sim >= similarity_threshold:
                        filtered_results.append((doc, sim))

                logger.info(
                    f"Query '{query[:30]}...' matched {len(results)} chunks, {len(filtered_results)} above threshold {similarity_threshold}"
                )
                return filtered_results

            except Exception as e:
                err_str = str(e).lower()
                is_conn_error = any(
                    k in err_str
                    for k in (
                        "closed the connection",
                        "operationalerror",
                        "broken pipe",
                        "connection refused",
                        "terminat",
                        "server closed",
                        "connection lost",
                    )
                )
                if is_conn_error and attempt < max_retries:
                    logger.warning(
                        f"Vector store connection dropped during search (attempt {attempt}/{max_retries}): {e}. "
                        "Re-initializing connection pool and retrying..."
                    )
                    self.reset_connection()
                    continue

                logger.error(f"Similarity search failed for query '{query}': {e}", exc_info=True)
                self.reset_connection()
                raise VectorStoreError(f"Vector search failed: {str(e)}")

    def check_health(self) -> Dict[str, Any]:
        """Verify vector store connectivity and collection status."""
        try:
            if self.is_postgres:
                engine = create_engine(settings.vector_database_url, pool_pre_ping=True)
                try:
                    with engine.connect() as conn:
                        count = conn.execute(text("SELECT count(*) FROM langchain_pg_embedding")).scalar() or 0
                finally:
                    engine.dispose()
                return {
                    "status": "healthy",
                    "available": True,
                    "engine": "postgresql_pgvector",
                    "collection": self.get_collection_name(),
                    "total_vectors": count,
                }
            else:
                store = self._get_store()
                count = store._collection.count()
                return {
                    "status": "healthy",
                    "available": True,
                    "engine": "chroma",
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


# Backward-compatible ChromaVectorStore alias and global instance
ChromaVectorStore = PostgresVectorStore
vector_store = PostgresVectorStore()
