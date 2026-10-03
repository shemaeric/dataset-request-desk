from dataclasses import dataclass

from app.config import Settings


@dataclass(frozen=True)
class DatabaseConfig:
    """Connection settings only.

    No engine or pool is created. `/health` must not read this object to
    decide whether the database is up.
    """

    url: str


def database_config_from(settings: Settings) -> DatabaseConfig:
    url = settings.database_url.strip()
    if not url:
        raise ValueError("DATABASE_URL must not be empty")
    return DatabaseConfig(url=url)
