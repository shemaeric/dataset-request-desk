import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import hash_password
from app.config import load_settings
from app.db import create_session_factory
from app.models import User


def default_seed_path() -> Path:
    return Path(__file__).resolve().parents[2] / "seed" / "users.json"


def seed_users(db: Session, path: Path) -> int:
    records = json.loads(path.read_text())
    created = 0
    for record in records:
        email = str(record["email"]).strip().lower()
        if db.scalar(select(User.id).where(User.email == email)) is not None:
            continue
        organisation = record.get("organisation")
        db.add(
            User(
                email=email,
                password_hash=hash_password(str(record["password"])),
                name=str(record["name"]).strip(),
                organisation=str(organisation).strip() if organisation else None,
                role=str(record["role"]),
                is_active=True,
            )
        )
        created += 1
    db.commit()
    return created


def main() -> None:
    settings = load_settings()
    path = Path(settings.seed_users_path) if settings.seed_users_path else default_seed_path()
    engine, factory = create_session_factory(settings)
    db = factory()
    try:
        created = seed_users(db, path)
    finally:
        db.close()
        engine.dispose()
    print(f"created {created} users")


if __name__ == "__main__":
    main()
