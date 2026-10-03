from fastapi import FastAPI

from app.logging import AccessLogMiddleware, configure_logging

configure_logging()

app = FastAPI(title="Dataset Request Desk", version="0.1.0")
app.add_middleware(AccessLogMiddleware)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
