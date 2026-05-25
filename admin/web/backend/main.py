from __future__ import annotations

import asyncio
from contextlib import suppress
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
import re
import secrets

from fastapi import FastAPI, HTTPException
from fastapi import Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .auth import authenticate, clear_session_cookie, current_username, hash_password, require_login, set_session_cookie, verify_password
from .cargeer import lookup_cargeer_options_by_phone
from .config import ADMIN_REGISTER_INVITE_CODE, AUTO_IMPORT, DB_PATH, WEB_DIR
from .database import db_session, row_to_dict, rows_to_dicts
from .schema import create_schema


FRONTEND_DIR = WEB_DIR / "frontend"

app = FastAPI(title="积分商城后台 API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

expiry_task: asyncio.Task | None = None


class IssueCouponRequest(BaseModel):
    wid: str
    template_id: str
    quantity: int = 1
    valid_days: int = 30
    operator: str = "员工"
    remark: str = ""
    usable_store_scope: str = "all"
    usable_store_ids: list[str] = []
    usable_store_names: list[str] = []


class RedeemCouponRequest(BaseModel):
    code: str
    operator: str = "员工"
    remark: str = ""


class VoidCouponRequest(BaseModel):
    code: str
    operator: str = "员工"
    remark: str = ""


class LoginRequest(BaseModel):
    username: str
    password: str


class RegisterAdminRequest(BaseModel):
    phone: str
    name: str
    store_id: str
    password: str
    invite_code: str


class CreateCustomerRequest(BaseModel):
    phone: str
    nickname: str = ""
    store_name: str = ""
    level_name: str = ""
    birthday: str = ""
    gender: str = ""
    real_name: str = ""
    car_series: str = ""
    vin: str = ""
    purchase_store_name: str = ""
    plate_no: str = ""
    remark: str = ""


class CreateTemplateRequest(BaseModel):
    name: str
    coupon_type: str = "通用券"
    rule_text: str = ""


class CreateStoreRequest(BaseModel):
    name: str
    code: str = ""


class UpdateStoreRequest(BaseModel):
    enabled: bool | None = None


class ClientLookupRequest(BaseModel):
    phone: str


@app.on_event("startup")
def startup() -> None:
    with db_session() as conn:
        if AUTO_IMPORT:
            from .importer import initialize_database

            initialize_database(conn)
        else:
            create_schema(conn)


@app.on_event("startup")
async def startup_coupon_expiry_task() -> None:
    global expiry_task
    expire_coupons_once()
    expiry_task = asyncio.create_task(coupon_expiry_loop())


@app.on_event("shutdown")
async def shutdown_coupon_expiry_task() -> None:
    if expiry_task:
        expiry_task.cancel()
        with suppress(asyncio.CancelledError):
            await expiry_task


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def local_id(prefix: str) -> str:
    return f"{prefix}_{datetime.now():%Y%m%d%H%M%S}_{secrets.token_hex(3).upper()}"


VIN_PATTERN = re.compile(r"^[A-HJ-NPR-Z0-9]{17}$")


def normalize_vin(value: str) -> str:
    return re.sub(r"\s+", "", value or "").upper()


def validate_new_customer_vin(conn, vin: str) -> str:
    normalized = normalize_vin(vin)
    if not normalized:
        return ""
    if not VIN_PATTERN.fullmatch(normalized):
        raise HTTPException(status_code=400, detail="车架号格式不正确：应为 17 位 VIN，且不能包含 I、O、Q")

    existing = row_to_dict(
        conn.execute(
            """
            SELECT wid, phone, nickname, real_name, vin
            FROM customers
            WHERE UPPER(REPLACE(REPLACE(REPLACE(TRIM(COALESCE(vin, '')), ' ', ''), char(9), ''), char(12288), '')) = ?
            LIMIT 1
            """,
            (normalized,),
        ).fetchone()
    )
    if existing:
        name = existing.get("real_name") or existing.get("nickname") or "-"
        raise HTTPException(
            status_code=400,
            detail=f"车架号已存在：{normalized}，客户 {name}，手机号 {existing.get('phone') or '-'}，WID {existing.get('wid')}",
        )
    return normalized


def current_admin_profile(conn, username: str) -> dict:
    user = row_to_dict(
        conn.execute(
            """
            SELECT u.id, u.username, u.display_name, u.store_id, u.store_name, u.role,
                   s.name AS linked_store_name
            FROM admin_users u
            LEFT JOIN stores s ON s.id = u.store_id
            WHERE u.username = ? AND u.enabled = 1
            """,
            (username,),
        ).fetchone()
    )
    if user:
        return {
            "user_id": user.get("id") or user.get("username"),
            "name": user.get("display_name") or user.get("username"),
            "store_id": user.get("store_id"),
            "store_name": user.get("store_name") or user.get("linked_store_name"),
            "role": user.get("role") or "staff",
        }
    return {
        "user_id": username,
        "name": username,
        "store_id": None,
        "store_name": None,
        "role": "admin",
    }


def join_text(values: list[str]) -> str:
    return ",".join(str(value).strip() for value in values if str(value).strip())


def store_id_for(name: str) -> str:
    slug = re.sub(r"[^0-9A-Za-z]+", "_", name).strip("_").lower()
    digest = hashlib.sha1(name.encode("utf-8")).hexdigest()[:10]
    return f"store_{slug}_{digest}" if slug else f"store_{digest}"


def ensure_store(conn, name: str) -> None:
    store_name = name.strip()
    if not store_name:
        return
    customer_count = conn.execute(
        "SELECT COUNT(*) FROM customers WHERE TRIM(store_name) = ?",
        (store_name,),
    ).fetchone()[0]
    existing = conn.execute("SELECT id FROM stores WHERE name = ?", (store_name,)).fetchone()
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
            (store_id_for(store_name), store_name, "", now_text(), customer_count),
        )


