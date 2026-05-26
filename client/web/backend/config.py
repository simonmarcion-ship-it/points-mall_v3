from __future__ import annotations

import os
from pathlib import Path


WEB_DIR = Path(__file__).resolve().parents[1]
CLIENT_DIR = WEB_DIR.parent
PROJECT_DIR = CLIENT_DIR.parent

DEFAULT_DB_PATH = PROJECT_DIR / "admin" / "web" / "data" / "mall.db"

APP_ENV = os.getenv("CLIENT_ENV", "development")
DB_PATH = Path(os.getenv("CLIENT_DB_PATH", str(DEFAULT_DB_PATH))).resolve()
WECHAT_APPID = os.getenv("WECHAT_APPID", "")
WECHAT_APPSECRET = os.getenv("WECHAT_APPSECRET", "")
WECHAT_OAUTH_REDIRECT_URI = os.getenv("WECHAT_OAUTH_REDIRECT_URI", "")
SESSION_COOKIE_NAME = os.getenv("CLIENT_SESSION_COOKIE_NAME", "tx_client_session")

CARGEER_ENABLED = os.getenv("CARGEER_ENABLED", "0").strip().lower() in {"1", "true", "yes", "on"}
CARGEER_ACCOUNT = os.getenv("CARGEER_ACCOUNT") or os.getenv("CARGEER_USERNAME", "")
CARGEER_PASSWORD = os.getenv("CARGEER_PASSWORD", "")
CARGEER_CAPTCHA_TOKEN = os.getenv("CARGEER_CAPTCHA_TOKEN") or os.getenv("JFBYM_TOKEN", "")
CARGEER_TIMEOUT = float(os.getenv("CARGEER_TIMEOUT", "15"))

SMS_ENABLED = os.getenv("SMS_ENABLED", "0").strip().lower() in {"1", "true", "yes", "on"}
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
ALIYUN_PNVS_REGION_ID = os.getenv("ALIYUN_PNVS_REGION_ID", "cn-hangzhou")
ALIYUN_PNVS_SIGN_NAME = os.getenv("ALIYUN_PNVS_SIGN_NAME", "")
ALIYUN_PNVS_TEMPLATE_CODE = os.getenv("ALIYUN_PNVS_TEMPLATE_CODE", "")
ALIYUN_PNVS_SCENE_CODE = os.getenv("ALIYUN_PNVS_SCENE_CODE", "")
ALIYUN_SMS_SIGN_NAME = os.getenv("ALIYUN_SMS_SIGN_NAME") or ALIYUN_PNVS_SIGN_NAME
ALIYUN_SMS_TEMPLATE_CODE = os.getenv("ALIYUN_SMS_TEMPLATE_CODE") or ALIYUN_PNVS_TEMPLATE_CODE
