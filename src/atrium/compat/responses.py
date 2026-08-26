# SPDX-License-Identifier: GPL-3.0-or-later
"""The JSON response class every route returns.

The reference is an ASP.NET Core application, and its JSON formatter emits

    Content-Type: application/json; charset=utf-8

Starlette appends `charset=utf-8` only to `text/*` media types, so its `JSONResponse` sends a bare
`application/json`. That is a difference on **every** response in the project, and one nobody would
find by reading either codebase - it took looking at real traffic.
`[probe: manual request, Jellyfin 10.11.11, 2026-08-26]`

**And the content type says which serialisation was used.** The reference accepts
`application/json; profile="PascalCase"` and `profile="CamelCase"`, answers the second in
camelCase, and echoes whichever profile matched - before the charset, canonically spelled - on
every JSON response, a bare string body included.
`[probe: tools/probe_content_type_profiles.py, Jellyfin 10.11.11, 2026-08-26]`

So the media type is per response rather than per class: it is read from the profile negotiated
for the request being served. `atrium.compat.profiles` decides that, and `AtriumModel` applies it
to the body - which is the only place a property name can be told apart from a dictionary key.

A refusal carries no content type at all, in the reference and here, so it echoes nothing: an
empty `401`, `404` or `405` is built by `atrium.compat.errors`, not by this class.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fastapi.responses import JSONResponse
from starlette.background import BackgroundTask

from atrium.compat.profiles import JSON_MEDIA_TYPE, current


class AtriumJSONResponse(JSONResponse):
    """`JSONResponse` with the reference's exact content type, profile and all."""

    media_type = JSON_MEDIA_TYPE

    def __init__(
        self,
        content: Any = None,
        status_code: int = 200,
        headers: Mapping[str, str] | None = None,
        media_type: str | None = None,
        background: BackgroundTask | None = None,
    ) -> None:
        """The parameters are spelled out, and that is not decoration.

        FastAPI builds the OpenAPI document by **inspecting this signature** for a `status_code`
        parameter with an integer default, and uses it as the operation's success status. Written
        as `*args, **kwargs` - which is otherwise the obvious way to add one default - the
        parameter disappears from the signature and generating the document raises
        `UnboundLocalError`. A test asserts the document still builds, which is the only reason
        that was a five-minute problem rather than a release-day one.
        """
        # The negotiated profile applies only when the caller did not decide for itself. The
        # framework constructs these without a media type, which is what makes the negotiated one
        # the default rather than something every route has to remember to pass.
        super().__init__(
            content, status_code, headers, media_type or current().media_type, background
        )


__all__ = ["JSON_MEDIA_TYPE", "AtriumJSONResponse"]
