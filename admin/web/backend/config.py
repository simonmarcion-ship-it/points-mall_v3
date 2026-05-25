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
ADMIN_USERNAME = os.getenv("MALL_ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("MALL_ADMIN_PASSWORD", "change-me")
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
