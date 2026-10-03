from pydantic_settings import BaseSettings, SettingsConfigDict

# Used when DATABASE_URL is unset, which is local uvicorn. Compose sets the variable
# itself and points the hostname at the `db` service.
LOCAL_DATABASE_URL = "postgresql+psycopg://desk:desk@127.0.0.1:5432/dataset_request_desk"


class Settings(BaseSettings):
    """Process configuration. Values come from the environment, not from request data."""

    model_config = SettingsConfigDict(extra="ignore")

    database_url: str = LOCAL_DATABASE_URL


def load_settings() -> Settings:
    return Settings()
