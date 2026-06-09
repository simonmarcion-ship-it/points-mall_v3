from __future__ import annotations

import base64
import json
import logging
import random
import re
from dataclasses import dataclass, field

import requests

from .config import (
    CARGEER_ACCOUNT,
    CARGEER_CAPTCHA_TOKEN,
    CARGEER_ENABLED,
    CARGEER_PASSWORD,
    CARGEER_TIMEOUT,
)


LOGGER = logging.getLogger(__name__)

LOGIN_PAGE = "https://cargeer.com/autobase/base/system/login/view"
CAPTCHA_URL = "https://cargeer.com/autobase/sys/manager/login/verifycode"
LOGIN_API = "https://cargeer.com/autobase/sys/manager/login/get"
IFRAME_URL = "https://vip2.cargeer.com/autorep/rep/sys/manager/iframemain/view"
MEMBER_QUERY_URL = "https://vip2.cargeer.com/autorep/rep/sys/manager/member/query"
VEHICLE_QUERY_URL = "https://vip2.cargeer.com/autorep/rep/sys/manager/member/queryvehicle"
DETAIL_URL = "https://vip2.cargeer.com/autorep/rep/sys/manager/member/getdetail"

BASE_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "Pragma": "no-cache",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36",
}


def ajax_headers(referer: str, origin: str = "https://vip2.cargeer.com") -> dict:
    return {
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "Origin": origin,
        "Pragma": "no-cache",
        "Referer": referer,
        "User-Agent": BASE_HEADERS["User-Agent"],
        "X-Requested-With": "XMLHttpRequest",
    }


@dataclass
class CargeerLookup:
    real_name: str = ""
    phone: str = ""
    store_name: str = ""
    level_name: str = ""
    member_id: str = ""
    card_number: str = ""
    plate_no: str = ""
    vin: str = ""
    car_series: str = ""
    raw_member: dict | None = None
    raw_detail: dict | None = None
    raw_vehicle: dict | None = None
    vehicles: list[dict] = field(default_factory=list)

    def as_customer_fields(self) -> dict:
        return {
            "real_name": self.real_name,
            "nickname": self.real_name,
            "store_name": self.store_name,
            "level_name": self.level_name,
            "member_card": self.card_number,
            "plate_no": self.plate_no,
            "vin": self.vin,
            "car_series": self.car_series,
            "purchase_store_name": self.store_name,
            "raw_json": {
                "source": "cargeer",
                "member_id": self.member_id,
                "card_number": self.card_number,
                "member": self.raw_member or {},
                "detail": self.raw_detail or {},
                "vehicle": self.raw_vehicle or {},
                "vehicles": self.vehicles,
            },
            "vehicles": self.vehicles,
        }


