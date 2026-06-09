from __future__ import annotations

import asyncio
import csv
from contextlib import suppress
from datetime import datetime, timedelta
import hashlib
import io
import json
from pathlib import Path
import re
import secrets
import time
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException
from fastapi import Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response as FastAPIResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import requests

from .auth import authenticate, clear_session_cookie, current_username, hash_password, require_login, set_session_cookie, verify_password
from .cargeer import lookup_cargeer_options_by_phone
from .config import AUTO_IMPORT, DB_PATH, SUPER_ADMIN_PASSWORD, SUPER_ADMIN_USERNAME, WEB_DIR, WECHAT_APPID, WECHAT_APPSECRET
from .database import db_session, row_to_dict, rows_to_dicts
from .schema import create_schema
from .sms import SmsError, normalize_phone, send_sms_code, verify_sms_code


FRONTEND_DIR = WEB_DIR / "frontend"
APP_TZ = ZoneInfo("Asia/Shanghai")

app = FastAPI(title="积分商城后台 API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

expiry_task: asyncio.Task | None = None
wechat_access_token_cache: dict = {}
wechat_jsapi_ticket_cache: dict = {}


class IssueCouponRequest(BaseModel):
    wid: str
    template_id: str
    quantity: int = 1
    validity_type: str = "days"
    valid_days: int = 30
    operator: str = "员工"
    remark: str = ""
    usable_store_scope: str = "all"
    usable_store_ids: list[str] = []
    usable_store_names: list[str] = []
    operation_store_id: str = ""
    operation_store_name: str = ""


class RedeemCouponRequest(BaseModel):
    code: str
    operator: str = "员工"
    remark: str = ""
    redeem_store_id: str = ""
    redeem_store_name: str = ""


class VoidCouponRequest(BaseModel):
    code: str
    operator: str = "员工"
    remark: str = ""


class LoginRequest(BaseModel):
    username: str
    password: str


class SwitchIdentityRequest(BaseModel):
    user_id: str


class RegisterAdminRequest(BaseModel):
    phone: str
    sms_code: str
    password: str
    password_confirm: str = ""


class SendAdminRegisterSmsRequest(BaseModel):
    phone: str


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


class UpdateCustomerRequest(BaseModel):
    phone: str | None = None
    nickname: str | None = None
    store_name: str | None = None
    level_name: str | None = None
    birthday: str | None = None
    gender: str | None = None
    real_name: str | None = None
    car_series: str | None = None
    vin: str | None = None
    purchase_store_name: str | None = None
    plate_no: str | None = None


class DeleteCustomerRequest(BaseModel):
    reason: str = ""


class CreateTemplateRequest(BaseModel):
    name: str
    coupon_type: str = "通用券"
    rule_text: str = ""


class UpdateTemplateRequest(BaseModel):
    name: str | None = None
    coupon_type: str | None = None
    rule_text: str | None = None
    enabled: bool | None = None


class CreateStoreRequest(BaseModel):
    name: str
    code: str = ""


class UpdateStoreRequest(BaseModel):
    enabled: bool | None = None


class UpdateAdminUserRequest(BaseModel):
    role: str | None = None
    enabled: bool | None = None
    can_issue_renewal: bool | None = None


class CreateAdminUserRequest(BaseModel):
    phone: str
    name: str
    store_id: str = ""
    role: str
    can_issue_renewal: bool = False


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
        ensure_super_admin(conn)


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
    return datetime.now(APP_TZ).strftime("%Y-%m-%d %H:%M:%S")


def ensure_super_admin(conn) -> None:
    username = SUPER_ADMIN_USERNAME.strip()
    password = SUPER_ADMIN_PASSWORD.strip()
    if not username or not password:
        return
    now = now_text()
    existing = row_to_dict(
        conn.execute("SELECT id FROM admin_users WHERE username = ?", (username,)).fetchone()
    )
    if existing:
        conn.execute(
            """
            UPDATE admin_users
            SET password_hash = ?, display_name = ?, role = 'super_admin', enabled = 1,
                registered_at = COALESCE(registered_at, ?), deleted_at = NULL
            WHERE username = ?
            """,
            (hash_password(password), username, now, username),
        )
        return
    legacy = row_to_dict(
        conn.execute("SELECT id FROM admin_users WHERE id = 'SUPER_ADMIN'").fetchone()
    )
    if legacy:
        conn.execute(
            """
            UPDATE admin_users
            SET username = ?, password_hash = ?, display_name = ?, phone = '',
                store_id = NULL, store_name = '', role = 'super_admin', enabled = 1,
                registered_at = COALESCE(registered_at, ?), deleted_at = NULL
            WHERE id = 'SUPER_ADMIN'
            """,
            (username, hash_password(password), username, now),
        )
        return
    conn.execute(
        """
        INSERT INTO admin_users (
            id, username, password_hash, display_name, phone, store_id, store_name,
            role, enabled, created_at, registered_at, last_login_at, deleted_at
        )
        VALUES (?, ?, ?, ?, '', NULL, '', 'super_admin', 1, ?, ?, NULL, NULL)
        """,
        ("SUPER_ADMIN", username, hash_password(password), username, now, now),
    )


def get_wechat_access_token() -> str:
    if not WECHAT_APPID or not WECHAT_APPSECRET:
        raise HTTPException(status_code=400, detail="微信扫码未配置")
    now = time.time()
    if wechat_access_token_cache.get("value") and wechat_access_token_cache.get("expires_at", 0) > now + 120:
        return wechat_access_token_cache["value"]
    res = requests.get(
        "https://api.weixin.qq.com/cgi-bin/token",
        params={"grant_type": "client_credential", "appid": WECHAT_APPID, "secret": WECHAT_APPSECRET},
        timeout=10,
    )
    data = res.json()
    token = data.get("access_token")
    if not token:
        raise HTTPException(status_code=502, detail=data.get("errmsg") or "获取微信 access_token 失败")
    wechat_access_token_cache.update({"value": token, "expires_at": now + int(data.get("expires_in", 7200))})
    return token


def get_wechat_jsapi_ticket() -> str:
    now = time.time()
    if wechat_jsapi_ticket_cache.get("value") and wechat_jsapi_ticket_cache.get("expires_at", 0) > now + 120:
        return wechat_jsapi_ticket_cache["value"]
    token = get_wechat_access_token()
    res = requests.get(
        "https://api.weixin.qq.com/cgi-bin/ticket/getticket",
        params={"access_token": token, "type": "jsapi"},
        timeout=10,
    )
    data = res.json()
    ticket = data.get("ticket")
    if not ticket:
        raise HTTPException(status_code=502, detail=data.get("errmsg") or "获取微信 jsapi_ticket 失败")
    wechat_jsapi_ticket_cache.update({"value": ticket, "expires_at": now + int(data.get("expires_in", 7200))})
    return ticket


def local_id(prefix: str) -> str:
    return f"{prefix}_{datetime.now(APP_TZ):%Y%m%d%H%M%S}_{secrets.token_hex(3).upper()}"


VIN_PATTERN = re.compile(r"^[A-HJ-NPR-Z0-9]{17}$")


def normalize_vin(value: str) -> str:
    return re.sub(r"\s+", "", value or "").upper()


def validate_customer_vin(conn, vin: str, current_wid: str = "") -> str:
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
              AND wid != ?
              AND deleted_at IS NULL
            LIMIT 1
            """,
            (normalized, current_wid),
        ).fetchone()
    )
    if existing:
        name = existing.get("real_name") or existing.get("nickname") or "-"
        raise HTTPException(
            status_code=400,
            detail=f"车架号已存在：{normalized}，客户 {name}，手机号 {existing.get('phone') or '-'}，WID {existing.get('wid')}",
        )
    return normalized


def validate_new_customer_vin(conn, vin: str) -> str:
    return validate_customer_vin(conn, vin)


def validate_customer_phone_unique(conn, phone: str, current_wid: str = "") -> str:
    normalized = re.sub(r"\D+", "", phone or "")
    if not re.fullmatch(r"1[3-9]\d{9}", normalized):
        raise HTTPException(status_code=400, detail="请输入正确的手机号")
    existing = row_to_dict(
        conn.execute(
            "SELECT wid, nickname, real_name FROM customers WHERE phone = ? AND wid != ? AND deleted_at IS NULL LIMIT 1",
            (normalized, current_wid),
        ).fetchone()
    )
    if existing:
        name = existing.get("real_name") or existing.get("nickname") or "-"
        raise HTTPException(status_code=400, detail=f"手机号已存在：客户 {name}，WID {existing.get('wid')}")
    return normalized


def current_admin_profile(conn, username: str) -> dict:
    user = row_to_dict(
        conn.execute(
            """
            SELECT u.id, u.username, u.display_name, u.phone, u.store_id, u.store_name, u.role,
                   COALESCE(u.can_issue_renewal, 0) AS can_issue_renewal,
                   s.name AS linked_store_name
            FROM admin_users u
            LEFT JOIN stores s ON s.id = u.store_id
            WHERE u.username = ? AND u.enabled = 1 AND u.deleted_at IS NULL
            """,
            (username,),
        ).fetchone()
    )
    if user:
        stores = admin_store_rows(conn, user.get("id"), user.get("store_id"), user.get("store_name") or user.get("linked_store_name"))
        store_names = [store.get("name") or "" for store in stores]
        primary_store = stores[0] if stores else {"id": user.get("store_id"), "name": user.get("store_name") or user.get("linked_store_name")}
        return {
            "user_id": user.get("id") or user.get("username"),
            "username": user.get("username"),
            "phone": user.get("phone") or user.get("username"),
            "name": user.get("display_name") or user.get("username"),
            "store_id": primary_store.get("id"),
            "store_name": join_text(store_names) or primary_store.get("name"),
            "stores": stores,
            "store_ids": [store.get("id") for store in stores],
            "store_names": store_names,
            "role": user.get("role") or "staff",
            "can_issue_renewal": user.get("role") == "super_admin" or bool(user.get("can_issue_renewal")),
        }
    if username != SUPER_ADMIN_USERNAME.strip() or not SUPER_ADMIN_USERNAME.strip():
        raise HTTPException(status_code=401, detail="login expired")
    return {
        "user_id": username,
        "username": username,
        "phone": "",
        "name": username,
        "store_id": None,
        "store_name": "",
        "stores": [],
        "store_ids": [],
        "store_names": [],
        "role": "super_admin",
        "can_issue_renewal": True,
    }


def admin_identity_options(conn, profile: dict) -> list[dict]:
    phone = (profile.get("phone") or "").strip()
    if not phone or profile.get("role") == "super_admin":
        return []
    rows = rows_to_dicts(
        conn.execute(
            """
            SELECT id, username, display_name, phone, store_id, store_name, role
            FROM admin_users
            WHERE phone = ? AND enabled = 1 AND deleted_at IS NULL AND registered_at IS NOT NULL
            ORDER BY store_name, role, display_name, username
            """,
            (phone,),
        ).fetchall()
    )
    return [
        {
            "user_id": row.get("id"),
            "username": row.get("username"),
            "name": row.get("display_name") or row.get("username"),
            "phone": row.get("phone"),
            "store_id": row.get("store_id"),
            "store_name": row.get("store_name"),
            "role": row.get("role") or "issuer",
            "current": row.get("id") == profile.get("user_id"),
        }
        for row in rows
    ]


def attach_profile_extras(conn, profile: dict) -> dict:
    profile["permissions"] = role_permissions(profile.get("role") or "issuer")
    profile["identities"] = admin_identity_options(conn, profile)
    return profile


def can_issue_renewal_coupon(admin_profile: dict) -> bool:
    role = admin_profile.get("role") or ""
    return role == "super_admin" or bool(admin_profile.get("can_issue_renewal"))


def admin_role(conn, username: str) -> str:
    return current_admin_profile(conn, username).get("role") or "issuer"


def role_permissions(role: str) -> dict:
    role = role or "issuer"
    is_super_admin = role == "super_admin"
    is_admin = role in {"super_admin", "admin"}
    return {
        "can_admin_users": is_admin,
        "can_promote_admin": is_super_admin,
        "can_issue": is_admin or role == "issuer",
        "can_create_customer": is_admin or role == "issuer",
        "can_void": is_admin or role == "issuer",
        "can_redeem": is_admin or role == "redeemer",
        "can_manage_templates": is_admin,
        "can_manage_stores": is_admin,
    }


def require_role(request: Request, allowed_roles: set[str]) -> str:
    username = require_login(request)
    with db_session() as conn:
        role = admin_role(conn, username)
    if role not in allowed_roles:
        raise HTTPException(status_code=403, detail="当前账号没有该操作权限")
    return username


def join_text(values: list[str]) -> str:
    return ",".join(str(value).strip() for value in values if str(value).strip())


def split_text(value: str | None) -> list[str]:
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


def admin_store_rows(conn, user_id: str | None, fallback_store_id: str | None = "", fallback_store_name: str | None = "") -> list[dict]:
    rows: list[dict] = []
    if user_id:
        rows = rows_to_dicts(
            conn.execute(
                """
                SELECT store_id AS id, store_name AS name
                FROM admin_user_stores
                WHERE admin_user_id = ?
                ORDER BY store_name
                """,
                (user_id,),
            ).fetchall()
        )
    if not rows and (fallback_store_id or fallback_store_name):
        rows = [{"id": fallback_store_id or "", "name": fallback_store_name or fallback_store_id or ""}]
    return [row for row in rows if (row.get("id") or row.get("name"))]


def store_options_by_ids(conn, store_ids: list[str]) -> list[dict]:
    cleaned = []
    for store_id in store_ids:
        value = str(store_id or "").strip()
        if value and value not in cleaned:
            cleaned.append(value)
    if not cleaned:
        return []
    placeholders = ",".join("?" for _ in cleaned)
    rows = rows_to_dicts(
        conn.execute(
            f"SELECT id, name FROM stores WHERE id IN ({placeholders}) AND enabled = 1",
            cleaned,
        ).fetchall()
    )
    by_id = {row["id"]: row for row in rows}
    return [by_id[store_id] for store_id in cleaned if store_id in by_id]


def unique_admin_username(conn, phone: str, current_user_id: str = "") -> str:
    username = phone
    row = conn.execute(
        "SELECT id FROM admin_users WHERE username = ? AND id != ?",
        (username, current_user_id),
    ).fetchone()
    if not row:
        return username
    username = f"{phone}_{secrets.token_hex(3)}"
    while conn.execute("SELECT 1 FROM admin_users WHERE username = ?", (username,)).fetchone():
        username = f"{phone}_{secrets.token_hex(3)}"
    return username


def replace_admin_user_stores(conn, user_id: str, stores: list[dict]) -> None:
    conn.execute("DELETE FROM admin_user_stores WHERE admin_user_id = ?", (user_id,))
    for store in stores:
        conn.execute(
            """
            INSERT OR IGNORE INTO admin_user_stores (id, admin_user_id, store_id, store_name, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (local_id("ADMIN_STORE"), user_id, store["id"], store["name"], now_text()),
        )
    primary = stores[0] if stores else {"id": None, "name": ""}
    conn.execute(
        "UPDATE admin_users SET store_id = ?, store_name = ? WHERE id = ?",
        (primary.get("id"), primary.get("name") or "", user_id),
    )


def select_admin_store(admin_profile: dict, store_id: str = "", store_name: str = "") -> dict:
    stores = admin_profile.get("stores") or []
    cleaned_id = (store_id or "").strip()
    cleaned_name = (store_name or "").strip()
    if not stores:
        return {"id": None, "name": ""}
    if cleaned_id or cleaned_name:
        for store in stores:
            if (cleaned_id and str(store.get("id") or "") == cleaned_id) or (cleaned_name and str(store.get("name") or "") == cleaned_name):
                return store
        raise HTTPException(status_code=403, detail="selected store is not bound to current account")
    if len(stores) == 1:
        return stores[0]
    raise HTTPException(status_code=400, detail="please choose operation store")


def redeem_store_options(coupon: dict, admin_profile: dict) -> list[dict]:
    stores = admin_profile.get("stores") or []
    usable_store_names = split_text(coupon.get("usable_store_names"))
    if not usable_store_names:
        return stores
    allowed = set(usable_store_names)
    return [store for store in stores if (store.get("name") or "").strip() in allowed]


def select_redeem_store(coupon: dict, admin_profile: dict, store_id: str = "", store_name: str = "") -> dict:
    options = redeem_store_options(coupon, admin_profile)
    if not options:
        raise HTTPException(status_code=403, detail="当前账户所属门店不能核销该券")
    cleaned_id = (store_id or "").strip()
    cleaned_name = (store_name or "").strip()
    if cleaned_id or cleaned_name:
        for store in options:
            if (cleaned_id and str(store.get("id") or "") == cleaned_id) or (cleaned_name and str(store.get("name") or "") == cleaned_name):
                return store
        raise HTTPException(status_code=403, detail="所选门店不能核销该券")
    if len(options) == 1:
        return options[0]
    raise HTTPException(status_code=400, detail="请选择本次核销门店")


def store_id_for(name: str) -> str:
    slug = re.sub(r"[^0-9A-Za-z]+", "_", name).strip("_").lower()
    digest = hashlib.sha1(name.encode("utf-8")).hexdigest()[:10]
    return f"store_{slug}_{digest}" if slug else f"store_{digest}"


def ensure_store(conn, name: str) -> None:
    store_name = name.strip()
    if not store_name:
        return
    customer_count = conn.execute(
        "SELECT COUNT(*) FROM customers WHERE TRIM(store_name) = ? AND deleted_at IS NULL",
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
        if valid_end and valid_end < datetime.now(APP_TZ).replace(tzinfo=None):
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
    now = datetime.now(APP_TZ).replace(tzinfo=None)
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


def require_customer(conn, wid: str, include_deleted: bool = False) -> dict:
    deleted_filter = "" if include_deleted else " AND deleted_at IS NULL"
    row = conn.execute(f"SELECT * FROM customers WHERE wid = ?{deleted_filter}", (wid,)).fetchone()
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


def active_customer_sql(alias: str = "") -> str:
    prefix = f"{alias}." if alias else ""
    return f"{prefix}deleted_at IS NULL"


def log_date_range(from_date: str = "", to_date: str = "") -> tuple[str, str]:
    start = (from_date or "").strip()
    end = (to_date or "").strip()
    if not start or not end:
        raise HTTPException(status_code=400, detail="请选择开始日期和结束日期")
    try:
        start_dt = datetime.strptime(start, "%Y-%m-%d")
        end_dt = datetime.strptime(end, "%Y-%m-%d")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="日期格式不正确") from exc
    if end_dt < start_dt:
        raise HTTPException(status_code=400, detail="结束日期不能早于开始日期")
    if (end_dt - start_dt).days > 366:
        raise HTTPException(status_code=400, detail="单次最多导出 366 天")
    return f"{start} 00:00:00", f"{end} 23:59:59"


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
                WHERE phone = ? AND deleted_at IS NULL
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
            WHERE cp.code = ? AND c.phone = ? AND c.deleted_at IS NULL
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
        users = rows_to_dicts(
            conn.execute(
                """
                SELECT *
                FROM admin_users
                WHERE (username = ? OR phone = ?) AND enabled = 1 AND deleted_at IS NULL
                ORDER BY username = ? DESC, store_name, role, display_name
                """,
                (username, username, username),
            ).fetchall()
        )
        user = next((row for row in users if verify_password(req.password, row.get("password_hash"))), None)
        if user:
            if user.get("role") not in {"admin", "super_admin"} and not user.get("registered_at"):
                raise HTTPException(status_code=403, detail="请先用手机号验证码完成注册")
            conn.execute("UPDATE admin_users SET last_login_at = ? WHERE id = ?", (now_text(), user["id"]))
            set_session_cookie(response, user["username"])
            profile = attach_profile_extras(conn, current_admin_profile(conn, user["username"]))
            return {"username": user["username"], "profile": profile}

    if authenticate(username, req.password):
        set_session_cookie(response, username)
        profile = {
            "user_id": username,
            "username": username,
            "phone": "",
            "name": username,
            "store_id": None,
            "store_name": "",
            "stores": [],
            "identities": [],
            "role": "super_admin",
        }
        profile["permissions"] = role_permissions("super_admin")
        return {"username": username, "profile": profile}

    raise HTTPException(status_code=401, detail="用户名或密码错误")


@app.get("/api/auth/register-options")
def register_options() -> dict:
    with db_session() as conn:
        return {"stores": usable_store_rows(conn)}


@app.post("/api/auth/register-sms/send")
def send_admin_register_sms(req: SendAdminRegisterSmsRequest) -> dict:
    try:
        phone = normalize_phone(req.phone)
    except SmsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    with db_session() as conn:
        user = row_to_dict(
            conn.execute(
                """
                SELECT id, registered_at, enabled, deleted_at
                FROM admin_users
                WHERE (username = ? OR phone = ?) AND enabled = 1 AND deleted_at IS NULL
                ORDER BY registered_at IS NULL DESC
                """,
                (phone, phone),
            ).fetchone()
        )
        if not user:
            raise HTTPException(status_code=400, detail="该手机号尚未由管理员添加，不能注册")

    try:
        send_sms_code(phone)
    except SmsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True}


