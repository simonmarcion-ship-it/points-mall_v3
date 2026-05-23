from __future__ import annotations

from datetime import datetime
import hashlib
from pathlib import Path
import re
from typing import Any
import secrets
import sqlite3

import pandas as pd

from .auth import hash_password
from .config import CRAWLER_V2_OUTPUT_DIR
from .database import CRAWLER_DIR
from .schema import create_schema


CUSTOMER_DETAIL_EXCEL = CRAWLER_DIR / "微盟客户详情_解析结果.xlsx"
CUSTOMER_DETAIL_JOBLIB_EXCEL = CRAWLER_DIR / "微盟客户详情_解析结果_Joblib.xlsx"
CUSTOMER_LIST_EXCEL = CRAWLER_DIR / "微盟客户数据_全部13776条.xlsx"
COUPON_EXCEL = CRAWLER_DIR / "微盟客户优惠券明细_解析结果.xlsx"
COUPON_JOBLIB_EXCEL = CRAWLER_DIR / "微盟客户优惠券明细_解析结果_Joblib.xlsx"
CUSTOMER_DETAIL_V2_EXCEL = CRAWLER_V2_OUTPUT_DIR / "微盟客户详情_解析结果.xlsx"
COUPON_V2_EXCEL = CRAWLER_V2_OUTPUT_DIR / "微盟客户优惠券明细_解析结果.xlsx"


def clean_value(value: Any) -> Any:
    if pd.isna(value):
        return None
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    return str(value) if not isinstance(value, str) else value


def read_excel_records(path: Path) -> list[dict[str, Any]]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    df = pd.read_excel(path, dtype=str)
    return [
        {str(key): clean_value(value) for key, value in row.items()}
        for row in df.to_dict("records")
    ]


def first_existing_excel(*paths: Path) -> Path | None:
    for path in paths:
        if path.exists() and path.stat().st_size > 0:
            return path
    return None


def read_first_excel_records(*paths: Path) -> list[dict[str, Any]]:
    path = first_existing_excel(*paths)
    if path is None:
        return []
    print(f"导入数据源: {path}")
    return read_excel_records(path)


def normalize_coupon_status(row: dict[str, Any]) -> tuple[str, str]:
    status_desc = str(row.get("状态描述") or row.get("状态") or "").strip()
    used_time = row.get("使用时间")
    if used_time or "已使用" in status_desc or status_desc == "使用":
        return "used", status_desc or "已核销"
    if "过期" in status_desc:
        return "expired", status_desc
    if "作废" in status_desc:
        return "voided", status_desc
    return "unused", status_desc or "未使用"


def database_has_customers(conn: sqlite3.Connection) -> bool:
    row = conn.execute("SELECT COUNT(*) AS count FROM customers").fetchone()
    return bool(row and row["count"])


def store_id_for(name: str) -> str:
    slug = re.sub(r"[^0-9A-Za-z]+", "_", name).strip("_").lower()
    digest = hashlib.sha1(name.encode("utf-8")).hexdigest()[:10]
    return f"store_{slug}_{digest}" if slug else f"store_{digest}"


def sync_inferred_stores(conn: sqlite3.Connection) -> int:
    rows = conn.execute(
        """
        SELECT TRIM(store_name) AS name, COUNT(*) AS customer_count
        FROM customers
        WHERE store_name IS NOT NULL AND TRIM(store_name) != ''
        GROUP BY TRIM(store_name)
        ORDER BY customer_count DESC, name
        """
    ).fetchall()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    count = 0
    for row in rows:
        name = row["name"]
        customer_count = row["customer_count"]
        existing = conn.execute("SELECT id FROM stores WHERE name = ?", (name,)).fetchone()
        if existing:
            conn.execute(
                "UPDATE stores SET enabled = 1, customer_count = ? WHERE id = ?",
                (customer_count, existing["id"]),
            )
        else:
            conn.execute(
                """
                INSERT INTO stores (id, name, code, enabled, created_at, customer_count)
                VALUES (?, ?, ?, 1, ?, ?)
                """,
                (store_id_for(name), name, "", now, customer_count),
            )
        count += 1
    return count


def ensure_default_admin_users(conn: sqlite3.Connection) -> None:
    store = conn.execute(
        """
        SELECT id, name
        FROM stores
        WHERE name = ?
        ORDER BY customer_count DESC, name
        LIMIT 1
        """,
        ("西安航星4S店-比亚迪王朝网",),
    ).fetchone()
    if not store:
        store = conn.execute(
            """
            SELECT id, name
            FROM stores
            WHERE name LIKE ?
            ORDER BY customer_count DESC, name
            LIMIT 1
            """,
            ("%西安航星%",),
        ).fetchone()
    if not store:
        store = conn.execute("SELECT id, name FROM stores ORDER BY customer_count DESC, name LIMIT 1").fetchone()

    store_id = store["id"] if store else ""
    store_name = store["name"] if store else ""
    conn.execute(
        """
        INSERT INTO admin_users (
            id, username, password_hash, display_name, phone,
            store_id, store_name, role, enabled, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
        ON CONFLICT(username) DO UPDATE SET
            display_name = excluded.display_name,
            store_id = excluded.store_id,
            store_name = excluded.store_name,
            role = excluded.role,
            enabled = 1
        """,
        (
            "user_maohongli",
            "maohongli",
            hash_password("123456"),
            "毛红丽",
            "",
            store_id,
            store_name,
            "staff",
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        ),
    )


