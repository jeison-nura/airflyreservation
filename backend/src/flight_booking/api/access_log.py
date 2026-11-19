"""Log HTTP requests and WebSocket sessions without raw URLs or headers."""

from time import perf_counter

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from flight_booking.shared.observability import log_context, log_event

_HTTP_METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "HEAD", "OPTIONS", "DELETE"})


class AccessLogMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        entry_point = scope["type"]
        if entry_point not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        start = perf_counter()
        status_code = None
        close_code = None
        error_type = None

        async def send_observed(message: Message) -> None:
            nonlocal status_code, close_code
            if message["type"] in ("http.response.start", "websocket.http.response.start"):
                status_code = message["status"]
                MutableHeaders(scope=message)["X-Request-ID"] = request_id
            elif message["type"] == "websocket.accept":
                status_code = 101
            elif message["type"] == "websocket.close":
                close_code = message.get("code", 1000)
            await send(message)

        async def receive_observed() -> Message:
            nonlocal close_code
            message = await receive()
            if message["type"] == "websocket.disconnect":
                close_code = message.get("code")
            return message

        with log_context(entry_point) as request_id:
            try:
                await self.app(scope, receive_observed, send_observed)
            except Exception as exc:
                error_type = type(exc).__name__
                if status_code is None and entry_point == "http":
                    status_code = 500
                raise
            finally:
                method = scope.get("method")
                log_event(
                    "api",
                    "http_request" if entry_point == "http" else "websocket_session",
                    level="ERROR" if error_type or (status_code or 0) >= 500 else "INFO",
                    route=getattr(scope.get("route"), "path", "<unmatched>"),
                    method=method if method in _HTTP_METHODS else None,
                    status_code=status_code,
                    close_code=close_code,
                    duration_ms=round((perf_counter() - start) * 1000, 2),
                    error_type=error_type,
                )
