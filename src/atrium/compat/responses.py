# SPDX-License-Identifier: GPL-3.0-or-later
"""The JSON response class every route returns.

The reference is an ASP.NET Core application, and its JSON formatter emits

    Content-Type: application/json; charset=utf-8

Starlette appends `charset=utf-8` only to `text/*` media types, so its `JSONResponse` sends a bare
`application/json`. That is a difference on **every** response in the project, and one nobody would
find by reading either codebase - it took looking at real traffic.
`[probe: manual request, Jellyfin 10.11.11, 2026-08-26]`

The reference also accepts `application/json; profile="PascalCase"` and `profile="CamelCase"`, and
those are **not** three names for one behaviour: the CamelCase profile really does answer in
camelCase, and the response's content type echoes whichever profile matched.
`[probe: tools/probe_content_type_profiles.py, Jellyfin 10.11.11, 2026-08-26]`

This module implements neither yet. Every response is PascalCase with the content type above,
whatever was asked for - a bounded gap recorded in docs/compatibility/behaviours.md section 5,
pinned by a conformance test, and closed by task T19 of feature 001. It is not fixed here because
the conversion has to happen while a response is still a model: dictionary *keys* are not
converted, and by the time a body is bytes nothing can tell a property from a key.
"""

from __future__ import annotations

from fastapi.responses import JSONResponse

#: What the reference sends, charset and all.
JSON_MEDIA_TYPE = "application/json; charset=utf-8"


class AtriumJSONResponse(JSONResponse):
    """`JSONResponse` with the reference's exact content type."""

    media_type = JSON_MEDIA_TYPE


__all__ = ["JSON_MEDIA_TYPE", "AtriumJSONResponse"]
