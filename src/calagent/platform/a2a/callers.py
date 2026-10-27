"""Admits JSON-RPC calls only from registered callers, before any JSON-RPC handling.

A pure ASGI middleware: a POST to the JSON-RPC path must carry a registered caller's secret in
X-Caller-Secret, compared in constant time against every secret; anything else gets HTTP 401 with
an empty body. The admitted caller is put on the request scope's state for the call-context
builder. Every other route (the card, health, the statements page) passes untouched.
"""

import hmac

from starlette.types import ASGIApp, Receive, Scope, Send

from calagent.adapters.callers_file import Caller
from calagent.platform.a2a.card import CALLER_SECRET_HEADER

CALLER_STATE_KEY = "caller"
_HEADER = CALLER_SECRET_HEADER.lower().encode()


class CallerSecretMiddleware:
    def __init__(self, app: ASGIApp, callers: dict[str, Caller], rpc_path: str = "/") -> None:
        self._app = app
        self._callers = [(secret.encode(), caller) for secret, caller in callers.items()]
        self._rpc_path = rpc_path

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] != "POST" or scope["path"] != self._rpc_path:
            await self._app(scope, receive, send)
            return
        caller = self._caller(dict(scope["headers"]).get(_HEADER, b""))
        if caller is None:
            await send(
                {
                    "type": "http.response.start",
                    "status": 401,
                    "headers": [(b"www-authenticate", CALLER_SECRET_HEADER.encode())],
                }
            )
            await send({"type": "http.response.body", "body": b""})
            return
        # The server leaves scope state out when it runs no lifespan state; Starlette then
        # creates it on first access.
        scope.setdefault("state", {})[CALLER_STATE_KEY] = caller
        await self._app(scope, receive, send)

    def _caller(self, presented: bytes) -> Caller | None:
        """Compares against every secret, so the time taken does not tell which one is close."""
        matched = None
        for secret, caller in self._callers:
            if hmac.compare_digest(secret, presented):
                matched = caller
        return matched