def import_customers(conn: sqlite3.Connection) -> int:
    rows = read_first_excel_records(
        CUSTOMER_DETAIL_V2_EXCEL,
        CUSTOMER_DETAIL_JOBLIB_EXCEL,
        CUSTOMER_DETAIL_EXCEL,
    )
    if not rows:
        raise RuntimeError(
            "没有找到客户详情解析结果，请先运行 crawler_v2 fetch-details，"
            f"期望文件: {CUSTOMER_DETAIL_V2_EXCEL}"
        )

    count = 0
    for row in rows:
        wid = str(row.get("客户编号 wid") or "").strip()
        if not wid:
            continue
        conn.execute(
            """
            INSERT OR REPLACE INTO customers (
                wid, phone, nickname, gender, birthday, avatar_url, became_customer_at,
                store_name, channel, member_card, level_name, joined_at, black_user,
                customer_status, available_point, total_point, frozen_point,
                available_balance, frozen_balance, total_balance,
                real_name, car_series, vin, purchase_store_name, plate_no,
                vehicle_query_success, vehicle_errcode, vehicle_errmsg,
                raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                wid,
                row.get("手机号"),
                row.get("昵称"),
                row.get("性别"),
                row.get("生日"),
                row.get("头像 URL"),
                row.get("成为客户时间"),
                row.get("归属门店"),
                row.get("客户渠道") or row.get("首次来源渠道"),
                row.get("会员卡"),
                row.get("等级名称"),
                row.get("入会时间"),
                row.get("是否黑名单"),
                row.get("客户状态"),
                row.get("可用积分"),
                row.get("累计积分"),
                row.get("冻结积分"),
                row.get("可用余额"),
                row.get("冻结余额"),
                row.get("累计余额"),
                row.get("姓名"),
                row.get("车型车系"),
                row.get("车架号"),
                row.get("购买门店"),
                row.get("车牌号"),
                row.get("车辆信息查询成功"),
                row.get("车辆信息errcode"),
                row.get("车辆信息errmsg"),
                str(row),
            ),
        )
        count += 1
    return count


def import_templates_and_coupons(conn: sqlite3.Connection) -> tuple[int, int]:
    coupon_rows = read_first_excel_records(COUPON_V2_EXCEL, COUPON_JOBLIB_EXCEL, COUPON_EXCEL)
    templates: dict[str, dict[str, Any]] = {}
    coupon_count = 0

    for row in coupon_rows:
        wid = str(row.get("客户编号 wid") or "").strip()
        if not wid:
            continue
        exists = conn.execute("SELECT 1 FROM customers WHERE wid = ?", (wid,)).fetchone()
        if not exists:
            continue

        template_id = str(row.get("券模板ID") or "manual_import").strip()
        templates.setdefault(
            template_id,
            {
                "name": row.get("券名称") or "未命名优惠券",
                "coupon_type": row.get("券类型描述") or row.get("券类型"),
                "rule_text": row.get("使用规则") or row.get("优惠说明"),
            },
        )

        status, status_text = normalize_coupon_status(row)
        code = str(row.get("券码") or "").strip() or f"NO_CODE_{secrets.token_hex(8)}"
        conn.execute(
            """
            INSERT OR REPLACE INTO coupons (
                code, customer_wid, template_id, template_name, coupon_type, status,
                status_text, receive_time, used_time, valid_period, valid_start,
                valid_end, phone, source, remark, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                code,
                wid,
                template_id,
                row.get("券名称") or "未命名优惠券",
                row.get("券类型描述") or row.get("券类型"),
                status,
                status_text,
                row.get("领取时间"),
                row.get("使用时间"),
                row.get("有效期"),
                row.get("有效开始时间戳"),
                row.get("有效结束时间戳"),
                row.get("领取手机号"),
                "old_mall",
                row.get("优惠说明"),
                str(row),
            ),
        )
        coupon_count += 1

    if not templates:
        templates["manual_cash_10"] = {
            "name": "手工补发券",
            "coupon_type": "通用券",
            "rule_text": "线下人工确认后使用",
        }

    for template_id, row in templates.items():
        conn.execute(
            """
            INSERT OR IGNORE INTO coupon_templates (id, name, coupon_type, rule_text, enabled, source)
            VALUES (?, ?, ?, ?, 1, 'import')
            """,
            (template_id, row["name"], row.get("coupon_type"), row.get("rule_text")),
        )
    return len(templates), coupon_count


def initialize_database(conn: sqlite3.Connection) -> dict[str, int]:
    create_schema(conn)
    if database_has_customers(conn):
        sync_inferred_stores(conn)
        ensure_default_admin_users(conn)
        return {"customers": 0, "templates": 0, "coupons": 0}
    customers = import_customers(conn)
    stores = sync_inferred_stores(conn)
    ensure_default_admin_users(conn)
    templates, coupons = import_templates_and_coupons(conn)
    conn.execute(
        """
        INSERT INTO operation_logs (created_at, operator, action, customer_wid, target, quantity, remark)
        VALUES (?, '系统', '导入', NULL, '旧商城Excel', ?, '数据库首次初始化')
        """,
        (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), customers),
    )
    return {"customers": customers, "stores": stores, "templates": templates, "coupons": coupons}
