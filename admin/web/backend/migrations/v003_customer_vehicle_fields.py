from __future__ import annotations

import sqlite3


def upgrade(conn: sqlite3.Connection) -> None:
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

    conn.executescript(
        """
        CREATE INDEX IF NOT EXISTS idx_customers_plate_no ON customers(plate_no);
        CREATE INDEX IF NOT EXISTS idx_customers_vin ON customers(vin);
        """
    )
