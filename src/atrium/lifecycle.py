# SPDX-License-Identifier: GPL-3.0-or-later
"""Whether the server is ready to answer, and what it says while it is not.

A server that is still scanning, migrating or opening its database has to answer *something*, and
the reference is specific about what. **Every one of its 395 operations declares a `503`**, so the
gate is server-wide rather than per-route, and the response carries two headers:

    Retry-After: <full seconds>
    Message: <a short plain-text reason>

with a `text/html` body.
`[spec: every operation's 503 response in the pinned 10.11.10 document]`

`Retry-After` is what separates "starting" from "broken" for a client. Without it a `503` is
indistinguishable from a server that is simply down, and a client that cannot tell will either
give up or hammer.

See specs/001-server-identity-and-discovery/plan.md section 5 and section 7.
"""

from __future__ import annotations

from dataclasses import dataclass

from starlette.types import ASGIApp, Receive, Scope, Send

#: Long enough that a client is not hammering, short enough that a fast start is not punished.
DEFAULT_RETRY_AFTER_SECONDS = 5

STARTING_MESSAGE = "Atrium is starting."


@dataclass(slots=True)
class Readiness:
    """One flag, consulted by the middleware and by nothing else.

    Kept as an object rather than a module-level flag so two instances in one process - which the
    tests rely on - do not share it.
    """

    ready: bool = False
    retry_after_seconds: int = DEFAULT_RETRY_AFTER_SECONDS
    message: str = STARTING_MESSAGE

    def mark_ready(self) -> None:
        self.ready = True

    def mark_unavailable(self, message: str, retry_after_seconds: int | None = None) -> None:
        """Take the server out of service without stopping it, saying why."""
        self.ready = False
        self.message = message
        if retry_after_seconds is not None:
            self.retry_after_seconds = retry_after_seconds


class ReadinessMiddleware:
    """Answer `503` until the application says it is ready.

    A raw ASGI middleware rather than Starlette's `BaseHTTPMiddleware`, deliberately: that one
    wraps every response in a queue-backed stream, which is fine for JSON and wrong for the
    byte-range and HLS delivery feature 008 adds. Choosing it here would put a buffer in front of
    every media stream the server ever serves, and the reason would be lost by then.
    """

    def __init__(self, app: ASGIApp, readiness: Readiness) -> None:
        self.app = app
        self.readiness = readiness

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or self.readiness.ready:
            await self.app(scope, receive, send)
            return

        body = (
            f"<html><head><title>Atrium</title></head>"
            f"<body><p>{self.readiness.message}</p></body></html>"
        ).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 503,
                "headers": [
                    (b"content-type", b"text/html; charset=utf-8"),
                    (b"content-length", str(len(body)).encode()),
                    (b"retry-after", str(self.readiness.retry_after_seconds).encode()),
                    (b"message", self.readiness.message.encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})


__all__ = [
    "DEFAULT_RETRY_AFTER_SECONDS",
    "STARTING_MESSAGE",
    "Readiness",
    "ReadinessMiddleware",
]
