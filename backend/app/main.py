from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.auth_routes import router as auth_router
from .api.routes import router
from .config import settings
from .database import Base, SessionLocal, engine
from .services.csv_loader import seed_products_if_empty, seed_suppliers_if_empty


def _run_migrations(db):
    """Idempotent ALTER TABLE migrations for existing databases."""
    import sqlalchemy

    alter_statements = [
        "ALTER TABLE lv_projects ADD COLUMN assigned_user_id INTEGER REFERENCES users(id)",
        "ALTER TABLE lv_projects ADD COLUMN last_editor_id INTEGER REFERENCES users(id)",
        "ALTER TABLE lv_projects ADD COLUMN last_edited_at DATETIME",
        "ALTER TABLE lv_projects ADD COLUMN workstate_json TEXT",
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

    existing = db.execute(select(User)).scalar_one_or_none()
    if existing is None:
        admin = User(
            email="admin@fassbender-tenten.de",
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
        seed_products_if_empty(db)
        seed_suppliers_if_empty(db)
    # Start background scheduler for Objektradar
    from .services.scheduler import start_scheduler, stop_scheduler
    start_scheduler()
    yield
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