def usable_store_rows(conn) -> list[dict]:
    return rows_to_dicts(
        conn.execute(
            """
            SELECT id, name, customer_count
            FROM stores
            WHERE enabled = 1
            ORDER BY customer_count DESC, name
            """
        ).fetchall()
    )


def all_store_rows(conn) -> list[dict]:
    return rows_to_dicts(
        conn.execute(
            """
            SELECT id, name, code, enabled, created_at, customer_count
            FROM stores
            ORDER BY enabled DESC, customer_count DESC, name
            """
        ).fetchall()
    )


def require_enabled_store(conn, store_name: str) -> str:
    name = store_name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="请选择客户归属门店")
    row = conn.execute(
        "SELECT name FROM stores WHERE name = ? AND enabled = 1",
        (name,),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=400, detail="客户归属门店不在门店总表中，或已停用")
    return row["name"]


STORE_MATCH_REMOVALS = (
    "汽车销售服务有限公司",
    "汽车销售有限公司",
    "销售服务有限公司",
    "汽车服务有限公司",
    "有限公司",
    "4S店",
    "比亚迪王朝网",
    "比亚迪海洋网",
    "王朝网",
    "海洋网",
    "腾势中心",
)


def store_match_key(name: str | None) -> str:
    text = re.sub(r"\s+", "", name or "")
    for token in STORE_MATCH_REMOVALS:
        text = text.replace(token, "")
    return re.sub(r"[\W_]+", "", text, flags=re.UNICODE)


def match_store_name(store_name: str | None, store_rows: list[dict]) -> str:
    source_key = store_match_key(store_name)
    if len(source_key) < 2:
        return ""

    scored: list[tuple[int, str]] = []
    for row in store_rows:
        candidate_name = row.get("name") or ""
        candidate_key = store_match_key(candidate_name)
        if not candidate_key:
            continue
        score = 0
        if candidate_key == source_key:
            score = 100
        elif len(source_key) >= 4 and source_key in candidate_key:
            score = 80
        elif len(candidate_key) >= 4 and candidate_key in source_key:
            score = 70
        if score:
            scored.append((score, candidate_name))

    if not scored:
        return ""
    scored.sort(reverse=True)
    best_score, best_name = scored[0]
    if len(scored) > 1 and scored[1][0] == best_score and scored[1][1] != best_name:
        return ""
    return best_name


def enrich_cargeer_store_matches(conn, items: list[dict]) -> list[dict]:
    store_rows = usable_store_rows(conn)
    enriched = []
    for item in items:
        row = dict(item)
        row["matched_store_name"] = match_store_name(row.get("store_name"), store_rows)
        enriched.append(row)
    return enriched


def parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    normalized = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
        return parsed.replace(tzinfo=None) if parsed.tzinfo else parsed
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def apply_dynamic_coupon_status(coupon: dict) -> dict:
    if not coupon:
        return coupon
    if coupon.get("status") == "unused":
        valid_end = parse_datetime(coupon.get("valid_end"))
        if valid_end and valid_end < datetime.now():
            coupon = dict(coupon)
            coupon["status"] = "expired"
            coupon["status_text"] = "已过期"
    return coupon


def apply_dynamic_coupon_statuses(coupons: list[dict]) -> list[dict]:
    return [apply_dynamic_coupon_status(coupon) for coupon in coupons]


def public_coupon_row(coupon: dict) -> dict:
    coupon = apply_dynamic_coupon_status(coupon)
    return {
        "code": coupon.get("code"),
        "template_name": coupon.get("template_name"),
        "coupon_type": coupon.get("coupon_type"),
        "status": coupon.get("status"),
        "status_text": coupon.get("status_text"),
        "receive_time": coupon.get("receive_time"),
        "used_time": coupon.get("used_time"),
        "valid_period": coupon.get("valid_period"),
        "valid_start": coupon.get("valid_start"),
        "valid_end": coupon.get("valid_end"),
        "remark": coupon.get("remark"),
    }


