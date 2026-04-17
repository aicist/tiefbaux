from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.auth_routes import router as auth_router
from .api.routes import router
from .config import settings
from .database import Base, SessionLocal, engine
from .services.csv_loader import seed_products_if_empty, seed_suppliers_if_empty

logger = logging.getLogger(__name__)


def _run_migrations(db):
    """Idempotent ALTER TABLE migrations for existing databases."""
    import sqlalchemy

    alter_statements = [
        "ALTER TABLE lv_projects ADD COLUMN assigned_user_id INTEGER REFERENCES users(id)",
        "ALTER TABLE lv_projects ADD COLUMN last_editor_id INTEGER REFERENCES users(id)",
        "ALTER TABLE lv_projects ADD COLUMN last_edited_at DATETIME",
        "ALTER TABLE lv_projects ADD COLUMN workstate_json TEXT",
        "ALTER TABLE products ALTER COLUMN artikel_id TYPE VARCHAR(64)",
        "ALTER TABLE products ALTER COLUMN ersatz_artikel_id TYPE VARCHAR(64)",
        "ALTER TABLE products ALTER COLUMN nachfolger_artikel_id TYPE VARCHAR(64)",
        "ALTER TABLE manual_overrides ALTER COLUMN chosen_artikel_id TYPE VARCHAR(64)",
    ]
    for stmt in alter_statements:
        try:
            db.execute(sqlalchemy.text(stmt))
            db.commit()
        except Exception:
            db.rollback()


def _seed_admin(db):
    """Create default admin user if no users exist."""
    from sqlalchemy import select

    from .auth import hash_password
    from .models import User

    # Avoid MultipleResultsFound when more than one user already exists.
    existing = db.execute(select(User.id).limit(1)).scalar_one_or_none()
    if existing is None:
        admin = User(
            email="info@aicist.de",
            password_hash=hash_password("admin"),
            name="Administrator",
            role="admin",
        )
        db.add(admin)
        db.commit()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        _run_migrations(db)
        _seed_admin(db)
        try:
            seed_products_if_empty(db)
        except FileNotFoundError as exc:
            logger.warning("Product seed skipped (catalog CSV missing): %s", exc)
        except Exception as exc:
            logger.exception("Product seed failed: %s", exc)
        try:
            seed_suppliers_if_empty(db)
        except Exception as exc:
            logger.exception("Supplier seed failed: %s", exc)
    # Start background scheduler for Objektradar
    from .services.scheduler import start_scheduler, stop_scheduler
    enable_scheduler = os.getenv("ENABLE_SCHEDULER", "true").lower() in ("1", "true", "yes")
    if os.getenv("VERCEL") == "1":
        enable_scheduler = False
    if enable_scheduler:
        start_scheduler()
    else:
        logger.info("Scheduler disabled for this runtime")
    yield
    if enable_scheduler:
        stop_scheduler()


app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(router)
