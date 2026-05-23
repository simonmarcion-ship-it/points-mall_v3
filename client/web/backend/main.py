from __future__ import annotations

from datetime import datetime
import ast
import json
import secrets
from urllib.parse import urlencode

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .config import DB_PATH, SESSION_COOKIE_NAME, WEB_DIR, WECHAT_APPID, WECHAT_OAUTH_REDIRECT_URI
from .cargeer import lookup_cargeer_by_phone
from .database import db_session, row_to_dict, rows_to_dicts
from .schema import create_client_schema


FRONTEND_DIR = WEB_DIR / "frontend"

app = FastAPI(title="天选好车主服务号客户端 API")


class BindPhoneRequest(BaseModel):
    phone: str
    sms_code: str
    nickname: str = ""


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def local_id(prefix: str) -> str:
    return f"{prefix}_{datetime.now():%Y%m%d%H%M%S}_{secrets.token_hex(3).upper()}"


def public_coupon_row(coupon: dict) -> dict:
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


def parse_raw_json(value: str | None) -> dict:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {}
    except (json.JSONDecodeError, TypeError):
        pass
    try:
        parsed = ast.literal_eval(value)
        return parsed if isinstance(parsed, dict) else {}
    except (ValueError, SyntaxError):
        return {}


def public_coupon_detail(coupon: dict, template: dict | None) -> dict:
    raw = parse_raw_json(coupon.get("raw_json"))
    detail = public_coupon_row(coupon)
    validity_text = coupon.get("valid_period") or " 至 ".join(
        str(value) for value in (coupon.get("valid_start"), coupon.get("valid_end")) if value
    )
    detail.update(
        {
            "rule_text": raw.get("使用规则") or (template or {}).get("rule_text") or "",
            "scope_text": coupon.get("usable_store_names") or raw.get("使用门店") or "",
            "usable_store_names": coupon.get("usable_store_names") or "",
            "validity_text": validity_text,
            "product_scope_text": validity_text,
            "discount_text": raw.get("优惠说明") or coupon.get("remark") or "",
            "template_id": coupon.get("template_id"),
        }
    )
    return detail


def current_customer_wid(request: Request) -> str | None:
    return request.cookies.get(SESSION_COOKIE_NAME)


def set_client_session(response: Response, wid: str) -> None:
    response.set_cookie(
        SESSION_COOKIE_NAME,
        wid,
        max_age=60 * 60 * 24 * 30,
        httponly=True,
        samesite="lax",
        path="/",
    )