def expire_coupons_once() -> int:
    with db_session() as conn:
        cursor = conn.execute(
            """
            UPDATE coupons
            SET status = 'expired', status_text = '已过期'
            WHERE status = 'unused'
              AND valid_end IS NOT NULL
              AND valid_end != ''
              AND datetime(valid_end) < datetime('now', 'localtime')
            """
        )
        return cursor.rowcount or 0


def seconds_until_next_expiry_run() -> float:
    now = datetime.now()
    next_run = (now + timedelta(days=1)).replace(hour=0, minute=5, second=0, microsecond=0)
    if now < now.replace(hour=0, minute=5, second=0, microsecond=0):
        next_run = now.replace(hour=0, minute=5, second=0, microsecond=0)
    return max(60.0, (next_run - now).total_seconds())


async def coupon_expiry_loop() -> None:
    while True:
        await asyncio.sleep(seconds_until_next_expiry_run())
        expired_count = expire_coupons_once()
        if expired_count:
            print(f"已自动更新过期券: {expired_count} 张")


def require_customer(conn, wid: str) -> dict:
    row = conn.execute("SELECT * FROM customers WHERE wid = ?", (wid,)).fetchone()
    customer = row_to_dict(row)
    if not customer:
        raise HTTPException(status_code=404, detail="客户不存在")
    return customer


def require_template(conn, template_id: str) -> dict:
    row = conn.execute("SELECT * FROM coupon_templates WHERE id = ? AND enabled = 1", (template_id,)).fetchone()
    template = row_to_dict(row)
    if not template:
        raise HTTPException(status_code=404, detail="券模板不存在或已停用")
    return template


def active_unused_coupon_sql(alias: str = "") -> str:
    prefix = f"{alias}." if alias else ""
    return f"""
        {prefix}status = 'unused'
        AND COALESCE({prefix}status_text, '') IN ('', '未使用', '可用')
        AND ({prefix}valid_end IS NULL OR {prefix}valid_end = '' OR datetime({prefix}valid_end) >= datetime('now', 'localtime'))
    """


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "database": str(DB_PATH)}


@app.get("/api/client/profile")
def client_profile(phone: str) -> dict:
    phone = phone.strip()
    if not phone:
        raise HTTPException(status_code=400, detail="请输入手机号")

    with db_session() as conn:
        customer = row_to_dict(
            conn.execute(
                """
                SELECT wid, phone, nickname, store_name, level_name, member_card,
                       available_point, total_point, customer_status
                FROM customers
                WHERE phone = ?
                ORDER BY became_customer_at DESC, wid DESC
                LIMIT 1
                """,
                (phone,),
            ).fetchone()
        )
        if not customer:
            raise HTTPException(status_code=404, detail="没有找到该手机号的会员")

        coupons = apply_dynamic_coupon_statuses(rows_to_dicts(
            conn.execute(
                """
                SELECT * FROM coupons
                WHERE customer_wid = ?
                ORDER BY
                    CASE status WHEN 'unused' THEN 0 WHEN 'used' THEN 1 ELSE 2 END,
                    receive_time DESC,
                    code DESC
                """,
                (customer["wid"],),
            ).fetchall()
        ))
        return {
            "customer": customer,
            "coupons": [public_coupon_row(coupon) for coupon in coupons],
        }


@app.get("/api/client/coupons/{code}")
def client_coupon_detail(code: str, phone: str) -> dict:
    phone = phone.strip()
    with db_session() as conn:
        row = conn.execute(
            """
            SELECT cp.*, c.phone
            FROM coupons cp
            JOIN customers c ON c.wid = cp.customer_wid
            WHERE cp.code = ? AND c.phone = ?
            """,
            (code.strip(), phone),
        ).fetchone()
        coupon = row_to_dict(row)
        if not coupon:
            raise HTTPException(status_code=404, detail="没有找到该优惠券")
        return {"coupon": public_coupon_row(coupon)}


@app.post("/api/auth/login")
def login(req: LoginRequest, response: Response) -> dict:
    username = req.username.strip()
    with db_session() as conn:
        user = row_to_dict(
            conn.execute(
                """
                SELECT *
                FROM admin_users
                WHERE username = ? AND enabled = 1
                """,
                (username,),
            ).fetchone()
        )
        if user and verify_password(req.password, user.get("password_hash")):
            conn.execute("UPDATE admin_users SET last_login_at = ? WHERE username = ?", (now_text(), username))
            set_session_cookie(response, username)
            return {"username": username, "profile": current_admin_profile(conn, username)}

    if authenticate(username, req.password):
        set_session_cookie(response, username)
        return {"username": username}

    raise HTTPException(status_code=401, detail="用户名或密码错误")


