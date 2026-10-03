from fastapi import FastAPI

from app.auth import router as auth_router
from app.config import Settings, load_settings
from app.db import create_session_factory, database_config_from
from app.episodes import router as episode_router
from app.logging import AccessLogMiddleware, configure_logging
from app.request_context import SessionMiddleware
from app.requests import router as request_router


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    configure_logging()
    engine, session_factory = create_session_factory(settings)
    app = FastAPI(title="Dataset Request Desk", version="0.1.0")
    app.state.settings = settings
    app.state.database = database_config_from(settings)
    app.state.engine = engine
    app.state.session_factory = session_factory
    app.add_middleware(SessionMiddleware)
    app.add_middleware(AccessLogMiddleware)
    app.include_router(auth_router, prefix="/api/v1")
    app.include_router(request_router, prefix="/api/v1")
    app.include_router(episode_router, prefix="/api/v1")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
