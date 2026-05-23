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
