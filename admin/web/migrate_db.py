from __future__ import annotations

import os

os.environ.setdefault("MALL_DATA_DIR", r"D:\weimeng_customerinfo\web\data")
os.environ.setdefault("MALL_DB_PATH", r"D:\weimeng_customerinfo\web\data\mall.db")
os.environ.setdefault("MALL_CRAWLER_V2_OUTPUT_DIR", r"D:\weimeng_customerinfo\crawler_v2\output")

from backend.database import DB_PATH, db_session
from backend.schema import create_schema


def migrate_database() -> None:
    with db_session() as conn:
        create_schema(conn)
        rows = conn.execute(
            "SELECT version, applied_at FROM schema_migrations ORDER BY version"
        ).fetchall()

    print("数据库迁移完成")
    print(f"数据库路径: {DB_PATH}")
    print("已应用版本:")
    for row in rows:
        print(f"- {row['version']} at {row['applied_at']}")


if __name__ == "__main__":
    migrate_database()
