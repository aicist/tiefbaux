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
    if raw.startswith("postgres://"):
        raw = "postgresql://" + raw[len("postgres://"):]
    if raw.startswith("postgresql://"):
        return "postgresql+psycopg://" + raw[len("postgresql://"):]
    return raw


@dataclass(frozen=True)
class Settings:
    app_name: str
    database_url: str
    gemini_api_key: str | None
    gemini_model: str
    gemini_fallback_models: list[str]
    gemini_retry_attempts: int
    cors_origins: list[str]
    project_root: Path
    smtp_host: str | None
    smtp_port: int
    smtp_user: str | None
    smtp_password: str | None
    smtp_from_email: str | None
    smtp_from_name: str
    smtp_use_tls: bool
    smtp_demo_mode: bool
    smtp_demo_recipients: list[str]
    smtp_demo_subject_prefix: str
    inbound_email_enabled: bool
    inbound_email_poll_minutes: int
    inbound_email_imap_host: str | None
    inbound_email_imap_port: int
    inbound_email_imap_user: str | None
    inbound_email_imap_password: str | None
    inbound_email_imap_folder: str
    inbound_email_imap_use_ssl: bool
    inbound_email_mark_seen: bool
    inbound_email_new_lv_keywords: list[str]
    inbound_email_offer_keywords: list[str]
    jwt_secret_key: str


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
        gemini_fallback_models=_split_csv_env(os.getenv("GEMINI_FALLBACK_MODELS"), []),
        gemini_retry_attempts=max(1, int(os.getenv("GEMINI_RETRY_ATTEMPTS", "2"))),
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
        smtp_demo_mode=os.getenv("SMTP_DEMO_MODE", "false").lower() in ("true", "1", "yes"),
        smtp_demo_recipients=_split_csv_env(os.getenv("SMTP_DEMO_RECIPIENTS"), []),
        smtp_demo_subject_prefix=os.getenv("SMTP_DEMO_SUBJECT_PREFIX", "[DEMO]"),
        inbound_email_enabled=os.getenv("INBOUND_EMAIL_ENABLED", "false").lower() in ("true", "1", "yes"),
        inbound_email_poll_minutes=max(1, int(os.getenv("INBOUND_EMAIL_POLL_MINUTES", "2"))),
        inbound_email_imap_host=os.getenv("INBOUND_EMAIL_IMAP_HOST"),
        inbound_email_imap_port=int(os.getenv("INBOUND_EMAIL_IMAP_PORT", "993")),
        inbound_email_imap_user=os.getenv("INBOUND_EMAIL_IMAP_USER"),
        inbound_email_imap_password=os.getenv("INBOUND_EMAIL_IMAP_PASSWORD"),
        inbound_email_imap_folder=os.getenv("INBOUND_EMAIL_IMAP_FOLDER", "INBOX"),
        inbound_email_imap_use_ssl=os.getenv("INBOUND_EMAIL_IMAP_USE_SSL", "true").lower() in ("true", "1", "yes"),
        inbound_email_mark_seen=os.getenv("INBOUND_EMAIL_MARK_SEEN", "true").lower() in ("true", "1", "yes"),
        inbound_email_new_lv_keywords=_split_csv_env(
            os.getenv("INBOUND_EMAIL_NEW_LV_KEYWORDS"),
            ["lv", "leistungsverzeichnis", "ausschreibung", "anfrage", "angebotsanfrage"],
        ),
        inbound_email_offer_keywords=_split_csv_env(
            os.getenv("INBOUND_EMAIL_OFFER_KEYWORDS"),
            ["angebot", "lieferantenangebot", "preisangebot", "rueckmeldung", "rückmeldung"],
        ),
        jwt_secret_key=os.getenv("JWT_SECRET_KEY", "tiefbaux-dev-secret-change-in-production"),
    )


settings = get_settings()
