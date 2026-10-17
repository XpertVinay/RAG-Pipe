"""Database configuration and session management using SQLAlchemy."""

from typing import AsyncGenerator
from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings

settings = get_settings()

engine: AsyncEngine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    future=True,
    connect_args={"check_same_thread": False} if "sqlite" in settings.DATABASE_URL else {},
)


# High-Performance SQLite Configuration: WAL mode, memory caching, non-blocking I/O
@event.listens_for(Engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    if "sqlite" in settings.DATABASE_URL:
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA journal_mode=WAL;")
            cursor.execute("PRAGMA synchronous=NORMAL;")
            cursor.execute("PRAGMA cache_size=-64000;")  # 64MB memory page cache
            cursor.execute("PRAGMA temp_store=MEMORY;")
            cursor.execute("PRAGMA mmap_size=268435456;")  # 256MB memory-mapped I/O
        except Exception:
            pass
        finally:
            cursor.close()


AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
    class_=AsyncSession,
)


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy ORM models."""
    pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency for providing database sessions per request."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db() -> None:
    """Initialize database tables, apply backward-compatible column migrations, and create high-speed indexes."""
    import app.models  # noqa: F401 - Register models with metadata

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

        def migrate_and_index_tables(sync_conn):
            cursor = sync_conn.connection.cursor()
            try:
                # Migrate conversations table
                cursor.execute("PRAGMA table_info(conversations)")
                conv_cols = [row[1] for row in cursor.fetchall()]
                if conv_cols:
                    if "room_id" not in conv_cols:
                        cursor.execute("ALTER TABLE conversations ADD COLUMN room_id VARCHAR(36)")
                    if "user_id" not in conv_cols:
                        cursor.execute("ALTER TABLE conversations ADD COLUMN user_id VARCHAR(36)")

                # Migrate documents table
                cursor.execute("PRAGMA table_info(documents)")
                doc_cols = [row[1] for row in cursor.fetchall()]
                if doc_cols:
                    if "user_id" not in doc_cols:
                        cursor.execute("ALTER TABLE documents ADD COLUMN user_id VARCHAR(36)")

                # Create performance indexes for joins and rapid lookups
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_room_documents_room_id ON room_documents(room_id);")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_room_documents_doc_id ON room_documents(document_id);")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_conversations_room_id ON conversations(room_id);")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_conversations_user_id ON conversations(user_id);")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_messages_conv_created ON messages(conversation_id, created_at);")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_doc_chunks_doc_idx ON document_chunks(document_id, chunk_index);")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_refresh_tokens_token ON refresh_tokens(token);")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_refresh_tokens_user ON refresh_tokens(user_id);")
            except Exception as e:
                import logging
                logging.getLogger("rag_agent").warning(f"Schema migration/indexing note: {e}")
            finally:
                cursor.close()

        if "sqlite" in settings.DATABASE_URL:
            await conn.run_sync(migrate_and_index_tables)