@app.post("/api/auth/register")
def register_admin(req: RegisterAdminRequest, response: Response) -> dict:
    try:
        phone = normalize_phone(req.phone)
    except SmsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    password = req.password.strip()
    password_confirm = req.password_confirm.strip()
    if len(password) < 5:
        raise HTTPException(status_code=400, detail="密码至少 5 位")
    if password_confirm and password != password_confirm:
        raise HTTPException(status_code=400, detail="两次输入的密码不一致")

    try:
        if not verify_sms_code(phone, req.sms_code):
            raise HTTPException(status_code=400, detail="验证码错误或已过期")
    except SmsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    with db_session() as conn:
        users = rows_to_dicts(
            conn.execute(
                """
                SELECT *
                FROM admin_users
                WHERE (username = ? OR phone = ?) AND deleted_at IS NULL
                ORDER BY registered_at IS NULL DESC, store_name, role, display_name
                """,
                (phone, phone),
            ).fetchall()
        )
        if not users:
            raise HTTPException(status_code=400, detail="该手机号尚未由管理员添加，不能注册")
        if not any(row.get("enabled") for row in users):
            raise HTTPException(status_code=400, detail="该账号已停用，不能注册")

        now = now_text()
        password_hash = hash_password(password)
        conn.execute(
            """
            UPDATE admin_users
            SET password_hash = ?, registered_at = COALESCE(registered_at, ?)
            WHERE phone = ? AND enabled = 1 AND deleted_at IS NULL
            """,
            (password_hash, now, phone),
        )
        user = rows_to_dicts(
            conn.execute(
                """
                SELECT *
                FROM admin_users
                WHERE phone = ? AND enabled = 1 AND deleted_at IS NULL
                ORDER BY store_name, role, display_name
                """,
                (phone,),
            ).fetchall()
        )[0]
        conn.execute("UPDATE admin_users SET last_login_at = ? WHERE id = ?", (now, user["id"]))
        set_session_cookie(response, user["username"])
        profile = attach_profile_extras(conn, current_admin_profile(conn, user["username"]))
        return {"ok": True, "username": user["username"], "profile": profile}


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
        profile = attach_profile_extras(conn, current_admin_profile(conn, username))
        return {"username": username, "profile": profile}


