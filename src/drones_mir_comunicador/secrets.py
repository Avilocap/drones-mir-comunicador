from __future__ import annotations

from pathlib import Path


DEFAULT_ENV_PATH = Path(".env")


def load_env(path: Path = DEFAULT_ENV_PATH) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = _clean_env_value(value)
    return values


def find_certificate_path(env: dict[str, str], base_dir: Path = Path(".")) -> Path:
    configured = env.get("CERTIFICATE_P12") or env.get("CERTIFICATE_PATH")
    if configured:
        return Path(configured).expanduser()

    candidates = sorted(base_dir.glob("*.p12")) + sorted(base_dir.glob("*.pfx"))
    if not candidates:
        raise FileNotFoundError("No encuentro ningun .p12/.pfx en el proyecto")
    if len(candidates) > 1:
        raise RuntimeError("Hay varios .p12/.pfx. Define CERTIFICATE_P12 en .env")
    return candidates[0]


def require_certificate_password(env: dict[str, str]) -> str:
    password = env.get("CERTIFICATE_PASSWORD")
    if not password:
        raise RuntimeError("Falta CERTIFICATE_PASSWORD en .env")
    return password


def _clean_env_value(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value

