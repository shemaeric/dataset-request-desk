import hashlib
import secrets
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from functools import lru_cache

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pwdlib import PasswordHash
from pydantic import BaseModel, ConfigDict
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import AuthSession, User, UserRole

SESSION_COOKIE = "desk_session"
CSRF_COOKIE = "desk_csrf"
CSRF_HEADER = "x-csrf-token"
LOGIN_PATH = "/api/v1/auth/login"
INVALID_LOGIN = "Invalid email or password"
_password_hash = PasswordHash.recommended()


class LoginIn(BaseModel):
    model_config = ConfigDict(extra="ignore")

    email: str
    password: str


class UserOut(BaseModel):
    id: int
    email: str
    name: str
    role: str
    organisation: str | None


def hash_password(password: str) -> str:
    return _password_hash.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    return _password_hash.verify(password, hashed)


@lru_cache(maxsize=1)
def _dummy_hash() -> str:
    return hash_password("not-a-real-password")


def hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode()).hexdigest()


def get_db(request: Request) -> Iterator[Session]:
    db = request.app.state.session_factory()
    try:
        yield db
    finally:
        db.close()


def authenticate(db: Session, email: str, password: str) -> User | None:
    user = db.scalar(select(User).where(User.email == email.strip().lower()))
    if user is None:
        verify_password(password, _dummy_hash())
        return None
    if not verify_password(password, user.password_hash) or not user.is_active:
        return None
    return user


def user_from_session(db: Session, raw_token: str) -> tuple[User, str] | None:
    row = db.scalar(select(AuthSession).where(AuthSession.token_hash == hash_token(raw_token)))
    if row is None:
        return None
    if row.expires_at <= datetime.now(UTC):
        db.delete(row)
        db.commit()
        return None
    user = db.get(User, row.user_id)
    if user is None or not user.is_active:
        return None
    csrf_token = row.csrf_token
    db.expunge(user)
    return user, csrf_token


def start_session(db: Session, user: User, ttl_seconds: int) -> tuple[str, str]:
    raw_token = secrets.token_urlsafe(32)
    csrf_token = secrets.token_urlsafe(32)
    db.execute(delete(AuthSession).where(AuthSession.user_id == user.id))
    db.add(
        AuthSession(
            token_hash=hash_token(raw_token),
            csrf_token=csrf_token,
            user_id=user.id,
            expires_at=datetime.now(UTC) + timedelta(seconds=ttl_seconds),
        )
    )
    db.commit()
    return raw_token, csrf_token


def end_session(db: Session, raw_token: str) -> None:
    db.execute(delete(AuthSession).where(AuthSession.token_hash == hash_token(raw_token)))
    db.commit()


def get_current_user(request: Request) -> User:
    user = getattr(request.state, "user", None)
    if not isinstance(user, User):
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


def require_roles(*roles: UserRole) -> Callable[..., User]:
    allowed = {role.value for role in roles}

    def checker(user: User = Depends(get_current_user)) -> User:
        if user.role not in allowed:
            raise HTTPException(status_code=403, detail="Forbidden")
        return user

    return checker


def _settings(request: Request) -> Settings:
    settings = request.app.state.settings
    if not isinstance(settings, Settings):
        raise RuntimeError("app settings are not configured")
    return settings


def _write_cookies(response: Response, settings: Settings, raw_token: str, csrf_token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        raw_token,
        httponly=True,
        max_age=settings.session_ttl_seconds,
        path="/",
        samesite="lax",
        secure=settings.cookie_secure,
    )
    response.set_cookie(
        CSRF_COOKIE,
        csrf_token,
        httponly=False,
        max_age=settings.session_ttl_seconds,
        path="/",
        samesite="lax",
        secure=settings.cookie_secure,
    )


def _clear_cookies(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        SESSION_COOKIE,
        path="/",
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
    )
    response.delete_cookie(
        CSRF_COOKIE,
        path="/",
        httponly=False,
        samesite="lax",
        secure=settings.cookie_secure,
    )


router = APIRouter(prefix="/auth")


@router.post("/login", response_model=UserOut)
def login(
    body: LoginIn,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> User:
    user = authenticate(db, body.email, body.password)
    if user is None:
        raise HTTPException(status_code=401, detail=INVALID_LOGIN)
    settings = _settings(request)
    raw_token, csrf_token = start_session(db, user, settings.session_ttl_seconds)
    _write_cookies(response, settings, raw_token, csrf_token)
    request.state.user_id = user.id
    return user


@router.post("/logout", status_code=204)
def logout(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> None:
    raw_token = request.cookies.get(SESSION_COOKIE)
    if raw_token:
        end_session(db, raw_token)
    _clear_cookies(response, _settings(request))


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)) -> User:
    return user
