from __future__ import annotations

import sqlite3


def upgrade(conn: sqlite3.Connection) -> None:
    existing = {row[1] for row in conn.execute("PRAGMA table_info(admin_users)").fetchall()}
    if "deleted_at" not in existing:
        conn.execute("ALTER TABLE admin_users ADD COLUMN deleted_at TEXT")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_admin_users_deleted_at ON admin_users(deleted_at)")
