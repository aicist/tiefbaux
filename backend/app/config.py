from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

_BACKEND_DIR = Path(__file__).resolve().parents[1]
_PROJECT_ROOT = _BACKEND_DIR.parent

for _candidate in (_BACKEND_DIR / ".env", _PROJECT_ROOT / ".env"):
    if _candidate.exists():
        load_dotenv(_candidate)
        break
else:
    load_dotenv()


def _resolve_database_url(raw: str) -> str:
    if raw.startswith("sqlite:///./"):
        relative = raw.replace("sqlite:///./", "")
        absolute = _BACKEND_DIR / relative
        return f"sqlite:///{absolute}"
    return raw


@dataclass(frozen=True)
class Settings:
    app_name: str
    database_url: str
    gemini_api_key: str | None
    gemini_model: str
    cors_origins: list[str]
    project_root: Path
    smtp_host: str | None
    smtp_port: int
    smtp_user: str | None
    smtp_password: str | None
    smtp_from_email: str | None
    smtp_from_name: str
    smtp_use_tls: bool


def _split_csv_env(value: str | None, default: list[str]) -> list[str]:
    if not value:
        return default
    return [part.strip() for part in value.split(",") if part.strip()]


def get_settings() -> Settings:
    raw_db_url = os.getenv(
        "DATABASE_URL",
        f"sqlite:///{_BACKEND_DIR / 'tiefbaux.db'}",
    )
    return Settings(
        app_name="TiefbauX MVP",
        database_url=_resolve_database_url(raw_db_url),
        gemini_api_key=os.getenv("GEMINI_API_KEY"),
        gemini_model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
        cors_origins=_split_csv_env(
            os.getenv("CORS_ORIGINS"),
            [
                "http://localhost:5173",
                "http://localhost:5174",
                "http://127.0.0.1:5173",
                "http://127.0.0.1:5174",
            ],
        ),
        project_root=_PROJECT_ROOT,
        smtp_host=os.getenv("SMTP_HOST"),
        smtp_port=int(os.getenv("SMTP_PORT", "587")),
        smtp_user=os.getenv("SMTP_USER"),
        smtp_password=os.getenv("SMTP_PASSWORD"),
        smtp_from_email=os.getenv("SMTP_FROM_EMAIL"),
        smtp_from_name=os.getenv("SMTP_FROM_NAME", "Fassbender Tenten GmbH"),
        smtp_use_tls=os.getenv("SMTP_USE_TLS", "true").lower() in ("true", "1", "yes"),
    )


settings = get_settings()
