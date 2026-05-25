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
    load_env_file(str(Path(__file__).resolve().parents[2] / ".env"))
    load_env_file(str(Path(__file__).resolve().parents[3] / ".env"))
    os.environ.setdefault("CLIENT_DB_PATH", r"D:\weimeng_customerinfo\web\data\mall.db")
    cargeer_env_file = os.environ.get(
        "CARGEER_ENV_FILE",
        str(Path.home() / "Desktop" / "Projects" / "小天" / "wecom-bot" / ".env"),
    )
    if load_env_file(cargeer_env_file):
        os.environ.setdefault("CARGEER_ENABLED", "1")
    uvicorn.run("backend.main:app", host="127.0.0.1", port=8010, reload=False)
