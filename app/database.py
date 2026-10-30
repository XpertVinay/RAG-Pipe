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

is_sqlite = "sqlite" in settings.DATABASE_URL

if is_sqlite:
    engine: AsyncEngine = create_async_engine(
        settings.DATABASE_URL,
        echo=False,
        future=True,
        connect_args={"check_same_thread": False},
    )
else:
    engine: AsyncEngine = create_async_engine(
        settings.DATABASE_URL,
        echo=False,
        future=True,
        pool_size=getattr(settings, "DB_POOL_SIZE", 50),
        max_overflow=getattr(settings, "DB_MAX_OVERFLOW", 50),
        pool_timeout=getattr(settings, "DB_POOL_TIMEOUT", 20.0),
        pool_recycle=getattr(settings, "DB_POOL_RECYCLE", 1800),
        pool_pre_ping=True,
    )


# High-Performance SQLite Configuration: WAL mode, memory caching, non-blocking I/O
@event.listens_for(Engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    # Only execute SQLite pragmas if the connection is truly a sqlite3 connection
    conn_mod = getattr(dbapi_connection, "__module__", "") or ""
    conn_type = type(dbapi_connection).__name__.lower()
    if "sqlite" in conn_mod or "sqlite" in conn_type:
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

# Alias for background services and workers
async_session_factory = AsyncSessionLocal


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy ORM models."""
    pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency for providing database sessions per request."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            if session.is_active:
                if session.dirty or session.new or session.deleted:
                    await session.commit()
        except Exception:
            if session.is_active:
                await session.rollback()
            raise
        finally:
            if session.is_active:
                await session.close()


async def init_db() -> None:
    """Initialize database tables, apply backward-compatible column migrations, and create high-speed indexes."""
    import app.models  # noqa: F401 - Register models with metadata
    from sqlalchemy import inspect, text

    def migrate_and_index_tables(sync_conn):
        try:
            insp = inspect(sync_conn)
            table_names = set(insp.get_table_names())

            def get_cols(table: str):
                if table not in table_names:
                    return set()
                return {col["name"] for col in insp.get_columns(table)}

            # Migrate conversations table
            conv_cols = get_cols("conversations")
            if conv_cols:
                if "room_id" not in conv_cols:
                    sync_conn.execute(text("ALTER TABLE conversations ADD COLUMN room_id VARCHAR(36)"))
                if "user_id" not in conv_cols:
                    sync_conn.execute(text("ALTER TABLE conversations ADD COLUMN user_id VARCHAR(36)"))
                if "project_id" not in conv_cols:
                    sync_conn.execute(text("ALTER TABLE conversations ADD COLUMN project_id VARCHAR(36)"))

            # Migrate documents table
            doc_cols = get_cols("documents")
            if doc_cols:
                if "user_id" not in doc_cols:
                    sync_conn.execute(text("ALTER TABLE documents ADD COLUMN user_id VARCHAR(36)"))
                if "uploader_username" not in doc_cols:
                    sync_conn.execute(text("ALTER TABLE documents ADD COLUMN uploader_username VARCHAR(100)"))
                if "uploader_email" not in doc_cols:
                    sync_conn.execute(text("ALTER TABLE documents ADD COLUMN uploader_email VARCHAR(255)"))
                if "client_ip" not in doc_cols:
                    sync_conn.execute(text("ALTER TABLE documents ADD COLUMN client_ip VARCHAR(45)"))
                if "user_agent" not in doc_cols:
                    sync_conn.execute(text("ALTER TABLE documents ADD COLUMN user_agent VARCHAR(512)"))
                if "audit_metadata" not in doc_cols:
                    sync_conn.execute(text("ALTER TABLE documents ADD COLUMN audit_metadata JSON DEFAULT '{}'"))
                if "is_persistent_vector" not in doc_cols:
                    sync_conn.execute(text("ALTER TABLE documents ADD COLUMN is_persistent_vector BOOLEAN DEFAULT TRUE"))
                if "is_shared" not in doc_cols:
                    sync_conn.execute(text("ALTER TABLE documents ADD COLUMN is_shared BOOLEAN DEFAULT FALSE"))

            # Migrate rooms table
            room_cols = get_cols("rooms")
            if room_cols:
                if "is_public" not in room_cols:
                    sync_conn.execute(text("ALTER TABLE rooms ADD COLUMN is_public BOOLEAN DEFAULT FALSE"))
                if "share_token" not in room_cols:
                    sync_conn.execute(text("ALTER TABLE rooms ADD COLUMN share_token VARCHAR(64)"))
                if "share_revoked" not in room_cols:
                    sync_conn.execute(text("ALTER TABLE rooms ADD COLUMN share_revoked BOOLEAN DEFAULT FALSE"))
                if "pii_consent_status" not in room_cols:
                    sync_conn.execute(text("ALTER TABLE rooms ADD COLUMN pii_consent_status VARCHAR(50) DEFAULT 'clean'"))

            # Migrate organizations table for Mandate support
            org_cols = get_cols("organizations")
            if org_cols:
                if "mandate_id" not in org_cols:
                    sync_conn.execute(text("ALTER TABLE organizations ADD COLUMN mandate_id VARCHAR(100)"))
                if "mandate_status" not in org_cols:
                    sync_conn.execute(text("ALTER TABLE organizations ADD COLUMN mandate_status VARCHAR(50) DEFAULT 'none'"))
                if "mandate_next_charge_at" not in org_cols:
                    sync_conn.execute(text("ALTER TABLE organizations ADD COLUMN mandate_next_charge_at TIMESTAMP WITH TIME ZONE"))

            # Migrate subscription_orders table for Razorpay & Mandate
            order_cols = get_cols("subscription_orders")
            if order_cols:
                if "currency" not in order_cols:
                    sync_conn.execute(text("ALTER TABLE subscription_orders ADD COLUMN currency VARCHAR(10) DEFAULT 'INR'"))
                if "razorpay_order_id" not in order_cols:
                    sync_conn.execute(text("ALTER TABLE subscription_orders ADD COLUMN razorpay_order_id VARCHAR(100)"))
                if "razorpay_payment_id" not in order_cols:
                    sync_conn.execute(text("ALTER TABLE subscription_orders ADD COLUMN razorpay_payment_id VARCHAR(100)"))
                if "razorpay_subscription_id" not in order_cols:
                    sync_conn.execute(text("ALTER TABLE subscription_orders ADD COLUMN razorpay_subscription_id VARCHAR(100)"))
                if "razorpay_signature" not in order_cols:
                    sync_conn.execute(text("ALTER TABLE subscription_orders ADD COLUMN razorpay_signature VARCHAR(255)"))

            # Migrate projects table for application creation requests and call transcripts
            proj_cols = get_cols("projects")
            if proj_cols:
                if "client_name" not in proj_cols:
                    sync_conn.execute(text("ALTER TABLE projects ADD COLUMN client_name VARCHAR(255)"))
                if "email" not in proj_cols:
                    sync_conn.execute(text("ALTER TABLE projects ADD COLUMN email VARCHAR(255)"))
                if "phone" not in proj_cols:
                    sync_conn.execute(text("ALTER TABLE projects ADD COLUMN phone VARCHAR(50)"))
                if "communication_channel" not in proj_cols:
                    sync_conn.execute(text("ALTER TABLE projects ADD COLUMN communication_channel VARCHAR(50) DEFAULT 'Gmeet'"))
                if "request_type" not in proj_cols:
                    sync_conn.execute(text("ALTER TABLE projects ADD COLUMN request_type VARCHAR(50) DEFAULT 'standard'"))
                if "transcripts" not in proj_cols:
                    sync_conn.execute(text("ALTER TABLE projects ADD COLUMN transcripts TEXT"))
                if "meeting_link" not in proj_cols:
                    sync_conn.execute(text("ALTER TABLE projects ADD COLUMN meeting_link VARCHAR(500)"))
                if "call_initiated_at" not in proj_cols:
                    sync_conn.execute(text("ALTER TABLE projects ADD COLUMN call_initiated_at TIMESTAMP WITH TIME ZONE"))
                if "call_notes" not in proj_cols:
                    sync_conn.execute(text("ALTER TABLE projects ADD COLUMN call_notes TEXT"))

            # Performance indexes for joins and rapid lookups
            indexes = [
                "CREATE INDEX IF NOT EXISTS idx_sub_orders_rzp_order ON subscription_orders(razorpay_order_id);",
                "CREATE INDEX IF NOT EXISTS idx_sub_orders_rzp_pay ON subscription_orders(razorpay_payment_id);",
                "CREATE INDEX IF NOT EXISTS idx_sub_orders_rzp_sub ON subscription_orders(razorpay_subscription_id);",
                "CREATE INDEX IF NOT EXISTS idx_projects_req_type ON projects(request_type);",
                "CREATE INDEX IF NOT EXISTS idx_invoices_org_id ON invoices(organization_id);",
                "CREATE INDEX IF NOT EXISTS idx_invoices_user_id ON invoices(user_id);",
                "CREATE INDEX IF NOT EXISTS idx_invoices_number ON invoices(invoice_number);",
                "CREATE INDEX IF NOT EXISTS idx_invoices_rzp_payment ON invoices(razorpay_payment_id);",
                "CREATE INDEX IF NOT EXISTS idx_invoices_rzp_sub ON invoices(razorpay_subscription_id);",
                "CREATE INDEX IF NOT EXISTS idx_system_settings_category ON system_settings(category);",
                "CREATE INDEX IF NOT EXISTS idx_pricing_plans_active ON pricing_plans(is_active);",
                "CREATE INDEX IF NOT EXISTS idx_documents_user_id ON documents(user_id);",
                "CREATE INDEX IF NOT EXISTS idx_documents_uploader_email ON documents(uploader_email);",
                "CREATE INDEX IF NOT EXISTS idx_documents_is_shared ON documents(is_shared);",
                "CREATE INDEX IF NOT EXISTS idx_rooms_is_public ON rooms(is_public);",
                "CREATE INDEX IF NOT EXISTS idx_rooms_share_token ON rooms(share_token);",
                "CREATE INDEX IF NOT EXISTS idx_rooms_share_revoked ON rooms(share_revoked);",
                "CREATE INDEX IF NOT EXISTS idx_rooms_pii_consent ON rooms(pii_consent_status);",
                "CREATE INDEX IF NOT EXISTS idx_projects_room_id ON projects(room_id);",
                "CREATE INDEX IF NOT EXISTS idx_projects_user_id ON projects(user_id);",
                "CREATE INDEX IF NOT EXISTS idx_projects_status ON projects(status);",
                "CREATE INDEX IF NOT EXISTS idx_conversations_project_id ON conversations(project_id);",
                "CREATE INDEX IF NOT EXISTS idx_room_members_room_id ON room_members(room_id);",
                "CREATE INDEX IF NOT EXISTS idx_room_members_user_id ON room_members(user_id);",
                "CREATE INDEX IF NOT EXISTS idx_audit_logs_user_id ON audit_logs(user_id);",
                "CREATE INDEX IF NOT EXISTS idx_audit_logs_entity ON audit_logs(entity_type, entity_id);",
                "CREATE INDEX IF NOT EXISTS idx_audit_logs_action ON audit_logs(action);",
                "CREATE INDEX IF NOT EXISTS idx_audit_logs_created_at ON audit_logs(created_at);",
                "CREATE INDEX IF NOT EXISTS idx_room_documents_room_id ON room_documents(room_id);",
                "CREATE INDEX IF NOT EXISTS idx_room_documents_doc_id ON room_documents(document_id);",
                "CREATE INDEX IF NOT EXISTS idx_conversations_room_id ON conversations(room_id);",
                "CREATE INDEX IF NOT EXISTS idx_conversations_user_id ON conversations(user_id);",
                "CREATE INDEX IF NOT EXISTS idx_messages_conv_created ON messages(conversation_id, created_at);",
                "CREATE INDEX IF NOT EXISTS idx_doc_chunks_doc_idx ON document_chunks(document_id, chunk_index);",
                "CREATE INDEX IF NOT EXISTS idx_refresh_tokens_token ON refresh_tokens(token);",
                "CREATE INDEX IF NOT EXISTS idx_refresh_tokens_user ON refresh_tokens(user_id);",
                "CREATE INDEX IF NOT EXISTS idx_memories_scope_type ON memories(scope, memory_type);",
                "CREATE INDEX IF NOT EXISTS idx_memories_user_id ON memories(user_id);",
                "CREATE INDEX IF NOT EXISTS idx_memories_doc_id ON memories(document_id);",
                "CREATE INDEX IF NOT EXISTS idx_memories_expires_at ON memories(expires_at);",
                "CREATE INDEX IF NOT EXISTS idx_agent_workflows_user_id ON agent_workflows(user_id);",
                "CREATE INDEX IF NOT EXISTS idx_agent_workflows_room_id ON agent_workflows(room_id);",
                "CREATE INDEX IF NOT EXISTS idx_agent_workflows_status ON agent_workflows(status);",
                "CREATE INDEX IF NOT EXISTS idx_agent_subtasks_wf_idx ON agent_subtasks(workflow_id, task_number);",
                "CREATE INDEX IF NOT EXISTS idx_agent_subtasks_status ON agent_subtasks(status);",
                "CREATE INDEX IF NOT EXISTS idx_agent_subtasks_role ON agent_subtasks(agent_role);",
            ]
            for idx_stmt in indexes:
                try:
                    sync_conn.execute(text(idx_stmt))
                except Exception:
                    pass
        except Exception as e:
            import logging
            logging.getLogger("rag_agent").warning(f"Schema migration/indexing note: {e}")

    try:
        async with engine.begin() as conn:
            if not is_sqlite:
                try:
                    await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))
                except Exception as ext_err:
                    import logging
                    logging.getLogger("rag_agent").warning(f"Note on CREATE EXTENSION vector: {ext_err}")
            await conn.run_sync(Base.metadata.create_all)
            await conn.run_sync(migrate_and_index_tables)
    except Exception as e:
        if "readonly database" in str(e).lower():
            import logging
            import os
            uid = os.getuid() if hasattr(os, "getuid") else "N/A"
            logging.getLogger("rag_agent").critical(
                f"DATABASE PERMISSION ERROR: SQLite database file or directory is not writable by current process (UID {uid}).\n"
                f"Resolved database URL: {settings.DATABASE_URL}\n"
                f"To fix in Docker: run 'docker compose exec -u root <container_name> chown -R appuser:appgroup /app/data'\n"
                f"To fix on Host: run 'chmod -R 777 ./data' or 'sudo chown -R $USER ./data'"
            )
        raise
