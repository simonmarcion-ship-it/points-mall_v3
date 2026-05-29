from __future__ import annotations

import sqlite3


def upgrade(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        UPDATE admin_users
        SET enabled = 0,
            registered_at = NULL,
            last_login_at = NULL,
            deleted_at = COALESCE(deleted_at, datetime('now', 'localtime'))
        WHERE username = 'wangting'
          AND role = 'admin'
          AND deleted_at IS NULL
        """
    )
