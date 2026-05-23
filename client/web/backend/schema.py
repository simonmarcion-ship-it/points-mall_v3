from __future__ import annotations

import sqlite3


def create_client_schema(conn: sqlite3.Connection) -> None:
    try:
        from backend.migrations.runner import run_migrations

        run_migrations(conn)
        ensure_customer_vehicle_columns(conn)
        return
    except Exception:
        pass

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
    ensure_customer_vehicle_columns(conn)


def ensure_customer_vehicle_columns(conn: sqlite3.Connection) -> None:
    table = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'customers'"
    ).fetchone()
    if not table:
        return

    existing = {row[1] for row in conn.execute("PRAGMA table_info(customers)").fetchall()}
    columns = {
        "real_name": "TEXT",
        "car_series": "TEXT",
        "vin": "TEXT",
        "purchase_store_name": "TEXT",
        "plate_no": "TEXT",
        "vehicle_query_success": "TEXT",
        "vehicle_errcode": "TEXT",
        "vehicle_errmsg": "TEXT",
    }
    for column, column_type in columns.items():
        if column not in existing:
            conn.execute(f"ALTER TABLE customers ADD COLUMN {column} {column_type}")
