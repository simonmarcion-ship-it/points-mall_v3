from __future__ import annotations

from datetime import datetime
import os
import shutil

os.environ.setdefault("MALL_DATA_DIR", r"D:\weimeng_customerinfo\web\data")
os.environ.setdefault("MALL_DB_PATH", r"D:\weimeng_customerinfo\web\data\mall.db")
os.environ.setdefault("MALL_CRAWLER_V2_OUTPUT_DIR", r"D:\weimeng_customerinfo\crawler_v2\output")

from backend.database import DB_PATH, DATA_DIR, db_session
from backend.importer import initialize_database


def backup_existing_database() -> None:
    if not DB_PATH.exists():
        return
    backup_dir = DATA_DIR / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = backup_dir / f"mall_{timestamp}.db"
    shutil.copy2(DB_PATH, backup_path)
    print(f"已备份当前数据库: {backup_path}")


def refresh_database() -> None:
    backup_existing_database()
    if DB_PATH.exists():
        DB_PATH.unlink()
        print(f"已删除旧开发数据库: {DB_PATH}")

    with db_session() as conn:
        result = initialize_database(conn)

    print("数据库刷新完成")
    print(f"客户数: {result['customers']}")
    print(f"门店数: {result.get('stores', 0)}")
    print(f"券模板数: {result['templates']}")
    print(f"优惠券数: {result['coupons']}")
    print(f"数据库路径: {DB_PATH}")


if __name__ == "__main__":
    refresh_database()
