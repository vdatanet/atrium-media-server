# SPDX-License-Identifier: GPL-3.0-or-later
"""The JSON response class every route returns.

The reference is an ASP.NET Core application, and its JSON formatter emits

    Content-Type: application/json; charset=utf-8

Starlette appends `charset=utf-8` only to `text/*` media types, so its `JSONResponse` sends a bare
`application/json`. That is a difference on **every** response in the project, and one nobody would
find by reading either codebase - it took looking at real traffic.
`[probe: manual request, Jellyfin 10.11.11, 2026-08-26]`

The reference also declares and accepts `application/json; profile="CamelCase"` and
`profile="PascalCase"` on requests, answering all three identically. Nothing is needed for that
here - the profile is a request-side concern and the body is PascalCase regardless - but it is why
this module does not try to be clever about content negotiation.
"""

from __future__ import annotations

from fastapi.responses import JSONResponse

#: What the reference sends, charset and all.
JSON_MEDIA_TYPE = "application/json; charset=utf-8"


class AtriumJSONResponse(JSONResponse):
    """`JSONResponse` with the reference's exact content type."""

    media_type = JSON_MEDIA_TYPE


__all__ = ["JSON_MEDIA_TYPE", "AtriumJSONResponse"]
