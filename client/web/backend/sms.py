from __future__ import annotations

from datetime import datetime, timedelta
import hashlib
import json
import logging
import os
import re
import secrets
import urllib.error
import urllib.parse
import urllib.request

from .config import (
    ALIYUN_ACCESS_KEY_ID,
    ALIYUN_ACCESS_KEY_SECRET,
    ALIYUN_SMS_SIGN_NAME,
    ALIYUN_SMS_TEMPLATE_CODE,
    SMS_ENABLED,
    SMS_PROVIDER,
    WEIWEBS_SMS_ACCOUNT,
    WEIWEBS_SMS_BASE_URL,
    WEIWEBS_SMS_AUTH_MODE,
    WEIWEBS_SMS_PASSWORD,
    WEIWEBS_SMS_PRODUCT,
    WEIWEBS_SMS_SIGN_NAME,
)


PHONE_RE = re.compile(r"^1[3-9]\d{9}$")
logger = logging.getLogger(__name__)
PROXY_ENV_KEYS = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
)
_SMS_CODES: dict[str, tuple[str, datetime, int, datetime]] = {}


class SmsError(RuntimeError):
    pass


def normalize_phone(phone: str) -> str:
    value = "".join(ch for ch in str(phone or "") if ch.isdigit())
    if not PHONE_RE.match(value):
        raise SmsError("请输入正确的手机号")
    return value


def sms_configured() -> bool:
    if not SMS_ENABLED:
        return False
    if SMS_PROVIDER == "aliyun_sms":
        return all(
            [
                ALIYUN_ACCESS_KEY_ID,
                ALIYUN_ACCESS_KEY_SECRET,
                ALIYUN_SMS_SIGN_NAME,
                ALIYUN_SMS_TEMPLATE_CODE,
            ]
        )
    if SMS_PROVIDER == "weiwebs_http":
        return all([WEIWEBS_SMS_BASE_URL, WEIWEBS_SMS_ACCOUNT, WEIWEBS_SMS_PASSWORD, WEIWEBS_SMS_SIGN_NAME])
    return False


def _aliyun_client():
    for key in PROXY_ENV_KEYS:
        os.environ.pop(key, None)

    try:
        from alibabacloud_dysmsapi20170525.client import Client as DysmsapiClient
        from alibabacloud_tea_openapi import models as open_api_models
    except ImportError as exc:
        raise SmsError("短信 SDK 未安装，请先安装 alibabacloud_dysmsapi20170525") from exc

    config = open_api_models.Config(
        access_key_id=ALIYUN_ACCESS_KEY_ID,
        access_key_secret=ALIYUN_ACCESS_KEY_SECRET,
    )
    config.endpoint = "dysmsapi.aliyuncs.com"
    return DysmsapiClient(config)


def _cleanup_expired() -> None:
    now = datetime.now()
    expired = [phone for phone, (_, expires_at, _, _) in _SMS_CODES.items() if now > expires_at]
    for phone in expired:
        _SMS_CODES.pop(phone, None)


