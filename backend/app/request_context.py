from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


class UserContextMiddleware(BaseHTTPMiddleware):
    """Attach the authenticated user id for this request.

    Authentication is not implemented, so the id is always None. Client
    headers are ignored.
    """

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request.state.user_id = None
        return await call_next(request)
