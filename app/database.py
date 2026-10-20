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
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db() -> None:
    """Initialize database tables, apply backward-compatible column migrations, and create high-speed indexes."""
    import app.models  # noqa: F401 - Register models with metadata

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
                if "uploader_username" not in doc_cols:
                    cursor.execute("ALTER TABLE documents ADD COLUMN uploader_username VARCHAR(100)")
                if "uploader_email" not in doc_cols:
                    cursor.execute("ALTER TABLE documents ADD COLUMN uploader_email VARCHAR(255)")
                if "client_ip" not in doc_cols:
                    cursor.execute("ALTER TABLE documents ADD COLUMN client_ip VARCHAR(45)")
                if "user_agent" not in doc_cols:
                    cursor.execute("ALTER TABLE documents ADD COLUMN user_agent VARCHAR(512)")
                if "audit_metadata" not in doc_cols:
                    cursor.execute("ALTER TABLE documents ADD COLUMN audit_metadata JSON DEFAULT '{}'")
                if "is_persistent_vector" not in doc_cols:
                    cursor.execute("ALTER TABLE documents ADD COLUMN is_persistent_vector BOOLEAN DEFAULT 1")
                if "is_shared" not in doc_cols:
                    cursor.execute("ALTER TABLE documents ADD COLUMN is_shared BOOLEAN DEFAULT 0")

            # Migrate rooms table
            cursor.execute("PRAGMA table_info(rooms)")
            room_cols = [row[1] for row in cursor.fetchall()]
            if room_cols:
                if "is_public" not in room_cols:
                    cursor.execute("ALTER TABLE rooms ADD COLUMN is_public BOOLEAN DEFAULT 0")

            # Create room_members table if not exists
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS room_members (
                    id VARCHAR(36) PRIMARY KEY,
                    room_id VARCHAR(36) NOT NULL,
                    user_id VARCHAR(36) NOT NULL,
                    role VARCHAR(30) DEFAULT 'viewer',
                    created_at DATETIME NOT NULL
                )
            """)

            # Create audit_logs table if not exists
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS audit_logs (
                    id VARCHAR(36) PRIMARY KEY,
                    user_id VARCHAR(36),
                    username VARCHAR(100),
                    user_email VARCHAR(255),
                    action VARCHAR(50) NOT NULL,
                    entity_type VARCHAR(50) NOT NULL,
                    entity_id VARCHAR(36) NOT NULL,
                    client_ip VARCHAR(45),
                    user_agent VARCHAR(512),
                    details JSON DEFAULT '{}',
                    created_at DATETIME NOT NULL
                )
            """)

            # Migrate organizations table for Mandate support
            cursor.execute("PRAGMA table_info(organizations)")
            org_cols = [row[1] for row in cursor.fetchall()]
            if org_cols:
                if "mandate_id" not in org_cols:
                    cursor.execute("ALTER TABLE organizations ADD COLUMN mandate_id VARCHAR(100)")
                if "mandate_status" not in org_cols:
                    cursor.execute("ALTER TABLE organizations ADD COLUMN mandate_status VARCHAR(50) DEFAULT 'none'")
                if "mandate_next_charge_at" not in org_cols:
                    cursor.execute("ALTER TABLE organizations ADD COLUMN mandate_next_charge_at DATETIME")

            # Migrate subscription_orders table for Razorpay & Mandate
            cursor.execute("PRAGMA table_info(subscription_orders)")
            order_cols = [row[1] for row in cursor.fetchall()]
            if order_cols:
                if "currency" not in order_cols:
                    cursor.execute("ALTER TABLE subscription_orders ADD COLUMN currency VARCHAR(10) DEFAULT 'INR'")
                if "razorpay_order_id" not in order_cols:
                    cursor.execute("ALTER TABLE subscription_orders ADD COLUMN razorpay_order_id VARCHAR(100)")
                if "razorpay_payment_id" not in order_cols:
                    cursor.execute("ALTER TABLE subscription_orders ADD COLUMN razorpay_payment_id VARCHAR(100)")
                if "razorpay_subscription_id" not in order_cols:
                    cursor.execute("ALTER TABLE subscription_orders ADD COLUMN razorpay_subscription_id VARCHAR(100)")
                if "razorpay_signature" not in order_cols:
                    cursor.execute("ALTER TABLE subscription_orders ADD COLUMN razorpay_signature VARCHAR(255)")

            # Create invoices table if not exists for transparent mandate records
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS invoices (
                    id VARCHAR(36) PRIMARY KEY,
                    invoice_number VARCHAR(50) NOT NULL UNIQUE,
                    organization_id VARCHAR(36),
                    user_id VARCHAR(36) NOT NULL,
                    subscription_order_id VARCHAR(36),
                    razorpay_invoice_id VARCHAR(100) UNIQUE,
                    razorpay_payment_id VARCHAR(100),
                    razorpay_subscription_id VARCHAR(100),
                    plan_id VARCHAR(50) NOT NULL,
                    plan_name VARCHAR(100) NOT NULL,
                    billing_cycle VARCHAR(20) DEFAULT 'monthly',
                    amount FLOAT NOT NULL,
                    currency VARCHAR(10) DEFAULT 'INR',
                    status VARCHAR(50) DEFAULT 'paid',
                    billing_name VARCHAR(150) NOT NULL,
                    billing_email VARCHAR(255) NOT NULL,
                    paid_at DATETIME,
                    invoice_pdf_url VARCHAR(500),
                    notes TEXT,
                    created_at DATETIME NOT NULL
                )
            """)

            # Create system_settings table if not exists
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS system_settings (
                    key VARCHAR(100) PRIMARY KEY,
                    value TEXT NOT NULL,
                    category VARCHAR(50) DEFAULT 'general',
                    description TEXT,
                    updated_at DATETIME NOT NULL
                )
            """)

            # Create pricing_plans table if not exists
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS pricing_plans (
                    id VARCHAR(50) PRIMARY KEY,
                    name VARCHAR(100) NOT NULL,
                    monthly_price FLOAT NOT NULL DEFAULT 0.0,
                    annual_price_per_month FLOAT NOT NULL DEFAULT 0.0,
                    inr_monthly_price FLOAT DEFAULT 0.0,
                    inr_annual_monthly_price FLOAT DEFAULT 0.0,
                    description TEXT NOT NULL,
                    badge VARCHAR(50) DEFAULT '',
                    features JSON DEFAULT '[]',
                    limits JSON DEFAULT '{}',
                    is_active BOOLEAN DEFAULT 1,
                    sort_order INTEGER DEFAULT 0,
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL
                )
            """)

            # Create performance indexes for joins and rapid lookups
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_sub_orders_rzp_order ON subscription_orders(razorpay_order_id);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_sub_orders_rzp_pay ON subscription_orders(razorpay_payment_id);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_sub_orders_rzp_sub ON subscription_orders(razorpay_subscription_id);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_invoices_org_id ON invoices(organization_id);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_invoices_user_id ON invoices(user_id);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_invoices_number ON invoices(invoice_number);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_invoices_rzp_payment ON invoices(razorpay_payment_id);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_invoices_rzp_sub ON invoices(razorpay_subscription_id);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_system_settings_category ON system_settings(category);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_pricing_plans_active ON pricing_plans(is_active);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_documents_user_id ON documents(user_id);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_documents_uploader_email ON documents(uploader_email);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_documents_is_shared ON documents(is_shared);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_rooms_is_public ON rooms(is_public);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_room_members_room_id ON room_members(room_id);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_room_members_user_id ON room_members(user_id);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_audit_logs_user_id ON audit_logs(user_id);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_audit_logs_entity ON audit_logs(entity_type, entity_id);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_audit_logs_action ON audit_logs(action);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_audit_logs_created_at ON audit_logs(created_at);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_room_documents_room_id ON room_documents(room_id);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_room_documents_doc_id ON room_documents(document_id);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_conversations_room_id ON conversations(room_id);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_conversations_user_id ON conversations(user_id);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_messages_conv_created ON messages(conversation_id, created_at);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_doc_chunks_doc_idx ON document_chunks(document_id, chunk_index);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_refresh_tokens_token ON refresh_tokens(token);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_refresh_tokens_user ON refresh_tokens(user_id);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_memories_scope_type ON memories(scope, memory_type);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_memories_user_id ON memories(user_id);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_memories_doc_id ON memories(document_id);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_memories_expires_at ON memories(expires_at);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_agent_workflows_user_id ON agent_workflows(user_id);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_agent_workflows_room_id ON agent_workflows(room_id);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_agent_workflows_status ON agent_workflows(status);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_agent_subtasks_wf_idx ON agent_subtasks(workflow_id, task_number);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_agent_subtasks_status ON agent_subtasks(status);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_agent_subtasks_role ON agent_subtasks(agent_role);")
        except Exception as e:
            import logging
            logging.getLogger("rag_agent").warning(f"Schema migration/indexing note: {e}")
        finally:
            cursor.close()

    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            if "sqlite" in settings.DATABASE_URL:
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