@app.get("/api/auth/register-options")
def register_options() -> dict:
    with db_session() as conn:
        return {"stores": usable_store_rows(conn)}


@app.post("/api/auth/register")
def register_admin(req: RegisterAdminRequest) -> dict:
    phone = re.sub(r"\D+", "", req.phone or "")
    name = req.name.strip()
    password = req.password.strip()
    if req.invite_code.strip() != ADMIN_REGISTER_INVITE_CODE:
        raise HTTPException(status_code=400, detail="邀请码不正确")
    if not re.fullmatch(r"1[3-9]\d{9}", phone):
        raise HTTPException(status_code=400, detail="请输入正确的手机号")
    if not name:
        raise HTTPException(status_code=400, detail="请输入姓名")
    if len(password) < 6:
        raise HTTPException(status_code=400, detail="密码至少 6 位")

    with db_session() as conn:
        store = row_to_dict(
            conn.execute(
                "SELECT id, name FROM stores WHERE id = ? AND enabled = 1",
                (req.store_id.strip(),),
            ).fetchone()
        )
        if not store:
            raise HTTPException(status_code=400, detail="请选择有效门店")
        existing = row_to_dict(
            conn.execute(
                "SELECT id FROM admin_users WHERE username = ? OR phone = ?",
                (phone, phone),
            ).fetchone()
        )
        if existing:
            raise HTTPException(status_code=400, detail="该手机号已注册")

        user_id = local_id("ADMIN_USER")
        while conn.execute("SELECT 1 FROM admin_users WHERE id = ?", (user_id,)).fetchone():
            user_id = local_id("ADMIN_USER")
        conn.execute(
            """
            INSERT INTO admin_users (
                id, username, password_hash, display_name, phone, store_id, store_name,
                role, enabled, created_at, last_login_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'staff', 1, ?, NULL)
            """,
            (
                user_id,
                phone,
                hash_password(password),
                name,
                phone,
                store["id"],
                store["name"],
                now_text(),
            ),
        )
        return {
            "ok": True,
            "username": phone,
            "profile": {
                "user_id": user_id,
                "name": name,
                "store_id": store["id"],
                "store_name": store["name"],
                "role": "staff",
            },
        }


@app.post("/api/auth/logout")
def logout(response: Response) -> dict:
    clear_session_cookie(response)
    return {"ok": True}


@app.get("/api/auth/me")
def me(request: Request) -> dict:
    username = current_username(request)
    if not username:
        raise HTTPException(status_code=401, detail="请先登录")
    with db_session() as conn:
        return {"username": username, "profile": current_admin_profile(conn, username)}


@app.get("/api/summary")
def summary(request: Request) -> dict:
    require_login(request)
    with db_session() as conn:
        def scalar(sql: str) -> int:
            return int(conn.execute(sql).fetchone()[0])

        return {
            "customers": scalar("SELECT COUNT(*) FROM customers"),
            "coupons": scalar("SELECT COUNT(*) FROM coupons"),
            "unused_coupons": scalar(
                f"SELECT COUNT(*) FROM coupons WHERE {active_unused_coupon_sql()}"
            ),
            "used_coupons": scalar("SELECT COUNT(*) FROM coupons WHERE status = 'used'"),
            "templates": scalar("SELECT COUNT(*) FROM coupon_templates WHERE enabled = 1"),
            "logs": scalar("SELECT COUNT(*) FROM operation_logs"),
        }


@app.post("/api/coupons/expire-now")
def expire_coupons_now(request: Request) -> dict:
    require_login(request)
    return {"expired": expire_coupons_once()}


