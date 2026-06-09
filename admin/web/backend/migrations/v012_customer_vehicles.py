from __future__ import annotations

import secrets
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo


APP_TZ = ZoneInfo("Asia/Shanghai")


def now_text() -> str:
    return datetime.now(APP_TZ).strftime("%Y-%m-%d %H:%M:%S")


def vehicle_id() -> str:
    return f"VEH_{datetime.now(APP_TZ):%Y%m%d%H%M%S}_{secrets.token_hex(4).upper()}"


def upgrade(conn: sqlite3.Connection) -> None:
    conn.execute(
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
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_customer_vehicles_customer_wid ON customer_vehicles(customer_wid)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_customer_vehicles_vin ON customer_vehicles(vin)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_customer_vehicles_plate_no ON customer_vehicles(plate_no)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_customer_vehicles_deleted_at ON customer_vehicles(deleted_at)")
    coupon_columns = {row[1] for row in conn.execute("PRAGMA table_info(coupons)").fetchall()}
    if "vehicle_id" not in coupon_columns:
        conn.execute("ALTER TABLE coupons ADD COLUMN vehicle_id TEXT")
    if "vin_snapshot" not in coupon_columns:
        conn.execute("ALTER TABLE coupons ADD COLUMN vin_snapshot TEXT")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_coupons_vehicle_id ON coupons(vehicle_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_coupons_vin_snapshot ON coupons(vin_snapshot)")

    if conn.execute("SELECT COUNT(*) FROM customer_vehicles").fetchone()[0]:
        return

    created_at = now_text()
    rows = conn.execute(
        """
        SELECT wid, phone, vin, plate_no, car_series, purchase_store_name
        FROM customers
        WHERE deleted_at IS NULL
          AND (
            COALESCE(TRIM(vin), '') != ''
            OR COALESCE(TRIM(plate_no), '') != ''
            OR COALESCE(TRIM(car_series), '') != ''
            OR COALESCE(TRIM(purchase_store_name), '') != ''
          )
        ORDER BY wid
        """
    ).fetchall()
    for row in rows:
        conn.execute(
            """
            INSERT INTO customer_vehicles (
                id, customer_wid, phone_snapshot, vin, plate_no, car_series,
                purchase_store_name, is_primary, sort_order, source, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 1, 1, 'legacy_customers', ?, ?)
            """,
            (
                vehicle_id(),
                row["wid"],
                (row["phone"] or "").strip(),
                (row["vin"] or "").strip().upper(),
                (row["plate_no"] or "").strip(),
                (row["car_series"] or "").strip(),
                (row["purchase_store_name"] or "").strip(),
                created_at,
                created_at,
            ),
        )
