import secrets
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.auth import CSRF_HEADER, LOGIN_PATH, SESSION_COOKIE, user_from_session

UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


class SessionMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request.state.user_id = None
        request.state.user = None
        if request.url.path == "/health":
            return await call_next(request)

        raw_token = request.cookies.get(SESSION_COOKIE)
        csrf_token = None
        if raw_token:
            db = request.app.state.session_factory()
            try:
                found = user_from_session(db, raw_token)
            finally:
                db.close()
            if found is not None:
                user, csrf_token = found
                request.state.user = user
                request.state.user_id = user.id

        if raw_token and request.method in UNSAFE_METHODS and request.url.path != LOGIN_PATH:
            if request.state.user is None:
                return JSONResponse({"detail": "Not authenticated"}, status_code=401)
            header = request.headers.get(CSRF_HEADER)
            csrf_ok = (
                header is not None
                and csrf_token is not None
                and secrets.compare_digest(header, csrf_token)
            )
            if not csrf_ok:
                return JSONResponse({"detail": "CSRF check failed"}, status_code=403)

        return await call_next(request)