@app.get("/api/customers")
def search_customers(
    request: Request,
    q: str = "",
    store: str = "",
    became_from: str = "",
    became_to: str = "",
    joined_from: str = "",
    joined_to: str = "",
    limit: int = 50,
    offset: int = 0,
) -> dict:
    require_login(request)
    limit = max(1, min(limit, 200))
    offset = max(0, offset)
    keyword = f"%{q.strip()}%"
    where_parts = []
    params: list = []
    if q.strip():
        where_parts.append(
            """
            (
                c.wid LIKE ?
                OR c.phone LIKE ?
                OR c.nickname LIKE ?
                OR c.member_card LIKE ?
                OR c.store_name LIKE ?
                OR c.plate_no LIKE ?
                OR c.vin LIKE ?
                OR c.real_name LIKE ?
            )
            """
        )
        params = [keyword, keyword, keyword, keyword, keyword, keyword, keyword, keyword]
    if store.strip():
        where_parts.append("c.store_name LIKE ?")
        params.append(f"%{store.strip()}%")
    if became_from.strip():
        where_parts.append("c.became_customer_at >= ?")
        params.append(became_from.strip())
    if became_to.strip():
        where_parts.append("c.became_customer_at <= ?")
        params.append(f"{became_to.strip()} 23:59:59")
    if joined_from.strip():
        where_parts.append("c.joined_at >= ?")
        params.append(joined_from.strip())
    if joined_to.strip():
        where_parts.append("c.joined_at <= ?")
        params.append(f"{joined_to.strip()} 23:59:59")

    where = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""

    with db_session() as conn:
        rows = conn.execute(
            f"""
            SELECT
                c.wid, c.phone, c.nickname, c.level_name, c.member_card, c.store_name,
                c.became_customer_at, c.joined_at, c.available_point, c.total_point,
                c.available_balance, c.black_user, c.customer_status,
                COUNT(cp.code) AS coupon_count,
                SUM(
                    CASE
                        WHEN {active_unused_coupon_sql('cp')}
                        THEN 1 ELSE 0
                    END
                ) AS unused_coupon_count
            FROM customers c
            LEFT JOIN coupons cp ON cp.customer_wid = c.wid
            {where}
            GROUP BY c.wid
            ORDER BY c.became_customer_at DESC, c.wid DESC
            LIMIT ? OFFSET ?
            """,
            (*params, limit, offset),
        ).fetchall()
        total = conn.execute(f"SELECT COUNT(*) FROM customers c {where}", params).fetchone()[0]
        return {"items": rows_to_dicts(rows), "total": total}


@app.get("/api/customers/{wid}")
def customer_detail(wid: str, request: Request) -> dict:
    require_login(request)
    with db_session() as conn:
        customer = require_customer(conn, wid)
        coupons = apply_dynamic_coupon_statuses(rows_to_dicts(
            conn.execute(
                """
                SELECT cp.*, ct.rule_text AS rule_text
                FROM coupons cp
                LEFT JOIN coupon_templates ct ON ct.id = cp.template_id
                WHERE cp.customer_wid = ?
                ORDER BY cp.receive_time DESC, cp.code DESC
                """,
                (wid,),
            ).fetchall()
        ))
        return {"customer": customer, "coupons": coupons}