@app.post("/api/auth/switch-identity")
def switch_identity(req: SwitchIdentityRequest, request: Request, response: Response) -> dict:
    username = require_login(request)
    with db_session() as conn:
        current = current_admin_profile(conn, username)
        target = row_to_dict(
            conn.execute(
                """
                SELECT *
                FROM admin_users
                WHERE id = ? AND enabled = 1 AND deleted_at IS NULL AND registered_at IS NOT NULL
                """,
                (req.user_id.strip(),),
            ).fetchone()
        )
        if not target:
            raise HTTPException(status_code=404, detail="identity not found")
        if current.get("role") != "super_admin" and (target.get("phone") or "") != (current.get("phone") or ""):
            raise HTTPException(status_code=403, detail="cannot switch to this identity")
        conn.execute("UPDATE admin_users SET last_login_at = ? WHERE id = ?", (now_text(), target["id"]))
        set_session_cookie(response, target["username"])
        profile = attach_profile_extras(conn, current_admin_profile(conn, target["username"]))
        return {"username": target["username"], "profile": profile}


@app.get("/api/summary")
def summary(request: Request) -> dict:
    require_login(request)
    with db_session() as conn:
        def scalar(sql: str) -> int:
            return int(conn.execute(sql).fetchone()[0])

        return {
            "customers": scalar("SELECT COUNT(*) FROM customers WHERE deleted_at IS NULL"),
            "coupons": scalar("SELECT COUNT(*) FROM coupons"),
            "unused_coupons": scalar(
                f"SELECT COUNT(*) FROM coupons WHERE {active_unused_coupon_sql()}"
            ),
            "used_coupons": scalar("SELECT COUNT(*) FROM coupons WHERE status = 'used'"),
            "yesterday_issued_coupons": scalar(
                "SELECT COUNT(*) FROM coupons "
                "WHERE datetime(issued_at) >= datetime('now', 'localtime', 'start of day', '-1 day') "
                "AND datetime(issued_at) < datetime('now', 'localtime', 'start of day')"
            ),
            "yesterday_redeemed_coupons": scalar(
                "SELECT COUNT(*) FROM coupons "
                "WHERE status = 'used' "
                "AND datetime(redeemed_at) >= datetime('now', 'localtime', 'start of day', '-1 day') "
                "AND datetime(redeemed_at) < datetime('now', 'localtime', 'start of day')"
            ),
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
    deleted_status: str = "active",
    limit: int = 50,
    offset: int = 0,
) -> dict:
    username = require_login(request)
    limit = max(1, min(limit, 200))
    offset = max(0, offset)
    keyword = f"%{q.strip()}%"
    with db_session() as conn:
        role = admin_role(conn, username)
        can_view_deleted = role in {"admin", "super_admin"}
        if not can_view_deleted:
            deleted_status = "active"
        deleted_status = deleted_status if deleted_status in {"active", "deleted", "all"} else "active"
        if deleted_status == "deleted":
            where_parts = ["c.deleted_at IS NOT NULL"]
        elif deleted_status == "all":
            where_parts = []
        else:
            where_parts = [active_customer_sql("c")]
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
        rows = conn.execute(
            f"""
            SELECT
                c.wid, c.phone, c.nickname, c.level_name, c.member_card, c.store_name,
                c.real_name, c.vin, c.plate_no, c.car_series,
                c.became_customer_at, c.joined_at, c.available_point, c.total_point,
                c.available_balance, c.black_user, c.customer_status,
                c.deleted_at, c.deleted_by, c.deleted_reason,
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
    username = require_login(request)
    with db_session() as conn:
        role = admin_role(conn, username)
        customer = require_customer(conn, wid, include_deleted=role in {"admin", "super_admin"})
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


@app.patch("/api/customers/{wid}")
def update_customer(wid: str, req: UpdateCustomerRequest, request: Request) -> dict:
    operator = require_role(request, {"admin", "super_admin", "issuer"})
    with db_session() as conn:
        customer = require_customer(conn, wid)
        updates = []
        params = []

        if req.phone is not None:
            updates.append("phone = ?")
            params.append(validate_customer_phone_unique(conn, req.phone, wid))
        if req.nickname is not None:
            updates.append("nickname = ?")
            params.append(req.nickname.strip())
        if req.store_name is not None:
            updates.append("store_name = ?")
            params.append(require_enabled_store(conn, req.store_name))
        if req.level_name is not None:
            updates.append("level_name = ?")
            params.append(req.level_name.strip())
        if req.birthday is not None:
            updates.append("birthday = ?")
            params.append(req.birthday.strip())
        if req.gender is not None:
            updates.append("gender = ?")
            params.append(req.gender.strip())
        if req.real_name is not None:
            updates.append("real_name = ?")
            params.append(req.real_name.strip())
        if req.car_series is not None:
            updates.append("car_series = ?")
            params.append(req.car_series.strip())
        if req.vin is not None:
            updates.append("vin = ?")
            params.append(validate_customer_vin(conn, req.vin, wid))
        if req.purchase_store_name is not None:
            updates.append("purchase_store_name = ?")
            params.append(req.purchase_store_name.strip())
        if req.plate_no is not None:
            updates.append("plate_no = ?")
            params.append(req.plate_no.strip())

        if updates:
            params.append(wid)
            conn.execute(f"UPDATE customers SET {', '.join(updates)} WHERE wid = ?", params)
            conn.execute(
                """
                INSERT INTO operation_logs (created_at, operator, action, customer_wid, target, quantity, remark)
                VALUES (?, ?, '修改客户资料', ?, ?, 1, ?)
                """,
                (now_text(), operator, wid, customer.get("phone"), "后台手动修改"),
            )
        return {"customer": require_customer(conn, wid)}


@app.delete("/api/customers/{wid}")
def delete_customer(wid: str, req: DeleteCustomerRequest, request: Request) -> dict:
    operator = require_role(request, {"admin", "super_admin"})
    reason = req.reason.strip()
    if not reason:
        raise HTTPException(status_code=400, detail="请输入删除原因")

    with db_session() as conn:
        customer = require_customer(conn, wid)
        deleted_at = now_text()
        conn.execute(
            """
            UPDATE customers
            SET deleted_at = ?, deleted_by = ?, deleted_reason = ?
            WHERE wid = ? AND deleted_at IS NULL
            """,
            (deleted_at, operator, reason, wid),
        )
        conn.execute(
            """
            INSERT INTO operation_logs (created_at, operator, action, customer_wid, target, quantity, remark)
            VALUES (?, ?, '删除客户', ?, ?, 1, ?)
            """,
            (deleted_at, operator, wid, customer.get("phone"), reason),
        )
        ensure_store(conn, customer.get("store_name") or "")
        return {"ok": True, "deleted_at": deleted_at}


@app.post("/api/customers")
def create_customer(req: CreateCustomerRequest, request: Request) -> dict:
    operator = require_role(request, {"admin", "super_admin", "issuer"})
    phone = req.phone.strip()
    if not phone:
        raise HTTPException(status_code=400, detail="请输入手机号")

    with db_session() as conn:
        existing = row_to_dict(conn.execute("SELECT * FROM customers WHERE phone = ? AND deleted_at IS NULL", (phone,)).fetchone())
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
def customer_lookup(request: Request, q: str, limit: int = 10, mode: str = "") -> dict:
    require_login(request)
    keyword_text = q.strip()
    if not keyword_text:
        return {"items": []}

    limit = max(1, min(limit, 20))
    if mode == "vin":
        vin = normalize_vin(keyword_text)
        if not vin:
            return {"items": []}
        with db_session() as conn:
            rows = conn.execute(
                """
                SELECT wid, phone, nickname, real_name, vin, plate_no, store_name, level_name, member_card,
                       available_point, total_point, customer_status
                FROM customers
                WHERE COALESCE(TRIM(vin), '') != ''
                  AND deleted_at IS NULL
                  AND UPPER(REPLACE(REPLACE(REPLACE(TRIM(COALESCE(vin, '')), ' ', ''), char(9), ''), char(12288), '')) LIKE ?
                ORDER BY
                    CASE
                        WHEN UPPER(REPLACE(REPLACE(REPLACE(TRIM(COALESCE(vin, '')), ' ', ''), char(9), ''), char(12288), '')) = ? THEN 0
                        ELSE 1
                    END,
                    became_customer_at DESC,
                    wid DESC
                LIMIT ?
                """,
                (f"%{vin}%", vin, limit),
            ).fetchall()
            return {"items": rows_to_dicts(rows)}

    keyword = f"%{keyword_text}%"
    with db_session() as conn:
        rows = conn.execute(
            """
            SELECT wid, phone, nickname, real_name, vin, plate_no, store_name, level_name, member_card,
                   available_point, total_point, customer_status
            FROM customers
            WHERE deleted_at IS NULL
              AND (
                   phone LIKE ?
                OR wid LIKE ?
                OR nickname LIKE ?
                OR real_name LIKE ?
                OR vin LIKE ?
                OR plate_no LIKE ?
              )
            ORDER BY
                CASE
                    WHEN phone = ? THEN 0
                    WHEN wid = ? THEN 1
                    WHEN vin = ? THEN 2
                    WHEN plate_no = ? THEN 3
                    ELSE 4
                END,
                became_customer_at DESC,
                wid DESC
            LIMIT ?
            """,
            (
                keyword,
                keyword,
                keyword,
                keyword,
                keyword,
                keyword,
                keyword_text,
                keyword_text,
                normalize_vin(keyword_text),
                keyword_text,
                limit,
            ),
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
    require_role(request, {"admin", "super_admin"})
    with db_session() as conn:
        rows = conn.execute(
            """
            SELECT id, username, display_name, phone, store_id, store_name, role,
                   COALESCE(can_issue_renewal, 0) AS can_issue_renewal,
                   enabled,
                   created_at, registered_at, last_login_at, deleted_at
            FROM admin_users
            WHERE deleted_at IS NULL
            ORDER BY deleted_at IS NOT NULL, enabled DESC, store_name, display_name, phone
            """
        ).fetchall()
        items = rows_to_dicts(rows)
        for item in items:
            stores = admin_store_rows(conn, item.get("id"), item.get("store_id"), item.get("store_name"))
            item["stores"] = stores
            item["store_ids"] = [store.get("id") for store in stores]
            item["store_names"] = [store.get("name") for store in stores]
            item["store_name"] = join_text(item["store_names"]) or item.get("store_name")
            item["can_issue_renewal"] = item.get("role") == "super_admin" or bool(item.get("can_issue_renewal"))
        return {"items": items}


@app.post("/api/admin-users")
def create_admin_user(req: CreateAdminUserRequest, request: Request) -> dict:
    require_role(request, {"admin", "super_admin"})
    allowed_roles = {"issuer", "redeemer"}
    try:
        phone = normalize_phone(req.phone)
    except SmsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    name = req.name.strip()
    role = req.role.strip()
    if not name:
        raise HTTPException(status_code=400, detail="请输入姓名")
    if role not in allowed_roles:
        raise HTTPException(status_code=400, detail="只能新增发券人员或核销人员")

    with db_session() as conn:
        store = row_to_dict(
            conn.execute(
                "SELECT id, name FROM stores WHERE id = ? AND enabled = 1",
                (req.store_id.strip(),),
            ).fetchone()
        )
        if not store:
            raise HTTPException(status_code=400, detail="请选择有效门店")
        phone_auth = row_to_dict(
            conn.execute(
                """
                SELECT password_hash, registered_at
                FROM admin_users
                WHERE phone = ? AND enabled = 1 AND deleted_at IS NULL AND registered_at IS NOT NULL
                ORDER BY last_login_at DESC
                LIMIT 1
                """,
                (phone,),
            ).fetchone()
        ) or {}
        existing = row_to_dict(
            conn.execute(
                """
                SELECT *
                FROM admin_users
                WHERE phone = ? AND store_id = ? AND role = ?
                ORDER BY deleted_at IS NULL DESC
                LIMIT 1
                """,
                (phone, store["id"], role),
            ).fetchone()
        )
        if existing:
            if existing.get("deleted_at"):
                conn.execute(
                    """
                    UPDATE admin_users
                    SET username = ?, display_name = ?, phone = ?,
                        store_id = ?, store_name = ?, role = ?, can_issue_renewal = ?, enabled = 1,
                        password_hash = COALESCE(?, password_hash),
                        registered_at = COALESCE(?, registered_at),
                        deleted_at = NULL
                    WHERE id = ?
                    """,
                    (
                        unique_admin_username(conn, phone, existing["id"]),
                        name,
                        phone,
                        store["id"],
                        store["name"],
                        role,
                        1 if role == "issuer" and req.can_issue_renewal else 0,
                        phone_auth.get("password_hash"),
                        phone_auth.get("registered_at"),
                        existing["id"],
                    ),
                )
                replace_admin_user_stores(conn, existing["id"], [store])
                return {
                    "user": row_to_dict(conn.execute("SELECT * FROM admin_users WHERE id = ?", (existing["id"],)).fetchone()),
                    "created": False,
                    "restored": True,
                }
            raise HTTPException(status_code=400, detail="该手机号已存在")

        user_id = local_id("ADMIN_USER")
        while conn.execute("SELECT 1 FROM admin_users WHERE id = ?", (user_id,)).fetchone():
            user_id = local_id("ADMIN_USER")
        username_value = unique_admin_username(conn, phone)
        conn.execute(
            """
            INSERT INTO admin_users (
                id, username, password_hash, display_name, phone, store_id, store_name,
                role, can_issue_renewal, enabled, created_at, registered_at, last_login_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, NULL)
            """,
            (
                user_id,
                username_value,
                phone_auth.get("password_hash"),
                name,
                phone,
                store["id"],
                store["name"],
                role,
                1 if role == "issuer" and req.can_issue_renewal else 0,
                now_text(),
                phone_auth.get("registered_at"),
            ),
        )
        replace_admin_user_stores(conn, user_id, [store])
        return {
            "user": row_to_dict(conn.execute("SELECT * FROM admin_users WHERE id = ?", (user_id,)).fetchone()),
            "created": True,
        }


@app.patch("/api/admin-users/{user_id}")
def update_admin_user(user_id: str, req: UpdateAdminUserRequest, request: Request) -> dict:
    username = require_role(request, {"admin", "super_admin"})
    with db_session() as conn:
        operator_role = admin_role(conn, username)
        allowed_roles = {"issuer", "redeemer", "admin"} if operator_role == "super_admin" else {"issuer", "redeemer"}
        user = row_to_dict(conn.execute("SELECT * FROM admin_users WHERE id = ?", (user_id,)).fetchone())
        if not user:
            raise HTTPException(status_code=404, detail="人员不存在")
        if user.get("deleted_at"):
            raise HTTPException(status_code=400, detail="该人员已被删除")
        if user.get("role") == "super_admin":
            raise HTTPException(status_code=400, detail="超级管理员不能在这里修改")
        if operator_role != "super_admin" and user.get("role") == "admin":
            raise HTTPException(status_code=403, detail="管理员不能修改其他管理员")
        if req.role is not None:
            role = req.role.strip()
            if role not in allowed_roles:
                raise HTTPException(status_code=400, detail="当前账号不能分配该权限")
            conn.execute("UPDATE admin_users SET role = ? WHERE id = ?", (role, user_id))
            if role not in {"issuer", "admin"}:
                conn.execute("UPDATE admin_users SET can_issue_renewal = 0 WHERE id = ?", (user_id,))
        if req.enabled is not None:
            if user.get("username") == username and not req.enabled:
                raise HTTPException(status_code=400, detail="不能停用当前登录账号")
            conn.execute("UPDATE admin_users SET enabled = ? WHERE id = ?", (1 if req.enabled else 0, user_id))
        if req.can_issue_renewal is not None:
            effective_role = (req.role or user.get("role") or "").strip()
            if effective_role == "admin" and operator_role != "super_admin":
                raise HTTPException(status_code=403, detail="只有超级管理员可以调整管理员的续保券权限")
            conn.execute(
                "UPDATE admin_users SET can_issue_renewal = ? WHERE id = ?",
                (1 if effective_role in {"issuer", "admin"} and req.can_issue_renewal else 0, user_id),
            )
        return {"user": row_to_dict(conn.execute("SELECT * FROM admin_users WHERE id = ?", (user_id,)).fetchone())}


@app.delete("/api/admin-users/{user_id}")
def delete_admin_user(user_id: str, request: Request) -> dict:
    username = require_role(request, {"admin", "super_admin"})
    with db_session() as conn:
        operator_role = admin_role(conn, username)
        user = row_to_dict(conn.execute("SELECT * FROM admin_users WHERE id = ?", (user_id,)).fetchone())
        if not user:
            raise HTTPException(status_code=404, detail="人员不存在")
        if user.get("username") == username:
            raise HTTPException(status_code=400, detail="不能删除当前登录账号")
        if user.get("role") == "super_admin":
            raise HTTPException(status_code=400, detail="不能删除超级管理员")
        if operator_role != "super_admin" and user.get("role") == "admin":
            raise HTTPException(status_code=403, detail="管理员不能删除其他管理员")
        if user.get("deleted_at"):
            return {"user": user, "deleted": False}
        conn.execute(
            """
            UPDATE admin_users
            SET enabled = 0, registered_at = NULL, last_login_at = NULL, deleted_at = ?
            WHERE id = ?
            """,
            (now_text(), user_id),
        )
        return {
            "user": row_to_dict(conn.execute("SELECT * FROM admin_users WHERE id = ?", (user_id,)).fetchone()),
            "deleted": True,
        }


@app.post("/api/stores")
def create_store(req: CreateStoreRequest, request: Request) -> dict:
    require_role(request, {"admin", "super_admin"})
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
    require_role(request, {"admin", "super_admin"})
    with db_session() as conn:
        store = row_to_dict(conn.execute("SELECT * FROM stores WHERE id = ?", (store_id,)).fetchone())
        if not store:
            raise HTTPException(status_code=404, detail="门店不存在")
        if req.enabled is not None:
            conn.execute("UPDATE stores SET enabled = ? WHERE id = ?", (1 if req.enabled else 0, store_id))
        return {"store": row_to_dict(conn.execute("SELECT * FROM stores WHERE id = ?", (store_id,)).fetchone())}


@app.get("/api/templates")
def templates(request: Request, include_disabled: bool = False) -> dict:
    require_login(request)
    with db_session() as conn:
        where = "" if include_disabled else "WHERE enabled = 1"
        rows = conn.execute(
            f"SELECT * FROM coupon_templates {where} ORDER BY enabled DESC, name, id"
        ).fetchall()
        return {"items": rows_to_dicts(rows)}


@app.post("/api/templates")
def create_template(req: CreateTemplateRequest, request: Request) -> dict:
    operator = require_role(request, {"admin", "super_admin"})
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


@app.patch("/api/templates/{template_id}")
def update_template(template_id: str, req: UpdateTemplateRequest, request: Request) -> dict:
    operator = require_role(request, {"admin", "super_admin"})
    with db_session() as conn:
        template = row_to_dict(conn.execute("SELECT * FROM coupon_templates WHERE id = ?", (template_id,)).fetchone())
        if not template:
            raise HTTPException(status_code=404, detail="券模板不存在")
        updates = []
        params = []
        if req.name is not None:
            name = req.name.strip()
            if not name:
                raise HTTPException(status_code=400, detail="请输入券模板名称")
            updates.append("name = ?")
            params.append(name)
        if req.coupon_type is not None:
            updates.append("coupon_type = ?")
            params.append(req.coupon_type.strip() or "通用券")
        if req.rule_text is not None:
            updates.append("rule_text = ?")
            params.append(req.rule_text.strip())
        if req.enabled is not None:
            updates.append("enabled = ?")
            params.append(1 if req.enabled else 0)
        if updates:
            params.append(template_id)
            conn.execute(f"UPDATE coupon_templates SET {', '.join(updates)} WHERE id = ?", params)
            conn.execute(
                """
                INSERT INTO operation_logs (created_at, operator, action, customer_wid, target, quantity, remark)
                VALUES (?, ?, '修改券模板', NULL, ?, 1, ?)
                """,
                (now_text(), operator, template_id, req.rule_text or ""),
            )
        return {"template": row_to_dict(conn.execute("SELECT * FROM coupon_templates WHERE id = ?", (template_id,)).fetchone())}


@app.post("/api/coupons/issue")
def issue_coupon(req: IssueCouponRequest, request: Request) -> dict:
    username = require_role(request, {"admin", "super_admin", "issuer"})
    if req.quantity < 1 or req.quantity > 100:
        raise HTTPException(status_code=400, detail="发券数量必须在 1-100 之间")
    validity_type = (req.validity_type or "days").strip()
    if validity_type not in {"days", "unlimited"}:
        raise HTTPException(status_code=400, detail="有效期类型不正确")
    if validity_type == "days" and (req.valid_days < 1 or req.valid_days > 3650):
        raise HTTPException(status_code=400, detail="有效天数必须在 1-3650 之间")

    with db_session() as conn:
        admin_profile = current_admin_profile(conn, username)
        operation_store = select_admin_store(admin_profile, req.operation_store_id, req.operation_store_name)
        customer = require_customer(conn, req.wid)
        template = require_template(conn, req.template_id)
        if "续保" in str(template.get("name") or "") and not can_issue_renewal_coupon(admin_profile):
            raise HTTPException(status_code=403, detail="无发送“续保”券权限")
        start = datetime.now(APP_TZ).replace(tzinfo=None)
        issued_at = now_text()
        if validity_type == "unlimited":
            end = datetime(2099, 1, 1)
            valid_period = "永久有效"
        else:
            end = start + timedelta(days=req.valid_days)
            valid_period = f"{start:%Y-%m-%d} 至 {end:%Y-%m-%d}"
        issued = []
        usable_store_scope = req.usable_store_scope.strip() or "all"
        if usable_store_scope == "current":
            usable_store_ids = [operation_store.get("id") or ""]
            usable_store_names = [operation_store.get("name") or ""]
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
                "valid_period": valid_period,
                "valid_start": start.isoformat(),
                "valid_end": end.isoformat(),
                "phone": customer.get("phone"),
                "source": "manual",
                "remark": req.remark,
                "usable_store_scope": usable_store_scope,
                "usable_store_ids": join_text(usable_store_ids),
                "usable_store_names": join_text(usable_store_names),
                "issued_store_id": operation_store.get("id"),
                "issued_store_name": operation_store.get("name"),
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
    username = require_role(request, {"admin", "super_admin", "redeemer"})
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

        redeem_store = select_redeem_store(coupon, admin_profile, req.redeem_store_id, req.redeem_store_name)
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
                redeem_store.get("id"),
                redeem_store.get("name"),
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
            "redeemed_store_id": redeem_store.get("id"),
            "redeemed_store_name": redeem_store.get("name"),
            "redeemed_by_user_id": admin_profile.get("user_id"),
            "redeemed_by_name": admin_profile.get("name"),
            "redeemed_at": used_time,
        })
        return {"coupon": coupon}


@app.get("/api/coupons/{code}/preview")
def coupon_preview(code: str, request: Request) -> dict:
    username = require_login(request)
    coupon_code = code.strip()
    if not coupon_code:
        raise HTTPException(status_code=400, detail="请输入券码")

    with db_session() as conn:
        row = conn.execute(
            """
            SELECT cp.*,
                   c.phone AS customer_phone,
                   c.nickname AS customer_nickname,
                   c.real_name AS customer_real_name,
                   c.store_name AS customer_store_name
            FROM coupons cp
            LEFT JOIN customers c ON c.wid = cp.customer_wid
            WHERE cp.code = ?
            """,
            (coupon_code,),
        ).fetchone()
        coupon = row_to_dict(row)
        if not coupon:
            raise HTTPException(status_code=404, detail="券码不存在")
        coupon = apply_dynamic_coupon_status(coupon)
        admin_profile = current_admin_profile(conn, username)
        options = redeem_store_options(coupon, admin_profile)
        redeemable = coupon.get("status") == "unused" and bool(options)
        message = "" if redeemable else "当前账户所属门店不能核销该券"
        return {
            "coupon": coupon,
            "redeemable": redeemable,
            "redeem_store_options": options,
            "redeem_message": message,
            "message": message if coupon.get("status") == "unused" else f"该券当前不可核销: {coupon.get('status_text')}",
        }


@app.post("/api/coupons/void")
def void_coupon(req: VoidCouponRequest, request: Request) -> dict:
    username = require_role(request, {"admin", "super_admin", "issuer"})
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
    username = require_login(request)
    limit = max(1, min(limit, 500))
    with db_session() as conn:
        role = admin_role(conn, username)
        if role in {"admin", "super_admin"}:
            rows = conn.execute(
                "SELECT * FROM operation_logs ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        else:
            user = row_to_dict(
                conn.execute(
                    "SELECT username, display_name, phone FROM admin_users WHERE username = ?",
                    (username,),
                ).fetchone()
            )
            operator_names = {
                username,
                user.get("username") or "",
                user.get("display_name") or "",
                user.get("phone") or "",
            }
            operator_names = {name for name in operator_names if name}
            if not operator_names:
                return {"items": []}
            placeholders = ",".join("?" for _ in operator_names)
            rows = conn.execute(
                f"""
                SELECT * FROM operation_logs
                WHERE operator IN ({placeholders})
                ORDER BY id DESC
                LIMIT ?
                """,
                (*operator_names, limit),
            ).fetchall()
        return {"items": rows_to_dicts(rows)}


@app.get("/api/logs/export")
def export_logs(request: Request, from_date: str = "", to_date: str = "") -> FastAPIResponse:
    require_role(request, {"admin", "super_admin"})
    start_text, end_text = log_date_range(from_date, to_date)
    with db_session() as conn:
        rows = rows_to_dicts(
            conn.execute(
                """
                SELECT created_at, operator, action, customer_wid, target, quantity, remark
                FROM operation_logs
                WHERE created_at >= ? AND created_at <= ?
                ORDER BY created_at ASC, id ASC
                """,
                (start_text, end_text),
            ).fetchall()
        )

    output = io.StringIO()
    output.write("\ufeff")
    writer = csv.writer(output)
    writer.writerow(["时间", "操作人", "动作", "客户WID", "对象", "数量", "备注"])
    for row in rows:
        writer.writerow([
            row.get("created_at") or "",
            row.get("operator") or "",
            row.get("action") or "",
            row.get("customer_wid") or "",
            row.get("target") or "",
            row.get("quantity") if row.get("quantity") is not None else "",
            row.get("remark") or "",
        ])
    filename = f"operation_logs_{from_date}_{to_date}.csv"
    return FastAPIResponse(
        content=output.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/wechat/js-sdk-config")
def wechat_js_sdk_config(request: Request, url: str) -> dict:
    require_login(request)
    page_url = url.strip()
    if not page_url:
        raise HTTPException(status_code=400, detail="缺少页面地址")
    ticket = get_wechat_jsapi_ticket()
    nonce_str = secrets.token_hex(8)
    timestamp = int(time.time())
    raw = f"jsapi_ticket={ticket}&noncestr={nonce_str}&timestamp={timestamp}&url={page_url}"
    signature = hashlib.sha1(raw.encode("utf-8")).hexdigest()
    return {
        "appId": WECHAT_APPID,
        "timestamp": timestamp,
        "nonceStr": nonce_str,
        "signature": signature,
    }


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
