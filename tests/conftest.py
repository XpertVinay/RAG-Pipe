"""Pytest configuration, fixtures, and deterministic test mocks."""

import os
import sys
import tempfile
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from typing import AsyncGenerator, Generator, List, Optional
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from langchain_core.embeddings import Embeddings
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Set test environment
os.environ["APP_ENV"] = "testing"
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"

from app.agent.state import AgentState
from app.config import Settings, get_settings
import app.models  # Ensure all models (User, Room, etc.) are registered
from app.database import Base, get_db
from app.main import app
from app.providers.factory import ModelFactory

if not hasattr(ModelFactory, "_orig_get_chat_model"):
    ModelFactory._orig_get_chat_model = ModelFactory.get_chat_model


class DeterministicMockEmbeddings(Embeddings):
    """Deterministic embedding mock for offline testing."""

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        # Return 8-dim normalized mock vectors based on text length
        vectors = []
        for text in texts:
            val = (len(text) % 100) / 100.0
            vectors.append([val] * 8)
        return vectors

    def embed_query(self, text: str) -> List[float]:
        val = (len(text) % 100) / 100.0
        return [val] * 8


class DeterministicMockChatModel(BaseChatModel):
    """Deterministic chat model mock for offline unit testing."""

    def _generate(self, messages: List[BaseMessage], stop=None, **kwargs):
        raise NotImplementedError

    async def _agenerate(self, messages: List[BaseMessage], stop=None, **kwargs):
        last_msg = messages[-1].content if messages else ""
        if "relevance" in str(messages[0].content).lower():
            text = "yes"
        elif "auditor" in str(messages[0].content).lower():
            text = "yes"
        elif "optimizer" in str(messages[0].content).lower():
            text = "rewritten search query"
        else:
            text = "This is a deterministic grounded answer from mock LLM."

        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=text))])

    async def astream(self, messages: List[BaseMessage], stop=None, **kwargs):
        tokens = ["This", " is", " a", " test", " grounded", " response."]
        for token in tokens:
            yield AIMessage(content=token)

    @property
    def _llm_type(self) -> str:
        return "deterministic-mock"


@pytest.fixture(autouse=True)
def mock_factory_providers(monkeypatch):
    """Patch ModelFactory to return deterministic mocks by default during unit tests."""
    mock_model = DeterministicMockChatModel()
    mock_embed = DeterministicMockEmbeddings()

    monkeypatch.setattr(ModelFactory, "get_chat_model", lambda *args, **kwargs: mock_model)
    monkeypatch.setattr(ModelFactory, "get_embeddings", lambda *args, **kwargs: mock_embed)


@pytest_asyncio.fixture
async def test_db() -> AsyncGenerator[AsyncSession, None]:
    """Provide a shared SQLite test database session for test client and background tasks."""
    import app.database as app_db

    temp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    temp_db_path = temp_db.name
    temp_db.close()

    test_engine = create_async_engine(
        f"sqlite+aiosqlite:///{temp_db_path}",
        echo=False,
        future=True,
        connect_args={"check_same_thread": False, "timeout": 30},
    )

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    TestSessionLocal = async_sessionmaker(
        bind=test_engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
        class_=AsyncSession,
    )

    # Patch global app.database so background tasks use this test DB
    orig_engine = app_db.engine
    orig_sessionmaker = app_db.AsyncSessionLocal
    app_db.engine = test_engine
    app_db.AsyncSessionLocal = TestSessionLocal

    async with TestSessionLocal() as session:
        yield session

    app_db.engine = orig_engine
    app_db.AsyncSessionLocal = orig_sessionmaker

    await test_engine.dispose()
    if os.path.exists(temp_db_path):
        os.remove(temp_db_path)


@pytest_asyncio.fixture
async def client(test_db: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """HTTP async client configured with test database session override and authenticated user."""
    from fastapi import HTTPException, Request, Security, status
    from fastapi.security import HTTPAuthorizationCredentials
    from sqlalchemy import select
    from app.core.auth import (
        bearer_scheme,
        decode_token,
        extract_token_from_request,
        get_current_user,
        get_optional_user,
    )
    from app.models.user import User

    async def override_get_db():
        yield test_db

    test_user = User(
        id="test-auth-user-id",
        email="testuser@example.com",
        username="testuser",
        hashed_password="mock_hashed_password",
        role="admin",
        is_active=True,
    )
    test_db.add(test_user)
    await test_db.commit()

    async def override_get_current_user(
        request: Request,
        auth: Optional[HTTPAuthorizationCredentials] = Security(bearer_scheme),
    ) -> User:
        token = extract_token_from_request(request, auth)
        if token:
            payload = decode_token(token, expected_type="access")
            user_id = payload.get("sub")
            if user_id:
                res = await test_db.execute(select(User).where(User.id == user_id))
                user = res.scalar_one_or_none()
                if user:
                    if not user.is_active:
                        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User account is deactivated.")
                    return user
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User account not found.")
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token subject.")

        # Disallow unauthenticated requests when an endpoint is explicitly probed for 401
        if "/upload" in request.url.path or request.headers.get("x-anonymous") == "true":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required. Missing Bearer access token.",
            )
        return test_user

    async def override_get_optional_user(
        request: Request,
        auth: Optional[HTTPAuthorizationCredentials] = Security(bearer_scheme),
    ) -> Optional[User]:
        token = extract_token_from_request(request, auth)
        if token:
            try:
                payload = decode_token(token, expected_type="access")
                user_id = payload.get("sub")
                if user_id:
                    res = await test_db.execute(select(User).where(User.id == user_id))
                    user = res.scalar_one_or_none()
                    if user and user.is_active:
                        return user
            except Exception:
                return None
        if request.headers.get("x-anonymous") == "true" or ("/file" in request.url.path and not token):
            return None
        return test_user

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user
    app.dependency_overrides[get_optional_user] = override_get_optional_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest.fixture
def temp_dir() -> Generator[Path, None, None]:
    """Temporary directory fixture for testing file operations."""
    with tempfile.TemporaryDirectory() as td:
        yield Path(td)
