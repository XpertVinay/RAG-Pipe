"""Integration tests verifying PostgreSQL as SQL & Vector Database, and JWT session auth & authorization."""

import asyncio
from datetime import timedelta
import pytest
from httpx import ASGITransport, AsyncClient
from langchain_core.documents import Document as LCDocument
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import get_settings
from app.core.auth import (
    create_access_token,
    create_id_token,
    decode_token,
    hash_password,
    is_admin,
    is_admin_or_staff,
    verify_password,
)
from app.ingestion.vector_store import PostgresVectorStore
from app.main import app
from app.models.user import User


@pytest.mark.asyncio
async def test_postgres_sql_connection_and_pgvector():
    """Verify that PostgreSQL connection succeeds and pgvector extension is enabled."""
    settings = get_settings()
    # Connect directly to the PostgreSQL instance
    pg_url = "postgresql+asyncpg://postgres:postgres@localhost:5432/rag_agent"
    engine = create_async_engine(pg_url)

    async with engine.connect() as conn:
        # Check pgvector extension
        ext_res = await conn.execute(
            text("SELECT extname FROM pg_extension WHERE extname = 'vector';")
        )
        ext = ext_res.scalar_one_or_none()
        assert ext == "vector", "pgvector extension must be enabled in PostgreSQL"

        # Ensure metadata tables are created on PostgreSQL
        from app.database import Base
        await conn.run_sync(Base.metadata.create_all)

        # Check table creation
        tables_res = await conn.execute(
            text(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public';"
            )
        )
        table_names = [row[0] for row in tables_res.fetchall()]
        assert "users" in table_names
        assert "documents" in table_names
        assert "conversations" in table_names
        assert "document_chunks" in table_names

    await engine.dispose()


@pytest.mark.asyncio
async def test_postgres_vector_store_crud():
    """Verify pgvector vector store indexing, similarity search, and deletion on PostgreSQL."""
    settings = get_settings()
    orig_url = settings.DATABASE_URL
    settings.DATABASE_URL = "postgresql+asyncpg://postgres:postgres@localhost:5432/rag_agent"

    from langchain_core.embeddings import Embeddings
    from app.providers.factory import ModelFactory

    class Dim768Mock(Embeddings):
        def embed_documents(self, texts):
            return [[(len(t) % 100) / 100.0] * 768 for t in texts]
        def embed_query(self, text):
            return [(len(text) % 100) / 100.0] * 768

    orig_get_emb = ModelFactory.get_embeddings
    ModelFactory.get_embeddings = lambda: Dim768Mock()

    try:
        pv = PostgresVectorStore()
        pv.reset_connection()
        assert pv.is_postgres is True

        test_docs = [
            LCDocument(
                page_content="PostgreSQL with pgvector provides ACID relational storage and vector search.",
                metadata={"document_id": "test-doc-pg-1", "chunk_id": "c-1"},
            ),
            LCDocument(
                page_content="JWT access tokens carry cryptographically signed claims for stateless auth.",
                metadata={"document_id": "test-doc-pg-2", "chunk_id": "c-2"},
            ),
        ]

        indexed = pv.add_chunks(test_docs)
        assert indexed == 2

        # Query similarity search
        results = pv.similarity_search_with_score(
            query="relational database and vector search",
            k=2,
            similarity_threshold=0.1,
        )
        assert len(results) >= 1
        top_doc, score = results[0]
        assert score > 0.0

        # Test filtering by document_id
        filtered = pv.similarity_search_with_score(
            query="stateless auth claims",
            k=1,
            similarity_threshold=0.1,
            document_ids=["test-doc-pg-2"],
        )
        assert len(filtered) == 1
        assert filtered[0][0].metadata.get("document_id") == "test-doc-pg-2"

        # Test deletion
        deleted = pv.delete_document("test-doc-pg-1")
        assert deleted is True
        deleted2 = pv.delete_document("test-doc-pg-2")
        assert deleted2 is True
    finally:
        ModelFactory.get_embeddings = orig_get_emb
        settings.DATABASE_URL = orig_url


@pytest.mark.asyncio
async def test_jwt_authentication_and_authorization_lifecycle():
    """Verify JWT password hashing, access token issuance, signature validation, and RBAC."""
    password = "SuperSecretPassword123!"
    hashed = hash_password(password)
    assert verify_password(password, hashed) is True
    assert verify_password("WrongPassword", hashed) is False

    mock_user = User(
        id="usr-jwt-test-123",
        email="developer@example.com",
        username="devuser",
        role="admin",
        is_active=True,
    )

    # 1. Issue access token
    access_token = create_access_token(mock_user, expires_delta=timedelta(minutes=30))
    assert isinstance(access_token, str) and len(access_token) > 20

    # 2. Decode access token
    payload = decode_token(access_token, expected_type="access")
    assert payload["sub"] == mock_user.id
    assert payload["email"] == mock_user.email
    assert payload["role"] == "admin"
    assert payload["type"] == "access"

    # 3. Issue ID token
    id_token = create_id_token(mock_user)
    id_payload = decode_token(id_token, expected_type="id_token")
    assert id_payload["sub"] == mock_user.id
    assert id_payload["iss"] == "rag-agent-auth"
    assert id_payload["aud"] == "rag-agent-client"

    # 4. Role authorization helper checks
    assert is_admin(mock_user) is True
    assert is_admin_or_staff(mock_user) is True

    staff_user = User(id="u2", email="staff@test.com", username="staff", role="staff")
    assert is_admin(staff_user) is False
    assert is_admin_or_staff(staff_user) is True

    regular_user = User(id="u3", email="user@test.com", username="user", role="user")
    assert is_admin(regular_user) is False
    assert is_admin_or_staff(regular_user) is False


@pytest.mark.asyncio
async def test_protected_routes_reject_unauthenticated_requests():
    """Verify that protected API endpoints reject requests without valid JWT access tokens."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Protected conversations endpoint
        resp = await client.post("/api/v1/chat/conversations?title=UnauthorizedChat")
        assert resp.status_code == 401
        assert "WWW-Authenticate" in resp.headers

        # Protected chat query
        resp_query = await client.post(
            "/api/v1/chat/query",
            json={"message": "Hello from an unauthenticated user"},
        )
        assert resp_query.status_code == 401

        # Protected chat stream
        resp_stream = await client.post(
            "/api/v1/chat/stream",
            json={"message": "Stream hello"},
        )
        assert resp_stream.status_code == 401

        # Protected create room
        resp_room = await client.post(
            "/api/v1/rooms",
            json={"name": "Protected Workspace"},
        )
        assert resp_room.status_code == 401
