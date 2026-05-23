import os
from pathlib import Path

import uvicorn


def load_env_file(path: str) -> bool:
    env_path = Path(path)
    if not env_path.exists():
        return False
    loaded = False
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
        loaded = True
    return loaded


if __name__ == "__main__":
    os.environ.setdefault("MALL_DATA_DIR", r"D:\weimeng_customerinfo\web\data")
    os.environ.setdefault("MALL_DB_PATH", r"D:\weimeng_customerinfo\web\data\mall.db")
    os.environ.setdefault("MALL_CRAWLER_V2_OUTPUT_DIR", r"D:\weimeng_customerinfo\crawler_v2\output")
    cargeer_env_file = os.environ.get(
        "CARGEER_ENV_FILE",
        r"C:\Users\78535\Desktop\Projects\小天\wecom-bot\.env",
    )
    if load_env_file(cargeer_env_file):
        os.environ.setdefault("CARGEER_ENABLED", "1")
    uvicorn.run("backend.main:app", host="127.0.0.1", port=8000, reload=False)