class CargeerClient:
    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.trust_env = False

    def init_session(self) -> requests.Session:
        session = requests.Session()
        session.trust_env = False
        session.headers.update(BASE_HEADERS)
        session.get(LOGIN_PAGE, timeout=CARGEER_TIMEOUT)
        return session

    def fetch_captcha(self, session: requests.Session) -> str:
        response = session.get(
            CAPTCHA_URL,
            params={"r": f"{random.random():.16f}"},
            headers={"Referer": LOGIN_PAGE, **BASE_HEADERS},
            timeout=CARGEER_TIMEOUT,
        )
        response.raise_for_status()
        return base64.b64encode(response.content).decode()

    def recognize_captcha(self, image_b64: str) -> str:
        if not CARGEER_CAPTCHA_TOKEN:
            raise RuntimeError("CARGEER_CAPTCHA_TOKEN is not configured")
        response = self.session.post(
            "http://api.jfbym.com/api/YmServer/customApi",
            headers={"Content-Type": "application/json"},
            json={"token": CARGEER_CAPTCHA_TOKEN, "type": "10110", "image": image_b64},
            timeout=CARGEER_TIMEOUT,
        )
        response.raise_for_status()
        result = response.json()
        code = ""
        if isinstance(result, dict):
            data = result.get("data")
            if isinstance(data, dict):
                code = data.get("data") or ""
            code = code or result.get("result") or ""
        if not code:
            raise RuntimeError("captcha recognition returned empty code")
        return str(code).strip().replace(" ", "").replace("\n", "")

    def get_base_token(self) -> tuple[str, str | None]:
        session = self.init_session()
        verify_code = self.recognize_captcha(self.fetch_captcha(session))
        response = session.post(
            LOGIN_API,
            headers={
                **ajax_headers(LOGIN_PAGE, origin="https://cargeer.com"),
                "Referer": LOGIN_PAGE,
            },
            data={
                "LOGINID": CARGEER_ACCOUNT,
                "PASSWORD": CARGEER_PASSWORD,
                "VERIFYCODE": verify_code,
                "ISUSE": "1",
            },
            timeout=CARGEER_TIMEOUT,
        )
        response.raise_for_status()
        payload = response.json()
        if not payload.get("success"):
            raise RuntimeError("Cargeer login failed")
        token = payload.get("BASE_SESSION_TOKEN")
        if not token:
            raise RuntimeError("Cargeer login response missing BASE_SESSION_TOKEN")
        return token, session.cookies.get("JSESSIONID")

    def get_rp_token(self, base_token: str) -> str:
        response = self.session.post(
            IFRAME_URL,
            headers={
                **BASE_HEADERS,
                "Content-Type": "application/x-www-form-urlencoded",
                "Origin": "https://cargeer.com",
                "Referer": "https://cargeer.com/",
            },
            data={"BASE_SESSION_TOKEN": base_token},
            timeout=CARGEER_TIMEOUT,
        )
        response.raise_for_status()
        match = re.search(
            r'name=["\']REP_SESSION_TOKEN["\'][^>]*value=["\']([\w-]+)["\']',
            response.text,
            flags=re.IGNORECASE,
        )
        if not match:
            raise RuntimeError("Cargeer iframe response missing REP_SESSION_TOKEN")
        return match.group(1)

    def get_single_with_phone(self, rp_token: str, phone: str) -> dict | None:
        response = self.session.post(
            MEMBER_QUERY_URL,
            headers=ajax_headers("https://vip2.cargeer.com/autorep/rep/sys/manager/member/view"),
            data={**member_query_payload(rp_token), "FILTERMAP": json.dumps(filter_map(phone=phone), ensure_ascii=False)},
            timeout=CARGEER_TIMEOUT,
        )
        response.raise_for_status()
        payload = response.json()
        records = payload.get("data", []) or []
        return records[0] if records else None

    def get_vehicles(self, rp_token: str, member_id: str) -> list[dict]:
        response = self.session.post(
            VEHICLE_QUERY_URL,
            headers=ajax_headers("https://vip2.cargeer.com/autorep/rep/sys/manager/member-view/view"),
            data={
                "REP_SESSION_TOKEN": rp_token,
                "IDISPLAYSTART": "0",
                "IDISPLAYLENGTH": "10",
                "SIMPLEQUERY": "true",
                "CONDITIONKEY": "REPAIRPROJECT_BASE",
                "GETCONDITIONFLAG": "true",
                "FILTER": "",
                "MODELNAME": "",
                "MODELID": "",
                "BRANDID": "",
                "SERIESID": "",
                "MEMBERID": member_id,
            },
            timeout=CARGEER_TIMEOUT,
        )
        response.raise_for_status()
        return response.json().get("data", []) or []

    def get_detail(self, rp_token: str, member_id: str, card_number: str) -> dict:
        response = self.session.post(
            DETAIL_URL,
            headers=ajax_headers("https://vip2.cargeer.com/autorep/rep/sys/manager/member-view/view"),
            data={"ID": member_id, "NUMBER": card_number, "REP_SESSION_TOKEN": rp_token},
            timeout=CARGEER_TIMEOUT,
        )
        response.raise_for_status()
        data = response.json().get("data", {}) or {}
        rows = data.get("MEMBER") or []
        return rows[0] if rows else {}

    def lookup_by_phone(self, phone: str) -> CargeerLookup | None:
        base_token, _ = self.get_base_token()
        rp_token = self.get_rp_token(base_token)
        member = self.get_single_with_phone(rp_token, phone)
        if not member:
            return None

        member_id = str(member.get("ID") or "")
        card_number = str(member.get("NUMBER") or "")
        detail = self.get_detail(rp_token, member_id, card_number) if member_id and card_number else {}
        vehicles = self.get_vehicles(rp_token, member_id) if member_id else []
        vehicle = first_vehicle(vehicles)
        vehicle_options = vehicle_rows(vehicles, detail, member)

        return CargeerLookup(
            real_name=text(detail.get("NAME") or member.get("NAME")),
            phone=text(detail.get("PHONE") or member.get("PHONE") or phone),
            store_name=text(detail.get("ORGUNITNAME") or member.get("ORGUNITNAME")),
            level_name=text(detail.get("LEVELNAME") or member.get("LEVELNAME")),
            member_id=member_id,
            card_number=card_number,
            plate_no=text(vehicle.get("PLATENUMBER") or vehicle.get("PLATENUM")),
            vin=normalize_vin(vehicle.get("VIN") or vehicle.get("vin")),
            car_series=vehicle_series(vehicle),
            raw_member=member,
            raw_detail=detail,
            raw_vehicle=vehicle,
            vehicles=vehicle_options,
        )


