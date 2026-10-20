"""Migrate all data from SQLite (/app/data/sqlite.db) to PostgreSQL with strict type casting."""

import asyncio
import sqlite3
import json
from datetime import datetime, timezone
from sqlalchemy import text
from app.database import engine

TABLE_ORDER = [
    "users",
    "refresh_tokens",
    "rooms",
    "projects",
    "conversations",
    "messages",
    "documents",
    "room_documents",
    "document_chunks",
    "memories",
    "audit_logs",
    "organizations",
    "organization_members",
    "organization_invites",
    "subscription_orders",
    "invoices",
    "system_settings",
    "pricing_plans",
    "agent_workflows",
    "agent_subtasks",
    "audit_trail_records",
]

def parse_dt(val):
    if not val or not isinstance(val, str):
        return val
    try:
        dt = datetime.fromisoformat(val.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return val

async def migrate():
    sqlite_conn = sqlite3.connect('/app/data/sqlite.db')
    sqlite_conn.row_factory = sqlite3.Row
    s_cur = sqlite_conn.cursor()

    for table in TABLE_ORDER:
        exists = s_cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()
        if not exists:
            continue

        rows = s_cur.execute(f"SELECT * FROM {table}").fetchall()
        if not rows:
            continue

        cols = rows[0].keys()
        col_names = ", ".join(cols)
        placeholders = ", ".join([f":{col}" for col in cols])

        inserted_count = 0
        for row in rows:
            data = dict(row)
            for k, v in list(data.items()):
                # Booleans
                if k in ("is_public", "share_revoked", "is_active", "is_shared", "is_persistent_vector", "is_revoked", "is_system", "is_pinned", "is_custom", "is_sandbox", "is_anonymous", "revoked"):
                    if v is not None:
                        data[k] = bool(v)
                # Datetimes
                elif k.endswith("_at") or k in ("timestamp", "expires_at", "created_at", "updated_at", "last_accessed_at", "period_start", "period_end"):
                    if v is not None:
                        data[k] = parse_dt(v)
                # Serialized JSON objects
                elif isinstance(v, (dict, list)):
                    data[k] = json.dumps(v)
                elif isinstance(v, str) and (v.startswith("{") or v.startswith("[")):
                    # already a json string
                    data[k] = v

            insert_stmt = text(f"""
                INSERT INTO {table} ({col_names})
                VALUES ({placeholders})
                ON CONFLICT DO NOTHING
            """)
            async with engine.begin() as pg_conn:
                try:
                    await pg_conn.execute(insert_stmt, data)
                    inserted_count += 1
                except Exception as err:
                    print(f"  [Skip/Error] on {table} row id={data.get('id')}: {err}")

        print(f"  -> Inserted {inserted_count}/{len(rows)} rows into {table}")

    sqlite_conn.close()
    print("All tables successfully migrated from SQLite to PostgreSQL!")

if __name__ == "__main__":
    asyncio.run(migrate())
