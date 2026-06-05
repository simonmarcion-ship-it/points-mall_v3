from __future__ import annotations

from dataclasses import dataclass
import importlib
import sqlite3


@dataclass(frozen=True)
class Migration:
    version: str
    module: str


MIGRATIONS = [
    Migration("001", "backend.migrations.v001_initial"),
    Migration("002", "backend.migrations.v002_wechat_bindings"),
    Migration("003", "backend.migrations.v003_customer_vehicle_fields"),
    Migration("004", "backend.migrations.v004_coupon_void_fields"),
    Migration("005", "backend.migrations.v005_admin_roles"),
    Migration("006", "backend.migrations.v006_admin_user_registration"),
    Migration("007", "backend.migrations.v007_admin_user_soft_delete"),
    Migration("008", "backend.migrations.v008_remove_legacy_wangting_admin"),
    Migration("009", "backend.migrations.v009_admin_user_stores"),
    Migration("010", "backend.migrations.v010_admin_renewal_coupon_permission"),
]


def ensure_migration_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version TEXT PRIMARY KEY,
            applied_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
        )
        """
    )


def applied_versions(conn: sqlite3.Connection) -> set[str]:
    ensure_migration_table(conn)
    rows = conn.execute("SELECT version FROM schema_migrations").fetchall()
    return {row[0] for row in rows}


def run_migrations(conn: sqlite3.Connection) -> list[str]:
    ensure_migration_table(conn)
    applied = applied_versions(conn)
    executed: list[str] = []
    for migration in MIGRATIONS:
        if migration.version in applied:
            continue
        module = importlib.import_module(migration.module)
        module.upgrade(conn)
        conn.execute(
            "INSERT INTO schema_migrations (version) VALUES (?)",
            (migration.version,),
        )
        executed.append(migration.version)
    return executed