def clear_client_session(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")


def get_customer_by_wid(conn, wid: str) -> dict | None:
    return row_to_dict(
        conn.execute(
            """
            SELECT wid, phone, nickname, store_name, level_name, member_card,
                   available_point, total_point, customer_status, avatar_url,
                   real_name, car_series, vin, purchase_store_name, plate_no
            FROM customers
            WHERE wid = ?
            """,
            (wid,),
        ).fetchone()
    )


def get_customer_by_phone(conn, phone: str) -> dict | None:
    return row_to_dict(
        conn.execute(
            """
            SELECT *
            FROM customers
            WHERE phone = ?
            ORDER BY became_customer_at DESC, wid DESC
            LIMIT 1
            """,
            (phone,),
        ).fetchone()
    )


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
    text = "".join(str(name or "").split())
    for token in STORE_MATCH_REMOVALS:
        text = text.replace(token, "")
    return "".join(ch for ch in text if ch.isalnum() or "\u4e00" <= ch <= "\u9fff")


def match_store_name(conn, store_name: str | None) -> str:
    source_key = store_match_key(store_name)
    if len(source_key) < 2:
        return ""

    rows = conn.execute(
        """
        SELECT name
        FROM stores
        WHERE enabled = 1
        ORDER BY customer_count DESC, name
        """
    ).fetchall()
    scored: list[tuple[int, str]] = []
    for row in rows:
        candidate_name = row["name"]
        candidate_key = store_match_key(candidate_name)
        if candidate_key == source_key:
            scored.append((100, candidate_name))
        elif len(source_key) >= 4 and source_key in candidate_key:
            scored.append((80, candidate_name))
        elif len(candidate_key) >= 4 and candidate_key in source_key:
            scored.append((70, candidate_name))

    if not scored:
        return ""
    scored.sort(reverse=True)
    best_score, best_name = scored[0]
    if len(scored) > 1 and scored[1][0] == best_score and scored[1][1] != best_name:
        return ""
    return best_name


def apply_store_match(conn, cargeer_fields: dict) -> dict:
    fields = dict(cargeer_fields)
    source_store = fields.get("store_name") or ""
    matched_store = match_store_name(conn, source_store)
    if matched_store:
        fields["store_name"] = matched_store
        fields["purchase_store_name"] = fields.get("purchase_store_name") or source_store
    return fields


def customer_needs_cargeer_enrichment(customer: dict) -> bool:
    if raw_json_should_replace(customer.get("raw_json")):
        return True
    if str(customer.get("vehicle_query_success") or "").lower() == "true":
        return False
    return any(
        not str(customer.get(field) or "").strip()
        for field in ("real_name", "car_series", "vin", "purchase_store_name", "plate_no")
    )


def raw_json_should_replace(value: str | None) -> bool:
    if not str(value or "").strip() or str(value or "").strip() == "{}":
        return True
    parsed = parse_raw_json(value)
    if not parsed:
        return False
    status = str(parsed.get("cargeer_status") or "").strip().lower()
    return parsed.get("source") == "client" and (
        status in {"disabled", "missing_config"} or status.startswith("error:")
    )


def update_customer_from_cargeer(conn, customer: dict, cargeer_fields: dict, cargeer_status: str) -> dict:
    fields = apply_store_match(conn, cargeer_fields)
    raw_json = json.dumps(
        fields.get("raw_json") or {"source": "client", "cargeer_status": cargeer_status},
        ensure_ascii=False,
    )
    current = customer
    conn.execute(
        """
        UPDATE customers
        SET
            nickname = CASE WHEN TRIM(COALESCE(nickname, '')) = '' THEN ? ELSE nickname END,
            store_name = CASE WHEN TRIM(COALESCE(store_name, '')) = '' THEN ? ELSE store_name END,
            member_card = CASE WHEN TRIM(COALESCE(member_card, '')) = '' THEN ? ELSE member_card END,
            level_name = CASE WHEN TRIM(COALESCE(level_name, '')) = '' THEN ? ELSE level_name END,
            real_name = CASE WHEN TRIM(COALESCE(real_name, '')) = '' THEN ? ELSE real_name END,
            car_series = CASE WHEN TRIM(COALESCE(car_series, '')) = '' THEN ? ELSE car_series END,
            vin = CASE WHEN TRIM(COALESCE(vin, '')) = '' THEN ? ELSE vin END,
            purchase_store_name = CASE WHEN TRIM(COALESCE(purchase_store_name, '')) = '' THEN ? ELSE purchase_store_name END,
            plate_no = CASE WHEN TRIM(COALESCE(plate_no, '')) = '' THEN ? ELSE plate_no END,
            vehicle_query_success = ?,
            vehicle_errcode = '',
            vehicle_errmsg = ?,
            raw_json = CASE WHEN ? THEN ? ELSE raw_json END
        WHERE wid = ?
        """,
        (
            fields.get("nickname") or fields.get("real_name") or "",
            fields.get("store_name") or "",
            fields.get("member_card"),
            fields.get("level_name") or "",
            fields.get("real_name") or "",
            fields.get("car_series") or "",
            fields.get("vin") or "",
            fields.get("purchase_store_name") or "",
            fields.get("plate_no") or "",
            "True",
            cargeer_status,
            1 if raw_json_should_replace(current.get("raw_json")) else 0,
            raw_json,
            current["wid"],
        ),
    )
    return get_customer_by_wid(conn, current["wid"]) or current


def mark_customer_cargeer_status(conn, wid: str, status: str) -> None:
    current = row_to_dict(conn.execute("SELECT raw_json FROM customers WHERE wid = ?", (wid,)).fetchone()) or {}
    conn.execute(
        """
        UPDATE customers
        SET vehicle_query_success = 'False',
            vehicle_errmsg = ?,
            raw_json = CASE WHEN ? THEN ? ELSE raw_json END
        WHERE wid = ?
        """,
        (
            status,
            1 if raw_json_should_replace(current.get("raw_json")) else 0,
            json.dumps({"source": "client", "cargeer_status": status}, ensure_ascii=False),
            wid,
        ),
    )


def enrich_customer_from_cargeer_task(wid: str, phone: str) -> None:
    cargeer_lookup, cargeer_status = lookup_cargeer_by_phone(phone)
    with db_session() as conn:
        customer = row_to_dict(conn.execute("SELECT * FROM customers WHERE wid = ?", (wid,)).fetchone())
        if not customer or not customer_needs_cargeer_enrichment(customer):
            return
        if cargeer_lookup:
            update_customer_from_cargeer(conn, customer, cargeer_lookup.as_customer_fields(), cargeer_status)
        else:
            mark_customer_cargeer_status(conn, wid, "not_found" if cargeer_status == "ok" else cargeer_status)


@app.on_event("startup")
def startup() -> None:
    with db_session() as conn:
        create_client_schema(conn)


@app.get("/api/client/config")
def client_config() -> dict:
    return {
        "database": str(DB_PATH),
        "wechat_configured": bool(WECHAT_APPID),
        "mode": "development",
    }


@app.get("/api/client/wechat/start")
def wechat_start() -> RedirectResponse:
    if not WECHAT_APPID or not WECHAT_OAUTH_REDIRECT_URI:
        return RedirectResponse(url="/?dev=1")

    query = urlencode(
        {
            "appid": WECHAT_APPID,
            "redirect_uri": WECHAT_OAUTH_REDIRECT_URI,
            "response_type": "code",
            "scope": "snsapi_userinfo",
            "state": secrets.token_urlsafe(12),
        }
    )
    return RedirectResponse(url=f"https://open.weixin.qq.com/connect/oauth2/authorize?{query}#wechat_redirect")


@app.get("/api/client/wechat/callback")
def wechat_callback(code: str = "", state: str = "") -> dict:
    if not code:
        raise HTTPException(status_code=400, detail="缺少微信授权 code")
    return {
        "status": "placeholder",
        "message": "这里后续用 code 换取 openid/unionid，再查询或创建绑定关系。",
        "code_received": bool(code),
        "state": state,
    }


@app.get("/api/client/me")
def client_me(request: Request) -> dict:
    wid = current_customer_wid(request)
    if not wid:
        raise HTTPException(status_code=401, detail="请先绑定手机号")

    with db_session() as conn:
        customer = get_customer_by_wid(conn, wid)
        if not customer:
            raise HTTPException(status_code=404, detail="客户不存在")
        return {"customer": customer}


@app.get("/api/client/coupons")
def client_coupons(request: Request) -> dict:
    wid = current_customer_wid(request)
    if not wid:
        raise HTTPException(status_code=401, detail="请先绑定手机号")

    with db_session() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM coupons
            WHERE customer_wid = ?
              AND status != 'voided'
            ORDER BY
                CASE status WHEN 'unused' THEN 0 WHEN 'used' THEN 1 ELSE 2 END,
                receive_time DESC,
                code DESC
            """,
            (wid,),
        ).fetchall()
        return {"items": [public_coupon_row(row) for row in rows_to_dicts(rows)]}


@app.get("/api/client/coupons/{code}")
def client_coupon_detail(code: str, request: Request) -> dict:
    wid = current_customer_wid(request)
    if not wid:
        raise HTTPException(status_code=401, detail="请先绑定手机号")

    with db_session() as conn:
        coupon = row_to_dict(
            conn.execute(
                """
                SELECT *
                FROM coupons
                WHERE code = ? AND customer_wid = ? AND status != 'voided'
                """,
                (code.strip(), wid),
            ).fetchone()
        )
        if not coupon:
            raise HTTPException(status_code=404, detail="没有找到该优惠券")

        template = row_to_dict(
            conn.execute(
                "SELECT * FROM coupon_templates WHERE id = ?",
                (coupon.get("template_id"),),
            ).fetchone()
        )
        return {"coupon": public_coupon_detail(coupon, template)}


@app.post("/api/client/logout")
def client_logout(response: Response) -> dict:
    clear_client_session(response)
    return {"ok": True}


@app.post("/api/client/bind-phone-legacy")
def bind_phone(req: BindPhoneRequest, response: Response) -> dict:
    phone = req.phone.strip()
    if not phone:
        raise HTTPException(status_code=400, detail="请输入手机号")

    # 骨架阶段先允许 000000 作为本地测试验证码；正式环境必须接短信服务。
    if req.sms_code.strip() != "000000":
        raise HTTPException(status_code=400, detail="开发阶段验证码请填写 000000")

    with db_session() as conn:
        customer = get_customer_by_phone(conn, phone)
        created = False
        if not customer:
            wid = f"LOCAL_CUSTOMER_{phone}"
            created = True
            conn.execute(
                """
                INSERT INTO customers (
                    wid, phone, nickname, gender, birthday, avatar_url, became_customer_at,
                    store_name, channel, member_card, level_name, joined_at, black_user,
                    customer_status, available_point, total_point, frozen_point,
                    available_balance, frozen_balance, total_balance, raw_json
                ) VALUES (?, ?, ?, '', '', NULL, ?, '', '服务号客户端', NULL, '', ?, 'False',
                          '本地客户', '0', '0', '0', '0', '0', '0', '{}')
                """,
                (wid, phone, req.nickname.strip(), now_text(), now_text()),
            )
            customer = get_customer_by_wid(conn, wid)

        if not customer:
            raise HTTPException(status_code=500, detail="绑定客户失败")

        set_client_session(response, customer["wid"])
        return {"customer": customer, "created": created}


@app.post("/api/client/bind-phone")
def bind_phone_with_cargeer(req: BindPhoneRequest, response: Response, background_tasks: BackgroundTasks) -> dict:
    phone = req.phone.strip()
    if not phone:
        raise HTTPException(status_code=400, detail="请输入手机号")

    # 本地骨架阶段允许 000000 作为测试验证码；正式环境需要接短信服务。
    if req.sms_code.strip() != "000000":
        raise HTTPException(status_code=400, detail="开发阶段验证码请填写 000000")

    with db_session() as conn:
        customer = get_customer_by_phone(conn, phone)
        created = False
        should_enrich = bool(customer and customer_needs_cargeer_enrichment(customer))

        if not customer:
            wid = local_id("LOCAL_CUSTOMER")
            while conn.execute("SELECT 1 FROM customers WHERE wid = ?", (wid,)).fetchone():
                wid = local_id("LOCAL_CUSTOMER")

            raw_json = json.dumps({"source": "client", "cargeer_status": "queued"}, ensure_ascii=False)
            created = True
            should_enrich = True
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
                ) VALUES (?, ?, ?, '', '', NULL, ?, '', '服务号客户端', NULL, '', ?, 'False',
                          '本地客户', '0', '0', '0', '0', '0', '0',
                          '', '', '', '', '', 'False', '', 'queued', ?)
                """,
                (
                    wid,
                    phone,
                    req.nickname.strip(),
                    now_text(),
                    now_text(),
                    raw_json,
                ),
            )
            customer = get_customer_by_wid(conn, wid)

        if not customer:
            raise HTTPException(status_code=500, detail="绑定客户失败")

        if should_enrich:
            background_tasks.add_task(enrich_customer_from_cargeer_task, customer["wid"], phone)

        set_client_session(response, customer["wid"])
        return {"customer": customer, "created": created, "cargeer_status": "queued" if should_enrich else "not_needed"}


app.mount("/assets", StaticFiles(directory=FRONTEND_DIR), name="assets")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/{path:path}")
def spa_fallback(path: str) -> FileResponse:
    if path.startswith("api/"):
        raise HTTPException(status_code=404, detail="接口不存在，请确认后端服务已重启")
    candidate = FRONTEND_DIR / path
    if candidate.exists() and candidate.is_file():
        return FileResponse(candidate)
    return FileResponse(FRONTEND_DIR / "index.html")
