from __future__ import annotations

import base64
import json
import logging
import random
import re

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


def text(value: object) -> str:
    return str(value or "").strip()


def normalize_vin(value: object) -> str:
    return re.sub(r"\s+", "", text(value)).upper()


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


def member_query_payload(rp_token: str, phone: str) -> dict:
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
        "FILTERMAP": json.dumps(
            {
                "ALL": [],
                "PHONE": [phone],
                "NAME": [],
                "VIN": [],
                "PLATENUMBER": [],
                "ENGINENUMBER": [],
                "NUMBER": [],
                "CARDID": [],
            },
            ensure_ascii=False,
        ),
    }


def vehicle_model(row: dict, member: dict) -> str:
    direct = text(row.get("品牌车型"))
    if direct:
        return direct
    brand = text(row.get("BRANDNAME") or member.get("BRANDNAME"))
    series = text(row.get("SERIESNAME") or member.get("SERIESNAME"))
    brand_series = " ".join(part for part in [brand, series] if part)
    return brand_series or text(row.get("MODELNAME") or member.get("MODELNAME"))


def option_from_vehicle(member: dict, detail: dict, vehicle: dict, index: int) -> dict:
    real_name = text(detail.get("NAME") or detail.get("姓名") or member.get("NAME"))
    store_name = text(
        detail.get("ORGUNITNAME")
        or detail.get("所属门店")
        or detail.get("JOINORGUNITNAME")
        or detail.get("入会门店")
        or member.get("ORGUNITNAME")
    )
    phone = text(detail.get("PHONE") or detail.get("手机号") or member.get("PHONE"))
    plate_no = text(vehicle.get("车牌号") or vehicle.get("PLATENUMBER") or vehicle.get("PLATENUM") or member.get("PLATENUMBER"))
    car_series = vehicle_model(vehicle, member)
    vin = normalize_vin(vehicle.get("车架号") or vehicle.get("VIN") or vehicle.get("vin") or member.get("VIN"))
    return {
        "source": "cargeer",
        "index": index,
        "phone": phone,
        "nickname": real_name,
        "real_name": real_name,
        "store_name": store_name,
        "purchase_store_name": store_name,
        "level_name": text(detail.get("LEVELNAME") or detail.get("会员等级") or member.get("LEVELNAME")),
        "member_card": text(detail.get("NUMBER") or member.get("NUMBER")),
        "car_series": car_series,
        "vin": vin,
        "plate_no": plate_no,
        "consultant_name": text(
            detail.get("SELLERNAME")
            or detail.get("当前顾问")
            or detail.get("CONSULTANTNAME")
            or detail.get("服务顾问")
            or member.get("SELLERNAME")
            or member.get("CONSULTANTNAME")
        ),
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
        response = self.session.post(
            "http://api.jfbym.com/api/YmServer/customApi",
            headers={"Content-Type": "application/json"},
            json={"token": CARGEER_CAPTCHA_TOKEN, "type": "10110", "image": image_b64},
            timeout=CARGEER_TIMEOUT,
        )
        response.raise_for_status()
        result = response.json()
        data = result.get("data") if isinstance(result, dict) else None
        code = (data or {}).get("data") if isinstance(data, dict) else ""
        code = code or (result.get("result") if isinstance(result, dict) else "")
        if not code:
            raise RuntimeError("captcha recognition returned empty code")
        return str(code).strip().replace(" ", "").replace("\n", "")

    def get_base_token(self) -> str:
        session = self.init_session()
        verify_code = self.recognize_captcha(self.fetch_captcha(session))
        response = session.post(
            LOGIN_API,
            headers={**ajax_headers(LOGIN_PAGE, origin="https://cargeer.com"), "Referer": LOGIN_PAGE},
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
        return token

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

    def lookup_member(self, rp_token: str, phone: str) -> dict | None:
        response = self.session.post(
            MEMBER_QUERY_URL,
            headers=ajax_headers("https://vip2.cargeer.com/autorep/rep/sys/manager/member/view"),
            data=member_query_payload(rp_token, phone),
            timeout=CARGEER_TIMEOUT,
        )
        response.raise_for_status()
        records = response.json().get("data", []) or []
        return records[0] if records else None

    def get_detail(self, rp_token: str, member_id: str, card_number: str) -> dict:
        if not (member_id and card_number):
            return {}
        response = self.session.post(
            DETAIL_URL,
            headers=ajax_headers("https://vip2.cargeer.com/autorep/rep/sys/manager/member-view/view"),
            data={"ID": member_id, "NUMBER": card_number, "REP_SESSION_TOKEN": rp_token},
            timeout=CARGEER_TIMEOUT,
        )
        response.raise_for_status()
        rows = (response.json().get("data", {}) or {}).get("MEMBER") or []
        return rows[0] if rows else {}

    def get_vehicles(self, rp_token: str, member_id: str) -> list[dict]:
        if not member_id:
            return []
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

    def lookup_options_by_phone(self, phone: str) -> list[dict]:
        base_token = self.get_base_token()
        rp_token = self.get_rp_token(base_token)
        member = self.lookup_member(rp_token, phone)
        if not member:
            return []
        detail = self.get_detail(rp_token, text(member.get("ID")), text(member.get("NUMBER")))
        vehicles = self.get_vehicles(rp_token, text(member.get("ID"))) or [{}]
        return [option_from_vehicle(member, detail, vehicle, index) for index, vehicle in enumerate(vehicles)]


def lookup_cargeer_options_by_phone(phone: str) -> tuple[list[dict], str]:
    if not CARGEER_ENABLED:
        return [], "disabled"
    if not (CARGEER_ACCOUNT and CARGEER_PASSWORD and CARGEER_CAPTCHA_TOKEN):
        return [], "missing_config"
    try:
        return CargeerClient().lookup_options_by_phone(phone), "ok"
    except Exception as exc:
        LOGGER.warning("Cargeer admin lookup failed for phone %s: %s", phone, exc)
        return [], f"error: {exc}"
