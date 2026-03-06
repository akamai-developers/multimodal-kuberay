"""Shared utilities for MCP servers."""

from starlette.responses import JSONResponse


class BearerAuthMiddleware:
    """ASGI middleware that validates Bearer token on all requests except /health."""

    def __init__(self, app, token: str):
        self.app = app
        self.token = token

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            path = scope.get("path", "")
            if path != "/health":
                headers = dict(scope.get("headers", []))
                auth = headers.get(b"authorization", b"").decode()
                if auth != f"Bearer {self.token}":
                    response = JSONResponse(
                        {"error": "Unauthorized"}, status_code=401,
                    )
                    await response(scope, receive, send)
                    return
        await self.app(scope, receive, send)
