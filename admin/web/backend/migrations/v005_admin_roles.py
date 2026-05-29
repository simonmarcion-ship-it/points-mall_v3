from __future__ import annotations

import sqlite3


def upgrade(conn: sqlite3.Connection) -> None:
    conn.execute("UPDATE admin_users SET role = 'issuer' WHERE role = 'staff'")
