from __future__ import annotations

import sqlite3


def upgrade(conn: sqlite3.Connection) -> None:
    columns = {row[1] for row in conn.execute("PRAGMA table_info(customers)").fetchall()}
    if "deleted_at" not in columns:
        conn.execute("ALTER TABLE customers ADD COLUMN deleted_at TEXT")
    if "deleted_by" not in columns:
        conn.execute("ALTER TABLE customers ADD COLUMN deleted_by TEXT")
    if "deleted_reason" not in columns:
        conn.execute("ALTER TABLE customers ADD COLUMN deleted_reason TEXT")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_customers_deleted_at ON customers(deleted_at)")
