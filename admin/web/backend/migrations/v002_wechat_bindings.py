from __future__ import annotations

import sqlite3


def upgrade(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS wechat_bindings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            openid TEXT NOT NULL,
            unionid TEXT,
            customer_wid TEXT NOT NULL,
            phone TEXT,
            nickname TEXT,
            avatar_url TEXT,
            bound_at TEXT NOT NULL,
            last_login_at TEXT,
            UNIQUE(openid),
            UNIQUE(unionid)
        );

        CREATE INDEX IF NOT EXISTS idx_wechat_bindings_customer
        ON wechat_bindings(customer_wid);

        CREATE INDEX IF NOT EXISTS idx_wechat_bindings_phone
        ON wechat_bindings(phone);
        """
    )
