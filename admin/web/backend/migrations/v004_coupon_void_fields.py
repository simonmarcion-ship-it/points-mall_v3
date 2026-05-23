from __future__ import annotations

import sqlite3


def upgrade(conn: sqlite3.Connection) -> None:
    existing = {row[1] for row in conn.execute("PRAGMA table_info(coupons)").fetchall()}
    columns = {
        "voided_by_user_id": "TEXT",
        "voided_by_name": "TEXT",
        "voided_at": "TEXT",
        "void_reason": "TEXT",
    }
    for column, column_type in columns.items():
        if column not in existing:
            conn.execute(f"ALTER TABLE coupons ADD COLUMN {column} {column_type}")

    conn.executescript(
        """
        CREATE INDEX IF NOT EXISTS idx_coupons_voided_at ON coupons(voided_at);
        """
    )