def _send_weiwebs_sms(phone: str, code: str) -> str:
    params = {
        "account": WEIWEBS_SMS_ACCOUNT,
        "pswd": WEIWEBS_SMS_PASSWORD,
        "mobile": phone,
        "msg": f"【{WEIWEBS_SMS_SIGN_NAME}】验证码：{code}，5分钟内有效。",
        "needstatus": "true",
        "resptype": "json",
    }
    if WEIWEBS_SMS_AUTH_MODE == "md5":
        ts = datetime.now().strftime("%Y%m%d%H%M%S")
        params["ts"] = ts
        params["pswd"] = hashlib.md5(
            f"{WEIWEBS_SMS_ACCOUNT}{WEIWEBS_SMS_PASSWORD}{ts}".encode("utf-8")
        ).hexdigest()
    if WEIWEBS_SMS_PRODUCT:
        params["product"] = WEIWEBS_SMS_PRODUCT

    body = urllib.parse.urlencode(params).encode("utf-8")
    request = urllib.request.Request(
        WEIWEBS_SMS_BASE_URL,
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            raw = response.read().decode("utf-8", errors="replace")
    except urllib.error.URLError as exc:
        raise SmsError(f"短信接口请求失败：{exc}") from exc

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.warning("Weiwebs SMS non-json response phone_suffix=%s response=%s", phone[-4:], raw[:200])
        raise SmsError("短信接口返回格式异常") from exc

    result = data.get("result")
    if str(result) != "0":
        logger.warning("Weiwebs SMS send failed phone_suffix=%s result=%s response=%s", phone[-4:], result, data)
        raise SmsError(f"短信发送失败，错误码：{result}")

    msgid = str(data.get("msgid") or "")
    logger.info("Weiwebs SMS send accepted phone_suffix=%s msgid=%s", phone[-4:], msgid)
    return msgid


def send_sms_code(phone: str) -> None:
    phone = normalize_phone(phone)
    if not sms_configured():
        raise SmsError("短信服务未配置")

    _cleanup_expired()
    existing = _SMS_CODES.get(phone)
    if existing:
        _, _, _, last_sent_at = existing
        seconds_since_last_send = (datetime.now() - last_sent_at).total_seconds()
        if seconds_since_last_send < 60:
            raise SmsError(f"请 {int(60 - seconds_since_last_send)} 秒后再获取验证码")

    code = f"{secrets.randbelow(1000000):06d}"

    if SMS_PROVIDER == "weiwebs_http":
        _send_weiwebs_sms(phone, code)
        now = datetime.now()
        _SMS_CODES[phone] = (code, now + timedelta(minutes=5), 0, now)
        return

    if SMS_PROVIDER != "aliyun_sms":
        raise SmsError("暂不支持的短信供应商")

    from alibabacloud_dysmsapi20170525 import models as dysmsapi_models
    from alibabacloud_tea_util import models as util_models

    request = dysmsapi_models.SendSmsRequest(
        phone_numbers=phone,
        sign_name=ALIYUN_SMS_SIGN_NAME,
        template_code=ALIYUN_SMS_TEMPLATE_CODE,
        template_param=json.dumps({"code": code, "min": "5"}, ensure_ascii=False),
    )
    response = _aliyun_client().send_sms_with_options(request, util_models.RuntimeOptions())
    body = getattr(response, "body", None)
    response_code = getattr(body, "code", None)
    if str(response_code).upper() != "OK":
        logger.warning(
            "Aliyun SMS send failed phone_suffix=%s code=%s message=%s template=%s sign=%s",
            phone[-4:],
            response_code,
            getattr(body, "message", None),
            ALIYUN_SMS_TEMPLATE_CODE,
            ALIYUN_SMS_SIGN_NAME,
        )
        raise SmsError(getattr(body, "message", None) or "短信发送失败")
    logger.info(
        "Aliyun SMS send accepted phone_suffix=%s biz_id=%s request_id=%s template=%s sign=%s",
        phone[-4:],
        getattr(body, "biz_id", None),
        getattr(body, "request_id", None),
        ALIYUN_SMS_TEMPLATE_CODE,
        ALIYUN_SMS_SIGN_NAME,
    )

    now = datetime.now()
    _SMS_CODES[phone] = (code, now + timedelta(minutes=5), 0, now)


def verify_sms_code(phone: str, code: str) -> bool:
    phone = normalize_phone(phone)
    code = str(code or "").strip()
    if not code:
        raise SmsError("请输入验证码")

    if not sms_configured():
        return code == "000000"

    if SMS_PROVIDER not in {"aliyun_sms", "weiwebs_http"}:
        raise SmsError("暂不支持的短信供应商")

    _cleanup_expired()
    record = _SMS_CODES.get(phone)
    if not record:
        return False

    expected, expires_at, attempts, last_sent_at = record
    if datetime.now() > expires_at:
        _SMS_CODES.pop(phone, None)
        return False

    if attempts >= 5:
        _SMS_CODES.pop(phone, None)
        return False

    if code == expected:
        _SMS_CODES.pop(phone, None)
        return True

    _SMS_CODES[phone] = (expected, expires_at, attempts + 1, last_sent_at)
    return False
