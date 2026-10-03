from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import get_db, hash_password, require_roles
from app.models import User, UserRole

NAME_MAX = 200
EMAIL_MAX = 200
PASSWORD_MAX = 200
ORG_MAX = 200
NOT_FOUND = "User not found"
DUPLICATE = "A user with this email already exists"
LAST_ADMIN = "The desk needs an active admin"

router = APIRouter(prefix="/users")
admin_only = require_roles(UserRole.ADMIN)


class AccountOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    name: str
    role: str
    organisation: str | None
    is_active: bool


class AccountIn(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    email: str = Field(min_length=3, max_length=EMAIL_MAX)
    name: str = Field(min_length=1, max_length=NAME_MAX)
    password: str = Field(min_length=1, max_length=PASSWORD_MAX)
    role: UserRole
    organisation: str | None = Field(default=None, max_length=ORG_MAX)

    @field_validator("email")
    @classmethod
    def clean_email(cls, value: str) -> str:
        email = value.strip().lower()
        if "@" not in email or email.startswith("@") or email.endswith("@"):
            raise ValueError("email is invalid")
        return email

    @field_validator("organisation")
    @classmethod
    def blank_organisation(cls, value: str | None) -> str | None:
        if not value:
            return None
        return value


class AccountPatch(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    name: str | None = Field(default=None, min_length=1, max_length=NAME_MAX)
    role: UserRole | None = None
    organisation: str | None = Field(default=None, max_length=ORG_MAX)
    is_active: bool | None = None

    @field_validator("organisation")
    @classmethod
    def blank_organisation(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


def _active_admins_besides(db: Session, user_id: int) -> int:
    counted = db.scalar(
        select(func.count())
        .select_from(User)
        .where(
            User.id != user_id,
            User.role == UserRole.ADMIN.value,
            User.is_active.is_(True),
        )
    )
    return int(counted or 0)


def _commit(db: Session) -> None:
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail=DUPLICATE) from None


@router.get("", response_model=list[AccountOut])
def list_users(
    db: Session = Depends(get_db),
    _user: User = Depends(admin_only),
) -> list[User]:
    return list(db.scalars(select(User).order_by(User.id)))


@router.post("", response_model=AccountOut, status_code=201)
def create_user(
    body: AccountIn,
    db: Session = Depends(get_db),
    _user: User = Depends(admin_only),
) -> User:
    if db.scalar(select(User.id).where(User.email == body.email)) is not None:
        raise HTTPException(status_code=409, detail=DUPLICATE)
    row = User(
        email=body.email,
        password_hash=hash_password(body.password),
        name=body.name,
        organisation=body.organisation,
        role=body.role.value,
        is_active=True,
    )
    db.add(row)
    _commit(db)
    db.refresh(row)
    return row


@router.patch("/{user_id}", response_model=AccountOut)
def update_user(
    user_id: int,
    body: AccountPatch,
    db: Session = Depends(get_db),
    _user: User = Depends(admin_only),
) -> User:
    row = db.scalar(select(User).where(User.id == user_id).with_for_update())
    if row is None:
        raise HTTPException(status_code=404, detail=NOT_FOUND)

    next_role = row.role
    if "role" in body.model_fields_set and body.role is not None:
        next_role = body.role.value
    next_active = row.is_active
    if "is_active" in body.model_fields_set and body.is_active is not None:
        next_active = body.is_active
    removes_admin = row.role == UserRole.ADMIN.value and row.is_active
    stays_admin = next_role == UserRole.ADMIN.value and next_active
    if removes_admin and not stays_admin and _active_admins_besides(db, row.id) == 0:
        raise HTTPException(status_code=409, detail=LAST_ADMIN)

    if "name" in body.model_fields_set and body.name is not None:
        row.name = body.name
    if "role" in body.model_fields_set and body.role is not None:
        row.role = body.role.value
    if "is_active" in body.model_fields_set and body.is_active is not None:
        row.is_active = body.is_active
    if "organisation" in body.model_fields_set:
        row.organisation = body.organisation
    row.updated_at = datetime.now(UTC)
    _commit(db)
    db.refresh(row)
    return row