@app.post("/api/customers")
def create_customer(req: CreateCustomerRequest, request: Request) -> dict:
    operator = require_login(request)
    phone = req.phone.strip()
    if not phone:
        raise HTTPException(status_code=400, detail="请输入手机号")

    with db_session() as conn:
        existing = row_to_dict(conn.execute("SELECT * FROM customers WHERE phone = ?", (phone,)).fetchone())
        if existing:
            return {"customer": existing, "created": False}

        vin = validate_new_customer_vin(conn, req.vin)
        wid = local_id("LOCAL_CUSTOMER")
        while conn.execute("SELECT 1 FROM customers WHERE wid = ?", (wid,)).fetchone():
            wid = local_id("LOCAL_CUSTOMER")
        store_name = require_enabled_store(conn, req.store_name)
        customer = {
            "wid": wid,
            "phone": phone,
            "nickname": req.nickname.strip(),
            "gender": req.gender.strip(),
            "birthday": req.birthday.strip(),
            "avatar_url": None,
            "became_customer_at": now_text(),
            "store_name": store_name,
            "channel": "本地新增",
            "member_card": None,
            "level_name": req.level_name.strip(),
            "joined_at": now_text(),
            "black_user": "False",
            "customer_status": "本地客户",
            "available_point": "0",
            "total_point": "0",
            "frozen_point": "0",
            "available_balance": "0",
            "frozen_balance": "0",
            "total_balance": "0",
            "real_name": req.real_name.strip(),
            "car_series": req.car_series.strip(),
            "vin": vin,
            "purchase_store_name": req.purchase_store_name.strip(),
            "plate_no": req.plate_no.strip(),
            "vehicle_query_success": "",
            "vehicle_errcode": "",
            "vehicle_errmsg": "",
            "raw_json": str({
                "source": "local",
                "remark": req.remark,
                "姓名": req.real_name.strip(),
                "车型车系": req.car_series.strip(),
                "车架号": vin,
                "购买门店": req.purchase_store_name.strip(),
                "车牌号": req.plate_no.strip(),
            }),
        }
        conn.execute(
            """
            INSERT INTO customers (
                wid, phone, nickname, gender, birthday, avatar_url, became_customer_at,
                store_name, channel, member_card, level_name, joined_at, black_user,
                customer_status, available_point, total_point, frozen_point,
                available_balance, frozen_balance, total_balance,
                real_name, car_series, vin, purchase_store_name, plate_no,
                vehicle_query_success, vehicle_errcode, vehicle_errmsg,
                raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            tuple(customer.values()),
        )
        ensure_store(conn, customer["store_name"])
        conn.execute(
            """
            INSERT INTO operation_logs (created_at, operator, action, customer_wid, target, quantity, remark)
            VALUES (?, ?, '新增客户', ?, ?, 1, ?)
            """,
            (now_text(), operator, wid, phone, req.remark),
        )
        return {"customer": customer, "created": True}


@app.get("/api/customer-lookup")
def customer_lookup(request: Request, q: str, limit: int = 10) -> dict:
    require_login(request)
    keyword_text = q.strip()
    if not keyword_text:
        return {"items": []}

    limit = max(1, min(limit, 20))
    keyword = f"%{keyword_text}%"
    with db_session() as conn:
        rows = conn.execute(
            """
            SELECT wid, phone, nickname, store_name, level_name, member_card,
                   available_point, total_point, customer_status
            FROM customers
            WHERE phone LIKE ? OR wid LIKE ? OR nickname LIKE ?
            ORDER BY
                CASE WHEN phone = ? THEN 0 WHEN wid = ? THEN 1 ELSE 2 END,
                became_customer_at DESC,
                wid DESC
            LIMIT ?
            """,
            (keyword, keyword, keyword, keyword_text, keyword_text, limit),
        ).fetchall()
        return {"items": rows_to_dicts(rows)}


@app.get("/api/cargeer/customer-lookup")
def cargeer_customer_lookup(request: Request, phone: str) -> dict:
    require_login(request)
    phone = phone.strip()
    if not phone:
        raise HTTPException(status_code=400, detail="请输入手机号")
    if len(phone) < 5:
        return {"items": [], "status": "too_short"}

    items, status = lookup_cargeer_options_by_phone(phone)
    if items:
        with db_session() as conn:
            items = enrich_cargeer_store_matches(conn, items)
    return {"items": items, "status": status}


@app.get("/api/stores")
def stores(request: Request) -> dict:
    require_login(request)
    with db_session() as conn:
        return {"items": usable_store_rows(conn)}


@app.get("/api/stores/all")
def stores_all(request: Request) -> dict:
    require_login(request)
    with db_session() as conn:
        return {"items": all_store_rows(conn)}


@app.get("/api/admin-users")
def admin_users(request: Request) -> dict:
    require_login(request)
    with db_session() as conn:
        rows = conn.execute(
            """
            SELECT id, username, display_name, phone, store_name, role, enabled, created_at, last_login_at
            FROM admin_users
            ORDER BY enabled DESC, store_name, display_name, phone
            """
        ).fetchall()
        return {"items": rows_to_dicts(rows)}


@app.post("/api/stores")
def create_store(req: CreateStoreRequest, request: Request) -> dict:
    require_login(request)
    name = req.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="请输入门店名称")

    with db_session() as conn:
        existing = row_to_dict(conn.execute("SELECT * FROM stores WHERE name = ?", (name,)).fetchone())
        if existing:
            conn.execute("UPDATE stores SET enabled = 1, code = COALESCE(NULLIF(?, ''), code) WHERE id = ?", (req.code.strip(), existing["id"]))
            return {"store": row_to_dict(conn.execute("SELECT * FROM stores WHERE id = ?", (existing["id"],)).fetchone()), "created": False}

        store_id = store_id_for(name)
        while conn.execute("SELECT 1 FROM stores WHERE id = ?", (store_id,)).fetchone():
            store_id = f"{store_id_for(name)}_{secrets.token_hex(2)}"
        conn.execute(
            """
            INSERT INTO stores (id, name, code, enabled, created_at, customer_count)
            VALUES (?, ?, ?, 1, ?, 0)
            """,
            (store_id, name, req.code.strip(), now_text()),
        )
        return {"store": row_to_dict(conn.execute("SELECT * FROM stores WHERE id = ?", (store_id,)).fetchone()), "created": True}


@app.patch("/api/stores/{store_id}")
def update_store(store_id: str, req: UpdateStoreRequest, request: Request) -> dict:
    require_login(request)
    with db_session() as conn:
        store = row_to_dict(conn.execute("SELECT * FROM stores WHERE id = ?", (store_id,)).fetchone())
        if not store:
            raise HTTPException(status_code=404, detail="门店不存在")
        if req.enabled is not None:
            conn.execute("UPDATE stores SET enabled = ? WHERE id = ?", (1 if req.enabled else 0, store_id))
        return {"store": row_to_dict(conn.execute("SELECT * FROM stores WHERE id = ?", (store_id,)).fetchone())}


@app.get("/api/templates")
def templates(request: Request) -> dict:
    require_login(request)
    with db_session() as conn:
        rows = conn.execute(
            "SELECT * FROM coupon_templates WHERE enabled = 1 ORDER BY name, id"
        ).fetchall()
        return {"items": rows_to_dicts(rows)}


@app.post("/api/templates")
def create_template(req: CreateTemplateRequest, request: Request) -> dict:
    operator = require_login(request)
    name = req.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="请输入券模板名称")

    template_id = local_id("LOCAL_TEMPLATE")
    with db_session() as conn:
        template = {
            "id": template_id,
            "name": name,
            "coupon_type": req.coupon_type.strip() or "通用券",
            "rule_text": req.rule_text.strip(),
            "enabled": 1,
            "source": "manual",
        }
        conn.execute(
            """
            INSERT INTO coupon_templates (id, name, coupon_type, rule_text, enabled, source)
            VALUES (?, ?, ?, ?, 1, 'manual')
            """,
            (template["id"], template["name"], template["coupon_type"], template["rule_text"]),
        )
        conn.execute(
            """
            INSERT INTO operation_logs (created_at, operator, action, customer_wid, target, quantity, remark)
            VALUES (?, ?, '新增券模板', NULL, ?, 1, ?)
            """,
            (now_text(), operator, name, template["rule_text"]),
        )
        return {"template": template}


@app.post("/api/coupons/issue")
def issue_coupon(req: IssueCouponRequest, request: Request) -> dict:
    username = require_login(request)
    if req.quantity < 1 or req.quantity > 100:
        raise HTTPException(status_code=400, detail="发券数量必须在 1-100 之间")
    if req.valid_days < 1 or req.valid_days > 3650:
        raise HTTPException(status_code=400, detail="有效天数必须在 1-3650 之间")

    with db_session() as conn:
        admin_profile = current_admin_profile(conn, username)
        customer = require_customer(conn, req.wid)
        template = require_template(conn, req.template_id)
        start = datetime.now()
        issued_at = now_text()
        end = start + timedelta(days=req.valid_days)
        issued = []
        usable_store_scope = req.usable_store_scope.strip() or "all"
        if usable_store_scope == "current":
            usable_store_ids = [admin_profile.get("store_id") or ""]
            usable_store_names = [admin_profile.get("store_name") or ""]
        elif usable_store_scope == "customer_store":
            usable_store_ids = []
            usable_store_names = [customer.get("store_name") or ""]
        elif usable_store_scope == "selected":
            usable_store_ids = req.usable_store_ids
            usable_store_names = req.usable_store_names
        else:
            store_rows = usable_store_rows(conn)
            usable_store_ids = []
            usable_store_names = [row.get("name") or "" for row in store_rows]
        if usable_store_scope in {"current", "customer_store", "selected"} and not join_text(usable_store_names):
            raise HTTPException(status_code=400, detail="请至少选择一个可用门店")

        for _ in range(req.quantity):
            code = f"TX{start:%Y%m%d}{secrets.token_hex(4).upper()}"
            coupon = {
                "code": code,
                "customer_wid": req.wid,
                "template_id": template["id"],
                "template_name": template["name"],
                "coupon_type": template["coupon_type"],
                "status": "unused",
                "status_text": "未使用",
                "receive_time": now_text(),
                "used_time": None,
                "valid_period": f"{start:%Y-%m-%d} 至 {end:%Y-%m-%d}",
                "valid_start": start.isoformat(),
                "valid_end": end.isoformat(),
                "phone": customer.get("phone"),
                "source": "manual",
                "remark": req.remark,
                "usable_store_scope": usable_store_scope,
                "usable_store_ids": join_text(usable_store_ids),
                "usable_store_names": join_text(usable_store_names),
                "issued_store_id": admin_profile.get("store_id"),
                "issued_store_name": admin_profile.get("store_name"),
                "issued_by_user_id": admin_profile.get("user_id"),
                "issued_by_name": admin_profile.get("name"),
                "issued_at": issued_at,
                "redeemed_store_id": None,
                "redeemed_store_name": None,
                "redeemed_by_user_id": None,
                "redeemed_by_name": None,
                "redeemed_at": None,
                "raw_json": json.dumps(
                    {
                        "source": "manual",
                        "优惠说明": req.remark,
                        "使用规则": template.get("rule_text") or "",
                        "使用门店": join_text(usable_store_names),
                    },
                    ensure_ascii=False,
                ),
            }
            conn.execute(
                """
                INSERT INTO coupons (
                    code, customer_wid, template_id, template_name, coupon_type, status,
                    status_text, receive_time, used_time, valid_period, valid_start,
                    valid_end, phone, source, remark,
                    usable_store_scope, usable_store_ids, usable_store_names,
                    issued_store_id, issued_store_name, issued_by_user_id, issued_by_name, issued_at,
                    redeemed_store_id, redeemed_store_name, redeemed_by_user_id, redeemed_by_name, redeemed_at,
                    raw_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                tuple(coupon.values()),
            )
            issued.append(coupon)

        conn.execute(
            """
            INSERT INTO operation_logs (created_at, operator, action, customer_wid, target, quantity, remark)
            VALUES (?, ?, '发券', ?, ?, ?, ?)
            """,
            (now_text(), req.operator, req.wid, template["name"], req.quantity, req.remark),
        )
        return {"issued": issued}


@app.post("/api/coupons/redeem")
def redeem_coupon(req: RedeemCouponRequest, request: Request) -> dict:
    username = require_login(request)
    code = req.code.strip()
    if not code:
        raise HTTPException(status_code=400, detail="请输入券码")

    with db_session() as conn:
        admin_profile = current_admin_profile(conn, username)
        row = conn.execute("SELECT * FROM coupons WHERE code = ?", (code,)).fetchone()
        coupon = row_to_dict(row)
        if not coupon:
            raise HTTPException(status_code=404, detail="券码不存在")
        coupon = apply_dynamic_coupon_status(coupon)
        if coupon["status"] != "unused":
            raise HTTPException(status_code=400, detail=f"该券当前状态不可核销: {coupon['status_text']}")

        used_time = now_text()
        cursor = conn.execute(
            """
            UPDATE coupons
            SET status = 'used',
                status_text = '已核销',
                used_time = ?,
                redeemed_store_id = ?,
                redeemed_store_name = ?,
                redeemed_by_user_id = ?,
                redeemed_by_name = ?,
                redeemed_at = ?
            WHERE code = ? AND status = 'unused'
            """,
            (
                used_time,
                admin_profile.get("store_id"),
                admin_profile.get("store_name"),
                admin_profile.get("user_id"),
                admin_profile.get("name"),
                used_time,
                code,
            ),
        )
        if cursor.rowcount != 1:
            raise HTTPException(status_code=409, detail="核销失败：券状态已变化，请刷新后重试")
        conn.execute(
            """
            INSERT INTO operation_logs (created_at, operator, action, customer_wid, target, quantity, remark)
            VALUES (?, ?, '核销', ?, ?, 1, ?)
            """,
            (used_time, req.operator, coupon["customer_wid"], code, req.remark),
        )
        coupon.update({
            "status": "used",
            "status_text": "已核销",
            "used_time": used_time,
            "redeemed_store_id": admin_profile.get("store_id"),
            "redeemed_store_name": admin_profile.get("store_name"),
            "redeemed_by_user_id": admin_profile.get("user_id"),
            "redeemed_by_name": admin_profile.get("name"),
            "redeemed_at": used_time,
        })
        return {"coupon": coupon}


@app.post("/api/coupons/void")
def void_coupon(req: VoidCouponRequest, request: Request) -> dict:
    username = require_login(request)
    code = req.code.strip()
    if not code:
        raise HTTPException(status_code=400, detail="请输入券码")

    with db_session() as conn:
        admin_profile = current_admin_profile(conn, username)
        row = conn.execute("SELECT * FROM coupons WHERE code = ?", (code,)).fetchone()
        coupon = row_to_dict(row)
        if not coupon:
            raise HTTPException(status_code=404, detail="券码不存在")
        coupon = apply_dynamic_coupon_status(coupon)
        if coupon["status"] != "unused":
            raise HTTPException(status_code=400, detail=f"该券当前状态不可作废: {coupon['status_text']}")

        voided_at = now_text()
        cursor = conn.execute(
            """
            UPDATE coupons
            SET status = 'voided',
                status_text = '已作废',
                voided_by_user_id = ?,
                voided_by_name = ?,
                voided_at = ?,
                void_reason = ?
            WHERE code = ? AND status = 'unused'
            """,
            (
                admin_profile.get("user_id"),
                admin_profile.get("name"),
                voided_at,
                req.remark,
                code,
            ),
        )
        if cursor.rowcount != 1:
            raise HTTPException(status_code=409, detail="作废失败：券状态已变化，请刷新后重试")
        conn.execute(
            """
            INSERT INTO operation_logs (created_at, operator, action, customer_wid, target, quantity, remark)
            VALUES (?, ?, '作废', ?, ?, 1, ?)
            """,
            (voided_at, req.operator, coupon["customer_wid"], code, req.remark),
        )
        coupon.update({
            "status": "voided",
            "status_text": "已作废",
            "voided_by_user_id": admin_profile.get("user_id"),
            "voided_by_name": admin_profile.get("name"),
            "voided_at": voided_at,
            "void_reason": req.remark,
        })
        return {"coupon": coupon}


@app.get("/api/logs")
def logs(request: Request, limit: int = 100) -> dict:
    require_login(request)
    limit = max(1, min(limit, 500))
    with db_session() as conn:
        rows = conn.execute(
            "SELECT * FROM operation_logs ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return {"items": rows_to_dicts(rows)}


app.mount("/assets", StaticFiles(directory=FRONTEND_DIR), name="assets")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/{path:path}")
def spa_fallback(path: str) -> FileResponse:
    candidate = FRONTEND_DIR / path
    if candidate.exists() and candidate.is_file():
        return FileResponse(candidate)
    return FileResponse(FRONTEND_DIR / "index.html")
