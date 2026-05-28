from __future__ import annotations

import sqlite3

from backend.auth import hash_password


def upgrade(conn: sqlite3.Connection) -> None:
    conn.execute("UPDATE admin_users SET role = 'issuer' WHERE role = 'staff'")
    conn.execute(
        """
        INSERT INTO admin_users (
            id, username, password_hash, display_name, phone, store_id, store_name,
            role, enabled, created_at, last_login_at
        )
        VALUES (
            'ADMIN_USER_WANGTING', 'wangting', ?, 'wangting', '',
            NULL, '', 'admin', 1, datetime('now', 'localtime'), NULL
        )
        ON CONFLICT(username) DO UPDATE SET
            password_hash = excluded.password_hash,
            display_name = excluded.display_name,
            role = 'admin',
            enabled = 1
        """,
        (hash_password("12345"),),
    )
