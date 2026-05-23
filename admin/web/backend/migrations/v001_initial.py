from __future__ import annotations

import sqlite3


def table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def add_missing_columns(conn: sqlite3.Connection, table: str, columns: dict[str, str]) -> None:
    existing = table_columns(conn, table)
    for column, definition in columns.items():
        if column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def upgrade(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS stores (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            code TEXT,
            enabled INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS admin_users (
            id TEXT PRIMARY KEY,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT,
            display_name TEXT,
            phone TEXT,
            store_id TEXT,
            store_name TEXT,
            role TEXT NOT NULL DEFAULT 'staff',
            enabled INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            last_login_at TEXT,
            FOREIGN KEY(store_id) REFERENCES stores(id)
        );

        CREATE TABLE IF NOT EXISTS customers (
            wid TEXT PRIMARY KEY,
            phone TEXT,
            nickname TEXT,
            gender TEXT,
            birthday TEXT,
            avatar_url TEXT,
            became_customer_at TEXT,
            store_name TEXT,
            channel TEXT,
            member_card TEXT,
            level_name TEXT,
            joined_at TEXT,
            black_user TEXT,
            customer_status TEXT,
            available_point TEXT,
            total_point TEXT,
            frozen_point TEXT,
            available_balance TEXT,
            frozen_balance TEXT,
            total_balance TEXT,
            raw_json TEXT NOT NULL DEFAULT '{}'
        );

        CREATE TABLE IF NOT EXISTS coupon_templates (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            coupon_type TEXT,
            rule_text TEXT,
            enabled INTEGER NOT NULL DEFAULT 1,
            source TEXT NOT NULL DEFAULT 'import'
        );

        CREATE TABLE IF NOT EXISTS coupons (
            code TEXT PRIMARY KEY,
            customer_wid TEXT NOT NULL,
            template_id TEXT,
            template_name TEXT NOT NULL,
            coupon_type TEXT,
            status TEXT NOT NULL,
            status_text TEXT,
            receive_time TEXT,
            used_time TEXT,
            valid_period TEXT,
            valid_start TEXT,
            valid_end TEXT,
            phone TEXT,
            source TEXT NOT NULL,
            remark TEXT,
            usable_store_scope TEXT,
            usable_store_ids TEXT,
            usable_store_names TEXT,
            issued_store_id TEXT,
            issued_store_name TEXT,
            issued_by_user_id TEXT,
            issued_by_name TEXT,
            issued_at TEXT,
            redeemed_store_id TEXT,
            redeemed_store_name TEXT,
            redeemed_by_user_id TEXT,
            redeemed_by_name TEXT,
            redeemed_at TEXT,
            raw_json TEXT NOT NULL DEFAULT '{}',
            FOREIGN KEY(customer_wid) REFERENCES customers(wid) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS operation_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            operator TEXT NOT NULL,
            action TEXT NOT NULL,
            customer_wid TEXT,
            target TEXT,
            quantity INTEGER NOT NULL DEFAULT 1,
            remark TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_customers_phone ON customers(phone);
        CREATE INDEX IF NOT EXISTS idx_customers_nickname ON customers(nickname);
        CREATE INDEX IF NOT EXISTS idx_coupons_customer ON coupons(customer_wid);
        CREATE INDEX IF NOT EXISTS idx_coupons_status ON coupons(status);
        CREATE INDEX IF NOT EXISTS idx_admin_users_username ON admin_users(username);
        CREATE INDEX IF NOT EXISTS idx_admin_users_store ON admin_users(store_id);
        CREATE INDEX IF NOT EXISTS idx_coupons_usable_store_scope ON coupons(usable_store_scope);
        CREATE INDEX IF NOT EXISTS idx_coupons_issued_store ON coupons(issued_store_id);
        CREATE INDEX IF NOT EXISTS idx_coupons_redeemed_store ON coupons(redeemed_store_id);
        """
    )

    add_missing_columns(
        conn,
        "stores",
        {"customer_count": "INTEGER NOT NULL DEFAULT 0"},
    )
    add_missing_columns(
        conn,
        "coupons",
        {
            "usable_store_scope": "TEXT",
            "usable_store_ids": "TEXT",
            "usable_store_names": "TEXT",
            "issued_store_id": "TEXT",
            "issued_store_name": "TEXT",
            "issued_by_user_id": "TEXT",
            "issued_by_name": "TEXT",
            "issued_at": "TEXT",
            "redeemed_store_id": "TEXT",
            "redeemed_store_name": "TEXT",
            "redeemed_by_user_id": "TEXT",
            "redeemed_by_name": "TEXT",
            "redeemed_at": "TEXT",
        },
    )
