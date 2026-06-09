from __future__ import annotations

import sqlite3


def create_client_schema(conn: sqlite3.Connection) -> None:
    try:
        from backend.migrations.runner import run_migrations

        run_migrations(conn)
        ensure_customer_vehicle_columns(conn)
        ensure_customer_vehicles_table(conn)
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
    ensure_customer_vehicles_table(conn)


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


def ensure_customer_vehicles_table(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS customer_vehicles (
            id TEXT PRIMARY KEY,
            customer_wid TEXT NOT NULL,
            phone_snapshot TEXT,
            vin TEXT,
            plate_no TEXT,
            car_series TEXT,
            purchase_store_name TEXT,
            is_primary INTEGER NOT NULL DEFAULT 0,
            sort_order INTEGER NOT NULL DEFAULT 1,
            source TEXT,
            raw_json TEXT,
            created_at TEXT,
            updated_at TEXT,
            deleted_at TEXT,
            deleted_by TEXT,
            deleted_reason TEXT,
            FOREIGN KEY(customer_wid) REFERENCES customers(wid) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_customer_vehicles_customer_wid ON customer_vehicles(customer_wid);
        CREATE INDEX IF NOT EXISTS idx_customer_vehicles_vin ON customer_vehicles(vin);
        CREATE INDEX IF NOT EXISTS idx_customer_vehicles_plate_no ON customer_vehicles(plate_no);
        CREATE INDEX IF NOT EXISTS idx_customer_vehicles_deleted_at ON customer_vehicles(deleted_at);
        """
    )
    coupon_table = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'coupons'"
    ).fetchone()
    if coupon_table:
        existing = {row[1] for row in conn.execute("PRAGMA table_info(coupons)").fetchall()}
        if "vehicle_id" not in existing:
            conn.execute("ALTER TABLE coupons ADD COLUMN vehicle_id TEXT")
        if "vin_snapshot" not in existing:
            conn.execute("ALTER TABLE coupons ADD COLUMN vin_snapshot TEXT")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_coupons_vehicle_id ON coupons(vehicle_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_coupons_vin_snapshot ON coupons(vin_snapshot)")
