from __future__ import annotations

import sqlite3


def upgrade(conn: sqlite3.Connection) -> None:
    existing = {row[1] for row in conn.execute("PRAGMA table_info(admin_users)").fetchall()}
    if "registered_at" not in existing:
        conn.execute("ALTER TABLE admin_users ADD COLUMN registered_at TEXT")
    conn.execute(
        """
        UPDATE admin_users
        SET registered_at = COALESCE(registered_at, created_at, datetime('now', 'localtime'))
        WHERE registered_at IS NULL
          AND (
            username = 'wangting'
            OR role = 'admin'
            OR password_hash IS NOT NULL
          )
        """
    )
    conn.executescript(
        """
        CREATE INDEX IF NOT EXISTS idx_admin_users_phone ON admin_users(phone);
        CREATE INDEX IF NOT EXISTS idx_admin_users_registered_at ON admin_users(registered_at);
        """
    )
