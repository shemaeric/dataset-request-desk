from fastapi import FastAPI

from app.config import Settings, load_settings
from app.db import database_config_from
from app.logging import AccessLogMiddleware, configure_logging
from app.request_context import UserContextMiddleware


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    configure_logging()
    app = FastAPI(title="Dataset Request Desk", version="0.1.0")
    app.state.settings = settings
    app.state.database = database_config_from(settings)
    # Added last so it is outermost and still sees the user id set inside.
    app.add_middleware(UserContextMiddleware)
    app.add_middleware(AccessLogMiddleware)

    @app.get("/health")
    def health() -> dict[str, str]:
        """Process liveness. This does not check the database."""
        return {"status": "ok"}

    return app


app = create_app()
