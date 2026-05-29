from __future__ import annotations

import sqlite3


def upgrade(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS admin_user_stores (
            id TEXT PRIMARY KEY,
            admin_user_id TEXT NOT NULL,
            store_id TEXT NOT NULL,
            store_name TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            UNIQUE(admin_user_id, store_id)
        )
        """
    )
    conn.execute(
        """
        INSERT OR IGNORE INTO admin_user_stores (id, admin_user_id, store_id, store_name)
        SELECT 'AUS_' || id || '_' || store_id, id, store_id, COALESCE(NULLIF(store_name, ''), store_id)
        FROM admin_users
        WHERE COALESCE(store_id, '') != ''
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_admin_user_stores_user ON admin_user_stores(admin_user_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_admin_user_stores_store ON admin_user_stores(store_id)")
