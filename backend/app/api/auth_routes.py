from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import (
    create_access_token,
    get_current_user,
    hash_password,
    require_admin,
    verify_password,
)
from ..database import get_db
from ..models import LVProject, User
from ..schemas import (
    AssignProjectRequest,
    ChangePasswordRequest,
    TokenResponse,
    UserCreate,
    UserResponse,
    UserUpdate,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _user_response(user: User) -> UserResponse:
    return UserResponse(
        id=user.id,
        email=user.email,
        name=user.name,
        role=user.role,
        active=user.active,
    )


@router.post("/login", response_model=TokenResponse)
def login(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.execute(
        select(User).where(User.email == form.username)
    ).scalar_one_or_none()

    if not user or not verify_password(form.password, user.password_hash):
        raise HTTPException(status_code=401, detail="E-Mail oder Passwort falsch")
    if not user.active:
        raise HTTPException(status_code=403, detail="Benutzer deaktiviert")

    token = create_access_token({"sub": str(user.id)})
    return TokenResponse(access_token=token, user=_user_response(user))


@router.get("/me", response_model=UserResponse)
def get_me(current_user: User = Depends(get_current_user)):
    return _user_response(current_user)


@router.patch("/me/password")
def change_own_password(
    data: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not verify_password(data.current_password, current_user.password_hash):
        raise HTTPException(status_code=400, detail="Aktuelles Passwort falsch")
    current_user.password_hash = hash_password(data.new_password)
    db.commit()
    return {"ok": True}


# --- Admin: User management ---

@router.get("/users", response_model=list[UserResponse])
def list_users(
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    users = db.execute(select(User).order_by(User.name)).scalars().all()
    return [_user_response(u) for u in users]


@router.post("/users", response_model=UserResponse, status_code=201)
def create_user(
    data: UserCreate,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    existing = db.execute(select(User).where(User.email == data.email)).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail="E-Mail bereits vergeben")

    user = User(
        email=data.email.strip().lower(),
        password_hash=hash_password(data.password),
        name=data.name.strip(),
        role=data.role if data.role in ("admin", "mitarbeiter") else "mitarbeiter",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return _user_response(user)


@router.patch("/users/{user_id}", response_model=UserResponse)
def update_user(
    user_id: int,
    data: UserUpdate,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Benutzer nicht gefunden")

    if data.name is not None:
        user.name = data.name.strip()
    if data.role is not None and data.role in ("admin", "mitarbeiter"):
        user.role = data.role
    if data.active is not None:
        user.active = data.active
    if data.password is not None:
        user.password_hash = hash_password(data.password)

    db.commit()
    db.refresh(user)
    return _user_response(user)


# --- Admin: Project assignment ---

@router.post("/projects/{project_id}/assign")
def assign_project(
    project_id: int,
    data: AssignProjectRequest,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    project = db.get(LVProject, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Projekt nicht gefunden")

    if data.user_id is not None:
        user = db.get(User, data.user_id)
        if not user:
            raise HTTPException(status_code=404, detail="Benutzer nicht gefunden")

    project.assigned_user_id = data.user_id
    db.commit()
    return {"ok": True}
