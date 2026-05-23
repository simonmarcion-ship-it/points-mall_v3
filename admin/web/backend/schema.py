from __future__ import annotations

import sqlite3

from .migrations.runner import run_migrations


def create_schema(conn: sqlite3.Connection) -> None:
    run_migrations(conn)
