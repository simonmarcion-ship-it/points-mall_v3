from __future__ import annotations

import os
from pathlib import Path


WEB_DIR = Path(__file__).resolve().parents[1]
PROJECT_DIR = WEB_DIR.parent
DEFAULT_DATA_DIR = WEB_DIR / "data"


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


APP_ENV = os.getenv("MALL_ENV", "development")
DATA_DIR = Path(os.getenv("MALL_DATA_DIR", str(DEFAULT_DATA_DIR))).resolve()
DB_PATH = Path(os.getenv("MALL_DB_PATH", str(DATA_DIR / "mall.db"))).resolve()
CRAWLER_DIR = Path(os.getenv("MALL_CRAWLER_DIR", str(PROJECT_DIR / "crawler"))).resolve()
CRAWLER_V2_OUTPUT_DIR = Path(
    os.getenv("MALL_CRAWLER_V2_OUTPUT_DIR", str(PROJECT_DIR / "crawler_v2" / "output"))
).resolve()
AUTO_IMPORT = env_bool("MALL_AUTO_IMPORT", default=APP_ENV != "production")
SUPER_ADMIN_USERNAME = os.getenv("MALL_SUPER_ADMIN_USERNAME", "").strip()
SUPER_ADMIN_PASSWORD = os.getenv("MALL_SUPER_ADMIN_PASSWORD", "").strip()
ADMIN_USERNAME = os.getenv("MALL_ADMIN_USERNAME", "").strip()
ADMIN_PASSWORD = os.getenv("MALL_ADMIN_PASSWORD", "").strip()
ADMIN_REGISTER_INVITE_CODE = os.getenv("MALL_ADMIN_REGISTER_INVITE_CODE", "tianzijituan0525")
SESSION_SECRET = os.getenv("MALL_SESSION_SECRET", "dev-session-secret-change-me")
SESSION_COOKIE_NAME = os.getenv("MALL_SESSION_COOKIE_NAME", "points_mall_session")
SESSION_MAX_AGE_SECONDS = int(os.getenv("MALL_SESSION_MAX_AGE_SECONDS", "28800"))
COOKIE_SECURE = env_bool("MALL_COOKIE_SECURE", default=APP_ENV == "production")

CARGEER_ENABLED = env_bool("CARGEER_ENABLED", default=False)
CARGEER_ACCOUNT = os.getenv("CARGEER_ACCOUNT") or os.getenv("CARGEER_USERNAME", "")
CARGEER_PASSWORD = os.getenv("CARGEER_PASSWORD", "")
CARGEER_CAPTCHA_TOKEN = os.getenv("CARGEER_CAPTCHA_TOKEN") or os.getenv("JFBYM_TOKEN", "")
CARGEER_TIMEOUT = float(os.getenv("CARGEER_TIMEOUT", "15"))

WECHAT_APPID = os.getenv("WECHAT_APPID", "")
WECHAT_APPSECRET = os.getenv("WECHAT_APPSECRET", "")

SMS_ENABLED = env_bool("SMS_ENABLED", default=False)
SMS_PROVIDER = os.getenv("SMS_PROVIDER", "dev").strip().lower()
WEIWEBS_SMS_BASE_URL = os.getenv("WEIWEBS_SMS_BASE_URL", "https://www.weiwebs.cn/msg/HttpBatchSendSM")
WEIWEBS_SMS_ACCOUNT = os.getenv("WEIWEBS_SMS_ACCOUNT", "")
WEIWEBS_SMS_PASSWORD = os.getenv("WEIWEBS_SMS_PASSWORD", "")
WEIWEBS_SMS_SIGN_NAME = os.getenv("WEIWEBS_SMS_SIGN_NAME", "")
WEIWEBS_SMS_PRODUCT = os.getenv("WEIWEBS_SMS_PRODUCT", "")
WEIWEBS_SMS_AUTH_MODE = os.getenv("WEIWEBS_SMS_AUTH_MODE", "plain").strip().lower()
ALIYUN_ACCESS_KEY_ID = os.getenv("ALIYUN_ACCESS_KEY_ID") or os.getenv("ALIBABA_CLOUD_ACCESS_KEY_ID", "")
ALIYUN_ACCESS_KEY_SECRET = os.getenv("ALIYUN_ACCESS_KEY_SECRET") or os.getenv(
    "ALIBABA_CLOUD_ACCESS_KEY_SECRET",
    "",
)
ALIYUN_PNVS_SIGN_NAME = os.getenv("ALIYUN_PNVS_SIGN_NAME", "")
ALIYUN_PNVS_TEMPLATE_CODE = os.getenv("ALIYUN_PNVS_TEMPLATE_CODE", "")
ALIYUN_SMS_SIGN_NAME = os.getenv("ALIYUN_SMS_SIGN_NAME") or ALIYUN_PNVS_SIGN_NAME
ALIYUN_SMS_TEMPLATE_CODE = os.getenv("ALIYUN_SMS_TEMPLATE_CODE") or ALIYUN_PNVS_TEMPLATE_CODE
