from __future__ import annotations

import sqlite3


def upgrade(conn: sqlite3.Connection) -> None:
    existing = {row[1] for row in conn.execute("PRAGMA table_info(admin_users)").fetchall()}
    if "can_issue_renewal" not in existing:
        conn.execute("ALTER TABLE admin_users ADD COLUMN can_issue_renewal INTEGER NOT NULL DEFAULT 0")
