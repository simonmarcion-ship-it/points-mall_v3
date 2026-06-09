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
    coupon_columns = {row[1] for row in conn.execute("PRAGMA table_info(coupons)").fetchall()}
    if "vehicle_id" not in coupon_columns:
        conn.execute("ALTER TABLE coupons ADD COLUMN vehicle_id TEXT")
    if "vin_snapshot" not in coupon_columns:
        conn.execute("ALTER TABLE coupons ADD COLUMN vin_snapshot TEXT")

    created_at = now_text()
    rows = conn.execute(
        """
        SELECT c.wid, c.phone
        FROM customers c
        WHERE c.deleted_at IS NULL
          AND EXISTS (
            SELECT 1
            FROM coupons cp
            WHERE cp.customer_wid = c.wid
              AND COALESCE(cp.vehicle_id, '') = ''
          )
          AND NOT EXISTS (
            SELECT 1
            FROM customer_vehicles v
            WHERE v.customer_wid = c.wid
              AND v.deleted_at IS NULL
          )
        """
    ).fetchall()
    for row in rows:
        conn.execute(
            """
            INSERT INTO customer_vehicles (
                id, customer_wid, phone_snapshot, vin, plate_no, car_series,
                purchase_store_name, is_primary, sort_order, source, created_at, updated_at
            ) VALUES (?, ?, ?, '', '', '', '', 1, 1, 'legacy_coupon_placeholder', ?, ?)
            """,
            (vehicle_id(), row["wid"], (row["phone"] or "").strip(), created_at, created_at),
        )

    conn.execute(
        """
        UPDATE coupons
        SET
            vehicle_id = (
                SELECT v.id
                FROM customer_vehicles v
                WHERE v.customer_wid = coupons.customer_wid
                  AND v.deleted_at IS NULL
                ORDER BY v.is_primary DESC, v.sort_order ASC, v.created_at ASC, v.id ASC
                LIMIT 1
            ),
            vin_snapshot = COALESCE(NULLIF(vin_snapshot, ''), (
                SELECT v.vin
                FROM customer_vehicles v
                WHERE v.customer_wid = coupons.customer_wid
                  AND v.deleted_at IS NULL
                ORDER BY v.is_primary DESC, v.sort_order ASC, v.created_at ASC, v.id ASC
                LIMIT 1
            ))
        WHERE COALESCE(vehicle_id, '') = ''
          AND EXISTS (
              SELECT 1
              FROM customer_vehicles v
              WHERE v.customer_wid = coupons.customer_wid
                AND v.deleted_at IS NULL
          )
        """
    )

    conn.execute("CREATE INDEX IF NOT EXISTS idx_coupons_vehicle_id ON coupons(vehicle_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_coupons_vin_snapshot ON coupons(vin_snapshot)")
