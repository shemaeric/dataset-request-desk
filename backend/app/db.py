from dataclasses import dataclass

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings


@dataclass(frozen=True)
class DatabaseConfig:
    """Connection settings. `/health` does not open a connection."""

    url: str


def database_config_from(settings: Settings) -> DatabaseConfig:
    url = settings.database_url.strip()
    if not url:
        raise ValueError("DATABASE_URL must not be empty")
    return DatabaseConfig(url=url)


def create_session_factory(settings: Settings) -> tuple[Engine, sessionmaker[Session]]:
    engine = create_engine(database_config_from(settings).url, pool_pre_ping=True)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    return engine, factory