def text(value: object) -> str:
    return str(value or "").strip()


def normalize_vin(value: object) -> str:
    return re.sub(r"\s+", "", text(value)).upper()


def vehicle_series(vehicle: dict) -> str:
    return " ".join(part for part in [text(vehicle.get("BRANDNAME")), text(vehicle.get("SERIESNAME"))] if part)


def first_vehicle(rows: list[dict]) -> dict:
    for row in rows:
        if text(row.get("VIN") or row.get("vin")) or text(row.get("PLATENUMBER") or row.get("PLATENUM")):
            return row
    return rows[0] if rows else {}


def vehicle_rows(rows: list[dict], detail: dict, member: dict) -> list[dict]:
    output = []
    store_name = text(detail.get("ORGUNITNAME") or member.get("ORGUNITNAME"))
    for index, row in enumerate(rows or []):
        output.append(
            {
                "index": index,
                "vin": normalize_vin(row.get("VIN") or row.get("vin")),
                "plate_no": text(row.get("PLATENUMBER") or row.get("PLATENUM")),
                "car_series": vehicle_series(row),
                "purchase_store_name": store_name,
                "raw_json": row,
            }
        )
    return output


def member_query_payload(rp_token: str) -> dict:
    return {
        "REP_SESSION_TOKEN": rp_token,
        "IDISPLAYSTART": "0",
        "IDISPLAYLENGTH": "20",
        "CONDITIONKEY": "MEMBER_BASE",
        "FILTER": "",
        "LEVELNAME": "",
        "LEVELID": "",
        "SELLERNAME_LIST": "",
        "SELLERID_LIST": "",
        "INSURANCEPERSONNAME_LIST": "",
        "INSURANCEPERSONID_LIST": "",
        "CONSULTANTNAME_LIST": "",
        "CONSULTANTID_LIST": "",
        "DATAPICKER_JOINTIME": "",
        "JOINTIME_START_DATE": "",
        "JOINTIME_END_DATE": "",
        "DATAPICKER_BIRTHDAY": "",
        "BIRTHDAY_START_DATE": "",
        "BIRTHDAY_END_DATE": "",
        "DATAPICKER_CREATETIME": "",
        "CREATETIME_START_DATE": "",
        "CREATETIME_END_DATE": "",
        "DATAPICKER_BUYTIME": "",
        "BUYTIME_START_DATE": "",
        "BUYTIME_END_DATE": "",
        "DATAPICKER_LASTCOMEDATE": "",
        "LASTCOMEDATE_START_DATE": "",
        "LASTCOMEDATE_END_DATE": "",
        "MODELNAME": "",
        "MODELID": "",
        "SERIESID": "",
        "BRANDID": "",
        "ORGUNITNAME_LIST": "",
        "ORGUNITID_LIST": "",
        "CREATORNAME_LIST": "",
        "CREATORID_LIST": "",
        "INCOMEINTERVAL_LIST": "",
        "ISIDENTIFY": "",
        "STATUS_LIST": "",
        "TAGNAME_LIST": "",
        "TAGID_LIST": "",
        "MEMBERCLASSLONGNUMBER": "001",
        "INDUSTRYNAME_LIST": "",
        "INDUSTRYID_LIST": "",
        "MEMBERSTATUS_LIST": "",
        "ISLOCK_LIST": "",
    }


def filter_map(phone: str = "") -> dict:
    return {
        "ALL": [],
        "PHONE": [phone] if phone else [],
        "NAME": [],
        "VIN": [],
        "PLATENUMBER": [],
        "ENGINENUMBER": [],
        "NUMBER": [],
        "CARDID": [],
    }


def lookup_cargeer_by_phone(phone: str) -> tuple[CargeerLookup | None, str]:
    if not CARGEER_ENABLED:
        return None, "disabled"
    if not (CARGEER_ACCOUNT and CARGEER_PASSWORD and CARGEER_CAPTCHA_TOKEN):
        return None, "missing_config"
    try:
        return CargeerClient().lookup_by_phone(phone), "ok"
    except Exception as exc:
        LOGGER.warning("Cargeer lookup failed for phone %s: %s", phone, exc)
        return None, f"error: {exc}"
