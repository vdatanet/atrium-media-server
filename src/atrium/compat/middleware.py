# SPDX-License-Identifier: GPL-3.0-or-later
"""Headers this server puts on every response.

Two, and they come from different places.

`Server` is where Atrium tells the truth about what it is. Everything a client *parses* says
Jellyfin - `ProductName`, `Version` - because those are the fields multi-server clients branch on,
and reading anything else there sends them down an unknown-server path. `Server` is read by people:
in a `curl` dump, in a proxy log, in a bug report. The reference sends `Server: Kestrel`, so this
is a measured difference and a deliberate one.
`[probe: manual request, Jellyfin 10.11.11, 2026-08-26; see docs/compatibility/behaviours.md 4.1]`

`X-Response-Time-ms` is the reference's, on every response, and this project would not have known
about it without looking at real traffic. Its middleware is registered unconditionally; the two
configuration flags near it gate a slow-response *log line*, not the header.
`[source: Jellyfin.Api/Middleware/ResponseTimeMiddleware.cs:17,
Jellyfin.Server/Startup.cs:163 @ v10.11.11]`

See specs/001-server-identity-and-discovery/plan.md section 6.5.
"""

from __future__ import annotations

import time
from collections.abc import MutableMapping
from typing import Any

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from atrium import __version__

SERVER_HEADER = b"server"
RESPONSE_TIME_HEADER = b"x-response-time-ms"

#: What a human sees. Never what a client discriminates on.
SERVER_VALUE = f"Atrium/{__version__}".encode()


class ResponseHeadersMiddleware:
    """Stamp both headers, replacing whatever the server underneath put there.

    Raw ASGI rather than `BaseHTTPMiddleware`, for the reason given in atrium.lifecycle: the
    convenient one buffers every response, which is wrong for the byte-range and HLS delivery
    feature 008 adds.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        started = time.perf_counter()

        async def stamped(message: Message) -> None:
            if message["type"] == "http.response.start":
                elapsed_ms = (time.perf_counter() - started) * 1000
                headers: list[tuple[bytes, bytes]] = [
                    (name, value)
                    for name, value in message.get("headers", [])
                    if name.lower() not in (SERVER_HEADER, RESPONSE_TIME_HEADER)
                ]
                headers.append((SERVER_HEADER, SERVER_VALUE))
                headers.append((RESPONSE_TIME_HEADER, f"{elapsed_ms:.4f}".encode()))
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, stamped)


def apply(app: MutableMapping[str, Any] | ASGIApp) -> ASGIApp:  # pragma: no cover - convenience
    """Wrap an application. Kept trivial so the app factory reads as a list of decisions."""
    return ResponseHeadersMiddleware(app)  # type: ignore[arg-type]


__all__ = [
    "RESPONSE_TIME_HEADER",
    "SERVER_HEADER",
    "SERVER_VALUE",
    "ResponseHeadersMiddleware",
]
