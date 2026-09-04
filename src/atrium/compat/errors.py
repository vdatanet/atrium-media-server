# SPDX-License-Identifier: GPL-3.0-or-later
"""What a refusal looks like on the wire.

Measured against a live 10.11.11 rather than assumed, and the answer is that the reference has
**four** error shapes, not one.
`[probe: tools/probe_routing.py, Jellyfin 10.11.11, 2026-08-28]`
`[probe: tools/probe_auth_mechanisms.py, Jellyfin 10.11.11, 2026-08-28]`
`[probe: tools/probe_query_envelope.py, Jellyfin 10.11.11, 2026-08-28]`

**Empty**, for refusals decided before a handler runs - an unauthenticated request, a path that
matches no route, a method a path does not have. Status line, `Content-Length: 0`, and nothing
else: no body, no `Content-Type`, and **no `WWW-Authenticate`**. A `405` additionally carries
`Allow`, and it lists **every** method the path has.
`[probe: tools/probe_routing.py, Jellyfin 10.11.11, 2026-08-26]`

**RFC 9457 problem details**, for errors a handler or the model binder produced - an item that does
not exist, a malformed identifier in a path. A JSON object with `type`, `title`, `status`, an
`errors` map for validation failures, and a `traceId`.

**Plain text**, for a refusal a controller decided itself. `text/plain` with no charset, and a
fixed 25-byte body reading `Error processing request.` Every refusal from
`POST /Users/AuthenticateByName` has this shape - the `400` for a broken client header, the `401`
for an unknown username, the `403` for a disabled account - so the status is the entire difference
between them. `[probe: tools/probe_auth_mechanisms.py, Jellyfin 10.11.11, 2026-08-26]`

**A JSON-encoded bare string**, for a controller that refused *with a message*. The image route's
own `404`: `"<item name> does not have an image of type <Type>"`, quoted, in
`application/json; charset=utf-8`. One route, two `404` bodies - an item that does not exist gets
problem details, an item that exists and lacks the image gets this - split by which of the two
lookups failed. `[probe: manual requests via tools/_probe.py, Jellyfin 10.11.11, 2026-08-28]`

**It has a second route since 009, and the second one does not split.** Every way
`GET /Playlists/{playlistId}/Items` can fail to hand over a playlist is the fixed 20-byte
`"Playlist not found"` - an unknown id, a real item that is not a playlist, and a playlist the
reader may not see - while the *problem-details* `404` for that same playlist lives on a different
route, `GET /Items/{itemId}`. So the shape is a fact about the route rather than about the status,
and reading it off a neighbouring route is how a feature ships a body no reference server sends
`[probe: tools/probe_playlist_read.py, Jellyfin 10.11.11, 2026-09-01]`.

**And a third route, in 002 and not in a feature that found the shape.** `GET /Users/{userId}`
answers the fixed 16-byte `"User not found"` for an identifier no account has - the same body to an
administrator and to a non-administrator, because that route refuses neither
`[probe: tools/probe_user_read.py, Jellyfin 10.11.11, 2026-09-01]`. Three routes now, one per
feature that has looked, which is the argument for looking on the fourth rather than assuming.

The first was implemented in feature 001, because only the first was reachable there. The second
belongs to the features that raise it; its shape is recorded in
docs/compatibility/behaviours.md section 1.11 so it does not have to be rediscovered. The fourth
arrived with feature 006 and lives here rather than in `api/images.py` for the reason the whole
module exists: a shape settled once is a shape no later route can get subtly wrong.

**Both of the framework's own refusals had to be replaced, and one was already documented as
done.** Starlette raises an `HTTPException` for an unmatched path and for a wrong method, and
FastAPI answers those with `{"detail": "Not Found"}` - the exact shape behaviours section 1.11
warns is neither of the two. Nothing had noticed, because until feature 001 had routes there was
no path to get wrong. Writing the module docstring is not the same as registering the handler.

**The absent `WWW-Authenticate` is worth keeping absent.** RFC 7235 says a 401 SHOULD carry one,
the reference does not, and adding `Basic` would make a browser open a credentials dialog on a
route no browser was meant to drive. Matching the reference is also the safer behaviour here.
"""

from __future__ import annotations

import json
import secrets
from collections.abc import Callable, Coroutine, Sequence
from typing import Any, get_args

from fastapi.exception_handlers import http_exception_handler
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException
from starlette.requests import ClientDisconnect, Request
from starlette.responses import Response

from atrium.compat.responses import AtriumJSONResponse

#: The shape Starlette expects of a handler, spelled out so the registry below type-checks against
#: what the application factory passes it.
ExceptionHandler = Callable[[Request, Any], Coroutine[Any, Any, Response]]

#: The refusals the framework decides on its own, before any handler of ours runs.
ROUTING_REFUSALS = frozenset({404, 405})


class UnauthenticatedError(Exception):
    """No usable credential on a route that needs one. Answered with an empty 401."""


class ForbiddenError(Exception):
    """A usable credential, and the account may not do this. The third shape at `403`.

    Measured at last, and the shape is the controller's own sentence rather than the emptiness
    this class emitted until 009: a non-administrator naming somebody else on
    `POST /Playlists/{id}/Items?userId=` is answered `403`, `text/plain` with no charset, and the
    same 25 bytes every other controller refusal carries
    `[probe: tools/probe_playlist_visibility.py, Jellyfin 10.11.11, 2026-08-31]`. That refusal is
    005's `/Items?userId=` one route away, so the correction is taken here rather than on 009's
    own routes (009 spec section 3.7, AC-19; 009 plan section 2).

    **A `403` is two shapes on the reference, and this class is only the first of them.** The same
    probe measured `POST /Items/{id}` - the elevated controller the music client renames through -
    answering `403` with **no content type and no body at all**, because that refusal is an
    authorization policy's and never reaches a controller. Both statuses are `403` and the bytes
    are the whole difference, which is behaviours section 1.11's rule applied to one status
    instead of to one route. The other shape is `EmptyForbiddenError` below; it arrived at 009 T10
    rather than at T13, because the playlist controller's own editing test is refused the same way
    - the split is between a refusal *returned* and a refusal *thrown*, not between a controller
    and a policy.

    ⚠️ **One of this class's raise sites is not the measured refusal**, and it does not move to a
    measured shape by changing this handler: `api/deps.py` refuses a live token whose account was
    disabled after it was issued. That is 002 spec section 7 (OQ-5)'s third row and is still
    unmeasured - measuring it means disabling a real account that holds a live token. It answered
    the empty shape by analogy with the empty `401`; it now answers this one by analogy with the
    `403` beside it. Both are analogies.

    **There were two, and the second one is gone.** `api/users.py` refused one user reading
    another, and the reference does not refuse that at all: every authenticated caller is answered
    `200` with the named user's whole object, `Configuration` and `Policy` included, in bytes that
    do not depend on who asked `[probe: tools/probe_user_read.py, Jellyfin 10.11.11, 2026-09-01]`.
    002 spec section 3.7 stated that `403` with no provenance; the route now replicates the
    disclosure (behaviours section 3.22) and raises nothing from this class at all.
    """


class ClientAuthorizationError(Exception):
    """The client-identification header is missing or unreadable where it is required.

    A `400`, and deliberately not a `401`: a client that reads this as one tells its user that
    their password is wrong, when what actually happened is that the client sent a broken header
    (spec section 3.3).
    """


class InvalidCredentialsError(Exception):
    """The username or the password was wrong. A `401` in the controller's shape.

    Distinct from `UnauthenticatedError`, which is the *empty* `401` a route sends when no token
    reached it. Same status, different bytes, decided by which layer refused - which is exactly
    what makes behaviours section 1.11 worth having.
    """


class AccountUnavailableError(Exception):
    """The credentials were not the problem: this account cannot log in at all.

    A `403`, measured, and the difference from `401` is load-bearing. Clients re-authenticate on
    `401` and stop on `403`, so answering `401` here loops a user through a login their correct
    password can never complete.
    `[probe: tools/probe_auth_mechanisms.py, Jellyfin 10.11.11, 2026-08-26]`
    """


#: RFC 9457 `type` URIs, as the reference spells them - `tools.ietf.org`, not `iana.org`, and
#: pointing at RFC 9110's status-code sections. Measured.
#: `[probe: tools/probe_query_envelope.py, Jellyfin 10.11.11, 2026-08-28]`
PROBLEM_TYPE_BAD_REQUEST = "https://tools.ietf.org/html/rfc9110#section-15.5.1"
PROBLEM_TYPE_NOT_FOUND = "https://tools.ietf.org/html/rfc9110#section-15.5.5"

#: The reference's own wording, byte for byte.
VALIDATION_TITLE = "One or more validation errors occurred."
NOT_FOUND_TITLE = "Not Found"

#: The framework's name for "this string did not match the declared pattern".
PATTERN_MISMATCH = "string_pattern_mismatch"

#: What the reference says when one does not, byte for byte, including the expression itself -
#: `/Videos/{id}/stream.a%20b` answers `{"container": ["The field container must match the regular
#: expression '^[a-zA-Z0-9\-\._,|]{0,40}$'."]}`, with the apostrophes escaped as `\u0027` by the
#: serialiser like every other quotable character (behaviours section 1.16). Reproducible exactly
#: because it is a template rather than a parser's output, which is why this one is matched where
#: the JSON parser's message in section 1.11 is a recorded divergence.
#: `[probe: tools/probe_range_matrix.py, Jellyfin 10.11.11, 2026-08-29]`
PATTERN_MESSAGE = "The field {name} must match the regular expression '{pattern}'."


class NotFoundError(Exception):
    """A handler looked and there was nothing there. Answered with a problem-details `404`.

    Not the same refusal as an unmatched path, which is the **empty** `404` of section 1.11's
    first table. Same status, different bytes, decided by which layer refused - and 005 AC-8
    requires an unknown id and an invisible one to be byte-identical, so both go through here.
    """


class ItemNotFoundError(NotFoundError):
    """The item a route was asked about does not exist, or has been removed.

    *(Named `ItemNotFound` by plan section 5. The `Error` suffix is this project's lint rule and
    every exception beside it obeys one, `NotFoundError` included, so the contract's spelling is
    amended rather than exempted.)*

    The same wire shape as `NotFoundError`, and a separate name on purpose: the image route has
    **two** `404`s, and plan section 7 asks for the split to be verified by exception type rather
    than by reading a body. A service that raises one of these has decided *which* lookup failed,
    and that decision is the whole difference between the two bodies below.

    Measured: a well-formed identifier nothing owns answers problem details on
    `/Items/{itemId}/Images/{imageType}`, byte-identical to the same refusal on `/Items/{itemId}`
    `[probe: manual requests via tools/_probe.py, Jellyfin 10.11.11, 2026-08-28]`.
    """


class DeliveryNotFoundError(Exception):
    """A delivery route was asked for bytes it has nowhere to read. Answered with the **third**
    shape - `404`, `text/plain`, the fixed 25 bytes - and not with problem details.

    Deliberately not a `NotFoundError`: the same unknown identifier answers two different bodies
    depending on the route, and this is the pair that proves it. `GET
    /Items/{itemId}/PlaybackInfo` answers RFC 9457 problem details for an id nothing holds, and
    `GET /Videos/{itemId}/stream?static=true` answers `Error processing request.` in `text/plain`
    with no charset - measured on all four `stream` routes in the same run `[probe:
    tools/probe_range_matrix.py, Jellyfin 10.11.11, 2026-08-29]`. The split is behaviours section
    1.11's, from the other side: the negotiation refuses through the framework's own not-found
    result, and the delivery controller throws its own exception before any of that runs
    `[source: Jellyfin.Api/Helpers/StreamingHelpers.cs:111 @ v10.11.11]`.

    Inheriting `NotFoundError` would have made it a problem-details `404` silently, which is the
    reason the two are named apart rather than distinguished by a status code.
    """


class DeliverySourceError(Exception):
    """A `mediaSourceId` names no part of this item. The third shape at **`400`**, measured.

    The reference answers exactly this for a well-formed identifier that matches no source and is
    not the item's own - and answers **`500`** for one that is not an identifier at all, because
    the fallback comparison parses the string before comparing it and a `FormatException` is not
    one of the types its middleware maps `[source:
    Jellyfin.Api/Helpers/StreamingHelpers.cs:136-140,
    Jellyfin.Api/Middleware/ExceptionMiddleware.cs GetStatusCode @ v10.11.11]`, `[probe:
    tools/probe_progressive_delivery.py, Jellyfin 10.11.11, 2026-08-29]`.

    **Atrium answers this `400` for both**, which is the divergence argued in behaviours section
    3.9: one refusal for one meaning, in the shape the reference already sends for the
    neighbouring value of the same parameter.

    And the reference sends it to **both** values one route away: `GET /Audio/{itemId}/universal`
    answers `400`, `text/plain`, the same 25 bytes, to a well-formed identifier naming no source
    and to `banana` alike, because it resolves the source through the negotiation helper and
    nothing there parses the string in order to throw `[probe: tools/probe_universal_audio.py,
    Jellyfin 10.11.11, 2026-08-29]`. So this class is not a third behaviour on any reading: it is
    the one the reference itself gives the same parameter on the sibling route.
    """


class DeliverySegmentRequestError(DeliverySourceError):
    """A segment request carried a start position, which that route refuses outright.

    The reference's first line of `GetDynamicSegment` throws on any `startTimeTicks` above zero -
    a segment already says where it begins, in the `runtimeTicks` its own URI carries, and two
    positions in one request have no defined meaning `[source:
    Jellyfin.Api/Controllers/DynamicHlsController.cs:1450-1453 @ v10.11.11]`. Measured as the
    third shape at `400`, which is the same answer as the parameter above it
    `[probe: tools/probe_transcode_session.py, Jellyfin 10.11.11, 2026-08-29]`.

    A subclass rather than a row of its own: Starlette resolves a handler by walking the
    exception's MRO, so one shape stays one handler, and the name says which refusal it is at the
    place that raises it.
    """


class DeliveryProductionError(Exception):
    """Nothing could be produced for this request. The third shape at `500`, measured.

    Three measured rows, one answer: a container no muxer writes (`stream.banana`,
    `?container=banana`) and a container that cannot hold the streams it was handed
    (`stream.mp3` on a film) each answer `500`, `text/plain`, the fixed 25 bytes - and they do it
    with `Accept-Ranges: none` already on the response, because the produced path writes that
    header before it starts anything `[probe: tools/probe_progressive_delivery.py, Jellyfin
    10.11.11, 2026-08-29]`. This is plan section 7's "ffmpeg dies" row reached before the first
    byte rather than after it, and replication rather than a decision: a failed production is a
    `500` on both servers.
    """


class SubtitleRequestError(Exception):
    """A subtitle fetch was asked for something it will not do. The third shape at `400`.

    Three measured conditions, one answer: an item identifier that names nothing (the all-zero
    form included), a format outside the writable set, and an **image** track asked for as text
    `[probe: tools/probe_subtitle_delivery.py, Jellyfin 10.11.11, 2026-08-30]`.

    They are one class because they are one class on the reference: each of the three reaches an
    `ArgumentException` - a null item, an unknown writer, a conversion that cannot be made - and
    its middleware maps that type and only that type to `400` `[source:
    Jellyfin.Api/Middleware/ExceptionMiddleware.cs:123-136 @ v10.11.11]`. Everything else on the
    same route falls through to `500`, which is `SubtitleUnavailableError` below.

    Not a `DeliverySourceError` despite sharing its wire shape: that one means *this identifier
    names no source of this item*, and on these two routes that same condition answers `500`.
    Sharing the class would have made the difference invisible at the place that raises it.
    """


class SubtitleUnavailableError(Exception):
    """A subtitle fetch found nothing to convert, or could not convert it. The `500` shape.

    Four measured conditions: a `mediaSourceId` naming no source, an index naming no stream, an
    index naming a video or an audio stream, and a negative index - each of them a lookup that
    finds nothing where the reference takes the first match of a sequence and throws
    `[probe: tools/probe_subtitle_delivery.py, Jellyfin 10.11.11, 2026-08-30]`. A failed
    extraction joins them, which is the same `500` for the same reason: nothing came back.

    `text/plain`, the fixed 25 bytes, and **no `Accept-Ranges`** - which is why this does not
    reuse `DeliveryProductionError`. That one writes `Accept-Ranges: none` onto its refusal
    because the produced delivery path had already written the header before the failure; a
    subtitle fetch never writes one at all, measured on every row of the table
    (011 spec section 3.5).
    """


class PlaylistCreationError(Exception):
    """`POST /Playlists` refused the request itself. The third shape at `400`.

    Two rows reach it, and only one of them is parity:

    * **An id in `Ids` that resolves to nothing, reached before any id that does.** The reference
      walks the list to infer a media type when the body names none, and throws on the first id
      it cannot resolve - so the same two ids in the other order answer `200`. Measured, with the
      body: `400`, `text/plain`, the fixed 25 bytes
      `[probe: tools/probe_playlist_creation.py, Jellyfin 10.11.11, 2026-08-31]`.
    * **A request that names no `Name` in either the body or the query**, where the reference
      answers **`500`** in this same shape. That is 009's fifth divergence (behaviours section
      3.19): the status changes, the bytes do not.

    One class for both because they are one shape on the wire, and the raise sites say which row
    they are. Deliberately not `DeliverySourceError`, whose docstring is a statement about a
    `mediaSourceId` and would be a lie at the place this is raised.
    """


class PlaylistMoveError(Exception):
    """`Move` was given an index this server refuses. The same third shape at `400`.

    009's third divergence (behaviours section 3.15): the reference answers an index past the
    caller's entry count with **`500`** and the fixed 25 bytes, and a **negative** one with `204`
    and a move nobody asked for. Atrium refuses both, in the *same* bytes the `500` carries, so
    the status line is the whole of the difference - the argument section 3.19 makes one route
    away `[probe: tools/probe_playlist_move.py, Jellyfin 10.11.11, 2026-09-01]`.

    Deliberately not `PlaylistCreationError`, whose docstring is a statement about `Ids` and a
    `Name` and would be false at the raise site: the classes in this module are read where they
    are raised, and one shape shared by two reasons is two classes.
    """


class EmptyIdentifierError(Exception):
    """An identifier of all zeros arrived where an item was expected. The same third shape.

    **It is not an unknown id, and that is the whole of why this class exists.** A well-formed
    identifier that addresses nothing is skipped - unconditionally by the add route, and after the
    media type has settled by the creation one (009 spec section 3.4). `Guid.Empty` is refused
    instead, on both routes and in every position, with the bare-text `400` and nothing added
    `[probe: tools/probe_playlist_add_remove.py, Jellyfin 10.11.11, 2026-09-01]`. The reference's
    item lookup rejects it before any query runs
    `[source: Emby.Server.Implementations/Library/LibraryManager.cs:1357-1362 @ v10.11.11]`, which
    is why one guard covers both routes here as it does there.

    An empty identifier is what a client sends when a default-initialised field reaches the wire,
    so this is a refusal a real client can meet by accident rather than an exotic one.

    Separate from `PlaylistCreationError` because that class's docstring is a statement about
    `POST /Playlists`, and this refusal belongs to the id list rather than to any one route.
    """


class EmptyForbiddenError(Exception):
    """The other `403`: no body, no content type, and the status line alone.

    009 spec section 3.7's *May edit* column is this shape rather than `ForbiddenError`'s 25
    bytes, and the two are told apart by **how** the reference refuses rather than by which route
    does: a refusal it *returns* as a result carries nothing, where one thrown as an exception is
    rendered by the error middleware into the controller's sentence
    `[probe: tools/probe_playlist_shares.py, Jellyfin 10.11.11, 2026-08-31]`
    `[source: Jellyfin.Api/Controllers/PlaylistsController.cs:383-389 @ v10.11.11]`.

    Two raise sites, and both are measured: the playlist controller's own owner-or-share test on
    every editing route (009 AC-13, AC-14), and the elevated rename controller turning away a
    non-administrator, where the refusal is an authorization policy's and never reaches a
    controller at all (009 spec section 3.8, AC-18, T13).
    """


#: The reference's own sentence, byte for byte, quoted as a complete JSON document by
#: `message_error`: 19 characters, 21 bytes on the wire.
#: `[probe: tools/probe_item_deletion.py, Jellyfin 10.11.11, 2026-09-01]`
UNAUTHORIZED_ACCESS_MESSAGE = "Unauthorized access"


class DeletionNotPermittedError(Exception):
    """`DELETE /Items/{itemId}` was asked to delete a playlist this caller may not. `401`.

    **A status this project associates with no credential, answering a perfectly authenticated
    caller**, which is why it is a class of its own rather than a second status taught to
    `ForbiddenError`: the reference's deletion route refuses with `Unauthorized`, and the body is
    the *fourth* shape - the JSON-encoded bare string `"Unauthorized access"`,
    `application/json; charset=utf-8`, 21 bytes
    `[probe: tools/probe_item_deletion.py, Jellyfin 10.11.11, 2026-09-01]`
    `[source: Jellyfin.Api/Controllers/LibraryController.cs:374-383 @ v10.11.11]`. So one route
    answers `401` in two shapes: this one, and the **empty** `401` `UnauthenticatedError` sends
    when no token reached it at all. Both measured on the same request path.

    **It is also the refusal that discloses**, and that is measured rather than assumed: a caller
    who may not even *read* a playlist is answered this and not `404`, so on this route - unlike
    every other route in 009 - a `404` really does mean "no such item" (009 spec section 3.6).
    """


class MediaDeletionRefusedError(Exception):
    """`DELETE /Items/{itemId}` was asked to delete something that is not a playlist. `403`.

    The one divergence in this project not argued from "no client can tell", and a deliberate
    exception rather than a defect this feature reproduces (behaviours section 4.3): a deletion
    the reference performs would take a file off disk, and v1 has no trash to put it in. The
    status is invented, because for an *entitled* caller the reference has no refusal to copy -
    it deletes - and the third shape is the one every other controller refusal here carries.

    Deliberately not `ForbiddenError`, whose docstring is a statement about an account that may
    not do this: the account is not the reason here, and the same caller is refused whatever their
    `EnableContentDeletion` says (009 spec section 3.6). Deliberately not `EmptyForbiddenError`
    either - no authorization policy is involved and nothing about this refusal is the
    reference's.
    """


class ItemUpdateError(Exception):
    """`POST /Items/{itemId}` was given a body it will not apply. The third shape at `400`.

    Two rows reach it, and only one of them is parity:

    * **A body that omits `Genres`, `Tags` or `ProviderIds`, or sends one of the three as
      `null`.** The reference requires exactly those three of the thirty-nine properties its own
      read hands a client, and refuses the body without them - `400`, `text/plain`, the fixed 25
      bytes. Every other property may be left out, and a body of just those three and a `Name` is
      accepted `[probe: tools/probe_playlist_rename.py, Jellyfin 10.11.11, 2026-09-01]`. So the
      client's round trip is load-bearing rather than incidental, and this row is the reference's
      answer reproduced exactly.
    * **A body carrying no `Name`, or a `Name` that is `null`.** The reference answers `204` and
      **erases the name**, leaving a playlist whose `Name` is absent from every response that
      carries it. That is 009's sixth divergence (behaviours section 3.21): the bytes are the
      row above's, and the status is the whole of the difference.

    One class for both because they are one shape on the wire, and the raise sites say which row
    they are - the same arrangement `PlaylistCreationError` makes for the creation route.
    Deliberately not that class, whose docstring is a statement about `Ids` and about a name in a
    query, neither of which this route has.
    """


class MediaUpdateRefusedError(Exception):
    """`POST /Items/{itemId}` was asked to update something that is not a playlist. `403`.

    The sibling of `MediaDeletionRefusedError` on the other method of the same path, and the same
    kind of refusal: the reference edits every field of every item type here, v1 has a consumer
    for none of that (Principle VI), and 004 T10 measured why it could not honour it anyway - the
    scan and the refresh already fight over `Item.name`, so a renamed film would be un-renamed by
    the next scan. Refusing is the honest answer (behaviours section 5).

    **The shape is the empty one and the deletion's is not**, which is deliberate on both sides.
    This route's other refusal carries no body and no content type, because an authorization
    policy makes it; answering the invented refusal in the same shape means a caller cannot tell
    "you are not an administrator" from "that is not a playlist", and there is nothing here worth
    disclosing. The deletion route has no such neighbour - both of its refusals carry a body - so
    it reaches for the third shape instead (009 plan section 6.6).

    Deliberately not `EmptyForbiddenError`, whose docstring names two refusals the reference
    makes: nothing about this one is the reference's.
    """


#: The reference's own sentence, byte for byte, quoted as a complete JSON document by
#: `message_error`: 18 characters, 20 bytes on the wire. Fixed - it interpolates nothing, unlike
#: the image route's template beside it, so an unknown playlist and a private one that this
#: reader may not learn exists are indistinguishable down to the byte, which is the point.
#: `[probe: tools/probe_playlist_read.py, Jellyfin 10.11.11, 2026-09-01]`
#: `[probe: tools/probe_playlist_visibility.py, Jellyfin 10.11.11, 2026-09-01]`
PLAYLIST_ABSENT_MESSAGE = "Playlist not found"


class PlaylistNotFoundError(Exception):
    """`GET /Playlists/{playlistId}/Items` could not hand this caller a playlist. Fourth shape.

    **Not problem details, and that is the finding rather than a detail.** Every other `404` this
    project raises from a handler is the second shape, and 009 said only *"404 for an unknown
    playlist, and for one the reader may not see"* - a status with no shape. Measured, the route
    answers the **JSON-encoded bare string** `"Playlist not found"`,
    `application/json; charset=utf-8`, 20 bytes - the shape behaviours section 1.11 records for
    the image route, now measured on a second route and a second feature
    `[probe: tools/probe_playlist_read.py, Jellyfin 10.11.11, 2026-09-01]`.

    **Three requests reach it and one does not.** An identifier that addresses nothing, an
    identifier that addresses a real item which is not a playlist, and a playlist this reader may
    not see are one body between them; a **malformed** identifier never gets here at all, because
    the model binder refuses it first with the validation `400` (behaviours section 1.11's fifth
    row). So the `/Items/{itemId}` fetch beside it answers problem details for the same private
    playlist, and the two routes disagree on purpose.

    Deliberately not an `ImageNotFoundError`: that class carries a display name and its docstring
    is a statement about images, and deliberately not a `NotFoundError` subclass, which would
    resolve through the MRO to the problem-details handler and undo the whole finding.
    """


#: The reference's own sentence for a user nobody has, byte for byte, quoted as a complete JSON
#: document by `message_error`: 14 characters, 16 bytes on the wire. Fixed, like the playlist's
#: message above and unlike the image route's template.
#: `[probe: tools/probe_user_read.py, Jellyfin 10.11.11, 2026-09-01]`
USER_ABSENT_MESSAGE = "User not found"


class UserNotFoundError(Exception):
    """`GET /Users/{userId}` was given an identifier no account has. The **fourth** shape at `404`.

    A third route for the JSON-encoded bare string, and the first outside the two features that
    found it: `"User not found"`, `application/json; charset=utf-8`, 16 bytes - and the *same*
    body whoever asks, because this route does not vary its answer by caller at all
    `[probe: tools/probe_user_read.py, Jellyfin 10.11.11, 2026-09-01]`.

    **This is where 002's `403` went.** The route refused a non-administrator naming anybody else,
    and refused an unknown identifier the same way so that the two could not be told apart. The
    reference does neither: it discloses the user (behaviours section 3.22) and answers this for
    an identifier nobody has, to an administrator and to a non-administrator alike. So the
    indistinguishability that `403` was protecting was protecting nothing the reference protects.

    A **malformed** identifier never reaches here - `WireGuid` on the path parameter means the
    validation `400` refuses it first, which is what the reference does too, keyed on `userId`
    and quoting the value back (behaviours section 1.11).

    Deliberately not a `PlaylistNotFoundError` and not a `NotFoundError` subclass: the first is a
    statement about playlists at the raise site, and the second resolves through the MRO to the
    problem-details handler, which is a body no reference server sends on this route.
    """


class NegotiationRefusedError(Exception):
    """A negotiation for an **audio** item found no audio stream to negotiate about. `400`.

    The third shape, and it is the **platform's** refusal rather than one this project designed:
    the reference's audio builder asks the source for its default audio stream and throws when
    there is none `[source: MediaBrowser.Model/Dlna/StreamBuilder.cs:104 @ v10.11.11]`, and its
    middleware maps every `ArgumentException` - which `ArgumentNullException` is - to `400`,
    `text/plain`, and the fixed sentence outside a development environment `[source:
    Jellyfin.Api/Middleware/ExceptionMiddleware.cs:93, 98, 127 @ v10.11.11]`. Measured whole
    rather than read: `400`, `text/plain`, **25 bytes**, `Error processing request.` - byte for
    byte the `CONTROLLER_ERROR_BODY` this project has sent since 002
    `[probe: tools/probe_uninspected_source.py, Jellyfin 10.11.11, 2026-09-03]`.

    **The condition is the missing audio stream and not the unreadable file.** The reference asks
    `GetDefaultAudioStream(null)`, so a readable audio file carrying no audio track is refused
    identically to one nothing could open, and the client's own `AudioStreamIndex` does not enter
    the question at all (012 spec section 3.4, plan section 6.4).

    It refuses the **whole request** and not the source, because it escapes a builder called per
    source: a second part with no audio stream takes the answer down with it even where the first
    part could have been played.

    Deliberately not a `DeliverySourceError`, whose docstring is a statement about a
    `mediaSourceId` and would be false here - this request named a source and that source exists.
    The classes in this module are read where they are raised (009 T10).
    """


class ImageNotFoundError(Exception):
    """The item exists and has no image of that type. Answered with the fourth shape.

    *(Plan section 5 spells it `ImageNotFound`; see the note on `ItemNotFoundError` above.)*

    Carries the item's **display name**, which is what the measured message says and therefore
    what travels to any caller holding an id - the image route requires no token (behaviours
    section 2.10), so the name is disclosed to whoever can name the item. That is the
    id-as-capability consequence, recorded in behaviours sections 1.11 and 2.10 and named here so
    it stays a decision rather than becoming an accident.

    The reference raises it for every way an image can be absent: no row of that type, an
    `imageIndex` past the last backdrop, a chapter with no thumbnail, and a vocabulary member no
    item can hold. The message names the **type**, never the index - `Backdrop/99` answers
    `"… does not have an image of type Backdrop"`
    `[probe: manual requests via tools/_probe.py, Jellyfin 10.11.11, 2026-08-28]`.
    """

    def __init__(self, item_name: str, image_type: str) -> None:
        super().__init__(image_absent_message(item_name, image_type))
        self.item_name = item_name
        self.image_type = image_type


#: The reference's wording, byte for byte, with the two values it interpolates. Measured on four
#: refusals of three kinds - an absent type, an out-of-range index and a chapter with no
#: thumbnail - which all produce this one sentence.
#: `[probe: manual requests via tools/_probe.py, Jellyfin 10.11.11, 2026-08-28]`
IMAGE_ABSENT_TEMPLATE = "{name} does not have an image of type {image_type}"


def image_absent_message(item_name: str, image_type: str) -> str:
    return IMAGE_ABSENT_TEMPLATE.format(name=item_name, image_type=image_type)


def trace_id() -> str:
    """A W3C trace-context identifier, in the shape the reference's `traceId` carries.

    `00-<32 hex>-<16 hex>-00`: version, trace id, parent id, flags. Per request by definition, so
    behaviours section 1.11 compares it by shape rather than by value and the goldens mask it.
    """
    return f"00-{secrets.token_hex(16)}-{secrets.token_hex(8)}-00"


def problem_details(
    status_code: int,
    title: str,
    type_uri: str,
    errors: dict[str, list[str]] | None = None,
) -> Response:
    """The second of the three shapes: RFC 9457 problem details as JSON.

    **The keys stay camelCase whatever content profile was negotiated.** They come from the
    reference's own framework rather than from its API models, so `profile="PascalCase"` does not
    make them `Type` and `Title` - the negotiated media type is echoed, the key spellings are not
    touched. `[probe: tools/probe_query_envelope.py, Jellyfin 10.11.11, 2026-08-28]`

    Key order is the reference's: `type`, `title`, `status`, then `errors` where there is one,
    then `traceId`. It costs nothing to preserve and a golden compares bytes.
    """
    body: dict[str, Any] = {"type": type_uri, "title": title, "status": status_code}
    if errors is not None:
        body["errors"] = errors
    body["traceId"] = trace_id()
    return AtriumJSONResponse(body, status_code=status_code)


#: What the reference says about a value inside a body that did not bind. Measured, and the key
#: it is filed under is the **empty string**.
BODY_VALUE_INVALID = "The supplied value is invalid."

#: The key the reference's JSON deserialiser files its own refusals under, as opposed to the
#: **empty string** the model binder uses. Measured on one route, twice, with the two failures a
#: body can carry: a required property that is absent and a value no vocabulary member matches
#: are both `"$"`, while a malformed identifier in the same body is `""`
#: `[probe: tools/probe_playlist_creation.py, Jellyfin 10.11.11, 2026-08-31]`.
DESERIALISATION_KEY = "$"

#: What the reference says when a property the type declares as required is **absent**. The
#: sentence names the reference's own type, which is a fact about the wire rather than about its
#: code - reproducing it is Principle I, the way `Error processing request.` is - and it is a
#: property the model declares (`AtriumModel.WIRE_TYPE`) rather than something derivable here.
#:
#: ⚠️ **Only the single-property form is measured.** `including:` reads like the head of a list
#: and no v1 body declares two required properties, so what separates two names is unknown.
#: `[probe: tools/probe_playlist_creation.py, Jellyfin 10.11.11, 2026-08-31]`
MISSING_PROPERTY_MESSAGE = (
    "JSON deserialization for type '{wire_type}' was missing required properties "
    "including: '{name}'."
)

#: What it says when that property is **present and null**, which is a different refusal at a
#: different key: the deserialiser accepted the document and the property validator refused the
#: value, so the map is keyed on the property rather than on `$`. Measured beside the row above,
#: and nothing in this repository had asked for the two to be told apart.
#: `[probe: tools/probe_playlist_creation.py, Jellyfin 10.11.11, 2026-08-31]`
PROPERTY_REQUIRED_MESSAGE = "The {name} field is required."

#: What it says when a value matches no member of the vocabulary a property declares, for a
#: property at the **top level** of a body. The byte position there is the position inside the
#: quoted token, not an offset into the request - measured with a one-character token, which
#: answers `3` where an eight-character one answers `10`, unchanged by a body twice as long.
#: `[probe: tools/probe_playlist_creation.py, Jellyfin 10.11.11, 2026-08-31]`
VOCABULARY_MESSAGE = (
    "The JSON value could not be converted to {wire_type}. "
    "Path: $ | LineNumber: 0 | BytePositionInLine: {position}."
)

#: **The same failure has a second shape, and the route decides which.** For a property nested
#: inside a body the `errors` key and the `Path:` are the property's full JSON path, and the
#: position is the byte offset of the end of the offending token **in the document as sent** -
#: `398` for `"dash"`, `395` for `" "` and `396` for `true` in one body, and `153` for a property
#: earlier in that same body. One converter, one exception, two renderings; 012 plan section 6.6
#: measured them side by side on the two routes.
#: `[probe: tools/probe_playback_info.py, Jellyfin 10.11.11, 2026-09-03]`
NESTED_VOCABULARY_MESSAGE = (
    "The JSON value could not be converted to {wire_type}. "
    "Path: {path} | LineNumber: {line} | BytePositionInLine: {position}."
)

#: The framework's names for "this value is in no vocabulary I declare". Two, because a `Literal`
#: and an `Enum` annotation are the same wire contract and report themselves differently.
VOCABULARY_MISMATCH = frozenset({"literal_error", "enum"})

#: One step of a body failure's location: a property, as `(wire spelling, Python name)`, or the
#: index of an entry in a list.
Level = tuple[str, str] | int


def _wire_name(body_model: type[Any] | None, name: str) -> str:
    """The property's spelling on the wire, whichever spelling the framework reported.

    It reports **both**, on one model, depending on how the value failed: a property that is
    absent is located by its alias (`Name`) and one that is present and wrong by the model's own
    field name (`name`). Either would reach a client as a key, and only one of them is a name the
    reference ever sends - which is 007 T8's finding arriving through a second door.
    """
    fields = getattr(body_model, "model_fields", {})
    field = fields.get(name)
    return str(getattr(field, "alias", None) or name)


def _nested_model(annotation: Any) -> type[Any] | None:
    """The model a field holds, through an optional, a union or a list.

    `DeviceProfile | None` and `list[TranscodingProfile]` are both levels a path has to descend,
    and the alias of a property inside one is declared by *that* model rather than by the body's.
    """
    if isinstance(annotation, type) and hasattr(annotation, "model_fields"):
        return annotation
    for argument in get_args(annotation):
        found = _nested_model(argument)
        if found is not None:
            return found
    return None


def _levels(
    location: tuple[Any, ...], body_model: type[Any] | None
) -> tuple[list[Level], type[Any] | None]:
    """Every step of a body failure's location, resolved through the models that own it.

    The walk stops at the first segment the current model does not declare, which is what keeps a
    union's discriminating tag - `(…, "protocol", "int")`, one error per member - out of the path
    a client is shown. The model returned is the one that **owns the last named step**: the two
    sentences that name a reference type name it for the type that declares the property, not for
    the outermost body.
    """
    model = body_model
    owner = body_model
    levels: list[Level] = []
    for segment in location[1:]:
        if isinstance(segment, int):
            levels.append(segment)
            continue
        fields = getattr(model, "model_fields", {})
        name = str(segment)
        if name not in fields:
            break
        owner = model
        levels.append((_wire_name(model, name), name))
        model = _nested_model(fields[name].annotation)
    return levels, owner


def _json_path(levels: Sequence[Level]) -> str:
    """The levels rendered as the reference renders a path: `$.A.B[0].C`."""
    rendered = DESERIALISATION_KEY
    for level in levels:
        rendered += f"[{level}]" if isinstance(level, int) else f".{level[0]}"
    return rendered


#: Everything JSON allows between tokens, as bytes, because a position in this message is counted
#: in bytes and not in characters.
_BLANK = b" \t\n\r"
_QUOTE = 0x22
_BACKSLASH = 0x5C

#: What ends a number, `true`, `false` or `null` - the only values whose length is not written down.
_DELIMITERS = b",]}" + _BLANK


def _past_blanks(raw: bytes, at: int) -> int:
    while at < len(raw) and raw[at] in _BLANK:
        at += 1
    return at


def _end_of_string(raw: bytes, at: int) -> int | None:
    """Just past the closing quote of the string starting at `at`, escapes honoured."""
    index = at + 1
    while index < len(raw):
        if raw[index] == _BACKSLASH:
            index += 2
            continue
        if raw[index] == _QUOTE:
            return index + 1
        index += 1
    return None


def _end_of_container(raw: bytes, at: int) -> int | None:
    """Just past the object or array starting at `at`, counted by depth.

    Strings are stepped over whole rather than scanned for braces, which is the one thing a
    depth counter gets wrong on a document containing `{"Container": "}"}`.
    """
    depth, index = 0, at
    while index < len(raw):
        if raw[index] == _QUOTE:
            end = _end_of_string(raw, index)
            if end is None:
                return None
            index = end
            continue
        if raw[index] in b"{[":
            depth += 1
        elif raw[index] in b"}]":
            depth -= 1
            if depth == 0:
                return index + 1
        index += 1
    return None


def _end_of_value(raw: bytes, at: int) -> int | None:
    """Just past the value starting at `at`, whatever kind of value it is."""
    at = _past_blanks(raw, at)
    if at >= len(raw):
        return None
    if raw[at] == _QUOTE:
        return _end_of_string(raw, at)
    if raw[at] in b"{[":
        return _end_of_container(raw, at)
    index = at
    while index < len(raw) and raw[index] not in _DELIMITERS:
        index += 1
    return index if index > at else None


def _key_at(raw: bytes, at: int) -> str | None:
    """The text of the string starting at `at`, escapes decoded by the parser rather than here."""
    end = _end_of_string(raw, at)
    if end is None:
        return None
    try:
        decoded = json.loads(raw[at:end])
    except ValueError:
        return None
    return decoded if isinstance(decoded, str) else None


def _locate(raw: bytes, at: int, levels: Sequence[Level]) -> int | None:
    """The byte offset just past the value `levels` names, counted from the start of `raw`.

    A key matches **case-insensitively**, against both spellings the model knows, because that is
    how the value got this far: `compat/model.py` accepts any casing a client writes, so the
    property that failed may be spelled in the document differently from the path this reports.
    """
    at = _past_blanks(raw, at)
    if at >= len(raw):
        return None
    if not levels:
        return _end_of_value(raw, at)
    head, rest = levels[0], levels[1:]

    if isinstance(head, int):
        if raw[at] not in b"[":
            return None
        index, position = 0, _past_blanks(raw, at + 1)
        while position < len(raw) and raw[position] not in b"]":
            if index == head:
                return _locate(raw, position, rest)
            position = _past_separator(raw, _end_of_value(raw, position))
            if position < 0:
                return None
            index += 1
        return None

    if raw[at] not in b"{":
        return None
    wanted = {one.lower() for one in head}
    position = _past_blanks(raw, at + 1)
    while position < len(raw) and raw[position] == _QUOTE:
        key, end = _key_at(raw, position), _end_of_string(raw, position)
        if key is None or end is None:
            return None
        position = _past_blanks(raw, end)
        if raw[position : position + 1] != b":":
            return None
        position = _past_blanks(raw, position + 1)
        if key.lower() in wanted:
            return _locate(raw, position, rest)
        position = _past_separator(raw, _end_of_value(raw, position))
        if position < 0:
            return None
    return None


def _past_separator(raw: bytes, end: int | None) -> int:
    """The start of the next member after a value that ended at `end`, or `-1`."""
    if end is None:
        return -1
    position = _past_blanks(raw, end)
    if raw[position : position + 1] == b",":
        return _past_blanks(raw, position + 1)
    return position


def _position_of(raw: bytes | None, levels: Sequence[Level]) -> tuple[int, int] | None:
    """`(LineNumber, BytePositionInLine)` for the end of the token `levels` names, or `None`.

    Both numbers are what the reference's reader reports for the place it stopped. Every measured
    body was one line, where the second number is the offset from the start of the document; the
    split into a line and an offset within it is this reader's own arithmetic and is what makes a
    pretty-printed body answer the same way a compact one does.
    """
    if not raw:
        return None
    end = _locate(raw, 0, list(levels))
    if end is None:
        return None
    return raw.count(b"\n", 0, end), end - (raw.rfind(b"\n", 0, end) + 1)


def _token_position(error: dict[str, Any]) -> int:
    """The position the **top-level** shape reports: the quotes and the token, and nothing else."""
    return len(str(error.get("input", ""))) + 2


def _reported_body_errors(raw: Sequence[Any], body_model: type[Any] | None) -> set[int]:
    """Which of the framework's body failures the reference would have reported: one per property.

    **A union is one property here and several validations to the framework.** A transcoding
    entry's `Protocol` is `StreamProtocol | int`, because an ordinal no member has survives to the
    wire as a number (behaviours section 2.24) - and a value that binds to neither member is
    reported twice, once per member, each located one segment deeper than the property at the
    member's own tag. The reference has one converter and one exception: its `errors` names
    `$.DeviceProfile.TranscodingProfiles[0].Protocol` and nothing else
    `[probe: tools/probe_playback_info.py, Jellyfin 10.11.11, 2026-08-29]`.

    So the failures are grouped by the property they resolve to and one is kept - the vocabulary
    mismatch where there is one, because that is the failure the reference reports and the only
    one that can name the enumeration. Left alone, the second would key itself under 007's `""`
    and answer a map with two entries where every measurement has one.
    """
    kept: dict[tuple[Level, ...], int] = {}
    for index, error in enumerate(raw):
        location = tuple(error.get("loc") or ("",))
        if not location or location[0] != "body":
            continue
        levels, _ = _levels(location, body_model)
        chosen = kept.get(tuple(levels))
        if chosen is None or (
            str(error.get("type", "")) in VOCABULARY_MISMATCH
            and str(raw[chosen].get("type", "")) not in VOCABULARY_MISMATCH
        ):
            kept[tuple(levels)] = index
    return set(kept.values())


def _body_error(
    error: dict[str, Any],
    location: tuple[Any, ...],
    body_model: type[Any] | None,
    sent: bytes | None = None,
) -> tuple[str, str]:
    """One failure inside a request body, as the reference keys and words it.

    Four answers, all four measured on `POST /Playlists` in one run
    `[probe: tools/probe_playlist_creation.py, Jellyfin 10.11.11, 2026-08-31]`:

    * a **required property that is absent** - `"$"`, the deserialiser naming the type it was
      building and the property it did not find;
    * a value matching **no member of a declared vocabulary** - `"$"` as well, because the
      converter throws while the document is still being read;
    * that same required property present and **null** - the *property's* own name, because the
      document deserialised and a validator refused the value;
    * anything else that did not bind - the **empty string** and the fixed sentence, which is what
      007 measured and is left exactly as it was.

    The first two need a name only the model can supply, so a model that declares none falls back
    to the last row rather than inventing one - which is what keeps every body 007 bound answering
    what it answered before.

    **And a failure inside a nested object is keyed by its JSON path, which is the same rule and
    not a fifth answer.** `$` is the path of a top-level failure as the route above reports one;
    a value inside a device profile is keyed `$.DeviceProfile.TranscodingProfiles[0].Protocol`,
    with that path repeated in the sentence and a byte position counted into the document as sent
    `[probe: tools/probe_playback_info.py, Jellyfin 10.11.11, 2026-09-03]`. Only the two rows the
    **deserialiser** keys move: a null refused by a property validator and a value that did not
    bind are the model binder's own keys, and what those are at depth is unmeasured, so they are
    left exactly as 007 measured them (012 plan section 6.6).
    """
    kind = str(error.get("type", ""))
    levels, owner = _levels(location, body_model)
    named = [level for level in levels if not isinstance(level, int)]
    name = named[-1][0] if named else _wire_name(body_model, str(location[-1]))
    path = _json_path(levels)
    nested = len(named) > 1
    wire_type = str(getattr(owner, "WIRE_TYPE", "") or "")
    if kind.startswith("json_"):
        # The text failing to parse is `json_invalid`, and its location is `("body", 0)` - a byte
        # offset rather than a field, so the error's *type* tells the two apart, not `len()`.
        return DESERIALISATION_KEY, str(error.get("msg", BODY_VALUE_INVALID))
    if kind == "missing" and len(location) > 1 and wire_type:
        key = path if nested else DESERIALISATION_KEY
        return key, MISSING_PROPERTY_MESSAGE.format(wire_type=wire_type, name=name)
    if kind in VOCABULARY_MISMATCH:
        vocabulary = dict(getattr(owner, "WIRE_ENUM_TYPES", {})).get(name)
        if vocabulary and nested:
            # The offset of the end of the offending token in the body as sent, which is why the
            # bytes are carried this far at all; a document this reader cannot walk falls back to
            # the shape above rather than to no message (plan section 11, D-6).
            line, position = _position_of(sent, levels) or (0, _token_position(error))
            return path, NESTED_VOCABULARY_MESSAGE.format(
                wire_type=vocabulary, path=path, line=line, position=position
            )
        if vocabulary:
            # The position is the offset inside the quoted token: the opening quote, the token,
            # and the closing quote the reader stops at.
            return DESERIALISATION_KEY, VOCABULARY_MESSAGE.format(
                wire_type=vocabulary, position=_token_position(error)
            )
    if kind != "missing" and len(location) > 1 and error.get("input", "") is None:
        # A null where the type declares a value. The deserialiser was happy; the property was not.
        return name, PROPERTY_REQUIRED_MESSAGE.format(name=name)
    return "", BODY_VALUE_INVALID


def validation_errors(
    raw: list[Any],
    body_parameter: str | None = None,
    body_model: type[Any] | None = None,
    sent: bytes | None = None,
) -> dict[str, list[str]]:
    """The framework's validation failures, keyed and worded as the reference words them.

    The key is the **declared** parameter name rather than the spelling the client sent: a request
    with `Limit=abc` against a route declaring `limit` comes back keyed `limit`, measured, which
    is also what `compat.query_params` canonicalisation produces before the binder ever runs.

    ⚠️ **Only the type-mismatch wording is measured** - `The value 'abc' is not valid.` What the
    reference says for a *missing* required parameter was not measured, so that case carries the
    framework's own message rather than a guess at the reference's.
    `[probe: tools/probe_query_envelope.py, Jellyfin 10.11.11, 2026-08-28]`

    **A refusal of the *body* is keyed differently, and 007 T1 measured how.** The reference files
    the binder's own complaint under `""` (a value inside the body that did not bind) or `"$"`
    (the text was not JSON at all), *and* names the action parameter the body binds to with
    `The <parameter> field is required.` - so one failure spells its keys differently on each
    route. `body_parameter` is that name, read from the route, because the framework here would
    otherwise key the **model's field**: `item_id`, in snake_case, on the wire.
    `[probe: tools/probe_playstate.py, Jellyfin 10.11.11, 2026-08-28]`, behaviours section 1.11.

    **The action-parameter row is not universal, and 009 T8 measured what decides it.** It appears
    when the route's body parameter is **required** and not otherwise: `POST /Playlists` declares
    an optional body - every one of its four measured refusals names one key and no second one -
    where 007's three reporting routes require theirs and name two. `body_parameter` is therefore
    `None` for an optional body (`body_parameter_of`), and `_body_error` above carries the rest.
    `[probe: tools/probe_playlist_creation.py, Jellyfin 10.11.11, 2026-08-31]`

    **`sent` is the body as the client wrote it**, which one of these sentences counts a byte
    offset into and nothing else needs. It is optional so that every caller which has no bytes -
    a query failure, a unit test of the keying - keeps the shape it had.
    """
    collected: dict[str, list[str]] = {}
    reported = _reported_body_errors(raw, body_model)
    for index, error in enumerate(raw):
        location = tuple(error.get("loc") or ("",))
        if location and location[0] == "body":
            if index not in reported:
                continue
            key, message = _body_error(error, location, body_model, sent)
            collected.setdefault(key, []).append(message)
            if body_parameter is not None:
                required = PROPERTY_REQUIRED_MESSAGE.format(name=body_parameter)
                if required not in collected.setdefault(body_parameter, []):
                    collected[body_parameter].append(required)
            continue
        name = str(location[-1])
        pattern = (error.get("ctx") or {}).get("pattern")
        if str(error.get("type", "")) == PATTERN_MISMATCH and pattern:
            # A different sentence, measured: the reference's data annotation says which
            # expression was not matched rather than quoting what the client sent.
            message = PATTERN_MESSAGE.format(name=name, pattern=pattern)
        elif "input" in error:
            message = f"The value '{error['input']}' is not valid."
        else:
            message = str(error.get("msg", "The value is not valid."))
        collected.setdefault(name, []).append(message)
    return collected


def body_parameter_of(request: Request) -> str | None:
    """The name the route's body binds to, which is what the reference's `errors` map names.

    Read off the resolved route rather than guessed: the three reporting routes call theirs
    `playbackStartInfo`, `playbackProgressInfo` and `playbackStopInfo` after the reference's own
    parameters, and a route with no body at all answers `None` and keeps the old keying.

    **An optional body answers `None` too, and that is a measurement rather than a shortcut.**
    The reference names the action parameter in a refusal only where the parameter is required;
    `POST /Playlists` takes an optional body and names one key per failure, never two
    `[probe: tools/probe_playlist_creation.py, Jellyfin 10.11.11, 2026-08-31]`.
    """
    route = request.scope.get("route")
    field = getattr(route, "body_field", None)
    if field is None or not _required(field):
        return None
    name: str | None = getattr(field, "alias", None) or getattr(field, "name", None)
    return name


def _required(field: Any) -> bool:
    """Whether the route declares its body as required. `Body(None)` says it does not."""
    info = getattr(field, "field_info", None)
    is_required = getattr(info, "is_required", None)
    return bool(is_required()) if callable(is_required) else True


def body_model_of(request: Request) -> type[Any] | None:
    """The model the route's body binds to, for the two sentences only it can spell.

    A refusal that names the reference's own type (`MISSING_PROPERTY_MESSAGE`) or the enumeration
    behind one of its properties (`VOCABULARY_MESSAGE`) cannot be written from the failure alone -
    the names are facts about the reference, declared on the model that reproduces it. This reads
    the class off the resolved route so the handler stays global; a route with no body, or one
    whose model declares neither name, falls back to the shape 007 measured.

    The annotation is unwrapped because an **optional** body is declared `Model | None`, and that
    is exactly the shape the only route needing this declares.
    """
    field = getattr(request.scope.get("route"), "body_field", None)
    annotation = getattr(getattr(field, "field_info", None), "annotation", None)
    candidates = get_args(annotation) or (annotation,)
    return next(
        (one for one in candidates if isinstance(one, type) and hasattr(one, "model_fields")), None
    )


async def body_as_sent(request: Request, errors: list[Any]) -> bytes | None:
    """The bytes the client actually sent, for the one sentence that counts an offset into them.

    **Not `exc.body`, which is the *parsed* document.** FastAPI hands the exception the value it
    got from `request.json()` where the text parsed, so a byte position taken from it would be a
    position in a document nobody sent - measured here rather than assumed, and it is what 012
    plan section 11 (D-6) named as the source. The raw bytes are on the request instead, and
    reaching them costs nothing: Starlette gives an exception handler the **same** `Request` the
    route was called with, and any failure located in the body proves the route already read and
    cached it. A failure located anywhere else never asks, so no handler ever touches a receive
    channel that a body might still be arriving on.
    """
    if not any(tuple(error.get("loc") or ())[:1] == ("body",) for error in errors):
        return None
    try:
        return await request.body()
    except (ClientDisconnect, RuntimeError):
        return None


async def validation_handler(request: Request, exc: Exception) -> Response:
    """Replace the framework's `422` with the reference's `400`, status **and** body.

    FastAPI answers an unbindable value with `422 Unprocessable Entity` and
    `{"detail": [...]}`, which is neither the reference's status nor any of its three shapes. The
    replacement is global rather than per route, because the one route that forgets is the one a
    client meets. behaviours sections 1.11 and 1.12: the line is token-versus-type - an
    unrecognised enum *token* is dropped and answered `200`, a value that cannot parse as its
    declared *type* is this.
    """
    raw = list(exc.errors()) if isinstance(exc, RequestValidationError) else []
    return problem_details(
        400,
        VALIDATION_TITLE,
        PROBLEM_TYPE_BAD_REQUEST,
        validation_errors(
            raw,
            body_parameter_of(request),
            body_model_of(request),
            await body_as_sent(request, raw),
        ),
    )


async def not_found_handler(_request: Request, _exc: Exception) -> Response:
    return problem_details(404, NOT_FOUND_TITLE, PROBLEM_TYPE_NOT_FOUND)


#: What a controller's own refusal says, byte for byte. Measured, and it is the same 25 bytes
#: whatever went wrong, which is why the golden responses compare bytes and not status codes.
CONTROLLER_ERROR_BODY = b"Error processing request."

#: No `charset`, unlike the JSON responses (behaviours section 1.10). Measured.
CONTROLLER_ERROR_TYPE = "text/plain"


def empty_error(status_code: int, headers: dict[str, str] | None = None) -> Response:
    """A refusal with a status line and nothing else, as the reference sends."""
    return Response(status_code=status_code, headers=headers)


async def unauthenticated_handler(_request: Request, _exc: Exception) -> Response:
    return empty_error(401)


def controller_error(status_code: int, headers: dict[str, str] | None = None) -> Response:
    """The third shape: a status, `text/plain`, and the reference's fixed sentence.

    The content type is set as a **header** rather than through `media_type`, which is not
    fussiness. Starlette appends `; charset=utf-8` to any `text/*` media type it is given, and the
    reference sends bare `text/plain` here - measured, and different from its JSON responses, which
    do carry the charset (behaviours sections 1.10 and 1.11). Going through `media_type` produced
    `text/plain; charset=utf-8` on every refusal from this feature, which is a difference a client
    can see, and it took a test comparing the header to notice.
    """
    return Response(
        content=CONTROLLER_ERROR_BODY,
        status_code=status_code,
        headers={"Content-Type": CONTROLLER_ERROR_TYPE, **(headers or {})},
    )


async def forbidden_handler(_request: Request, _exc: Exception) -> Response:
    """The measured `403`: `text/plain`, no charset, the fixed 25 bytes.

    Below `controller_error` rather than beside `unauthenticated_handler` on purpose - the
    grouping is by wire shape, and this refusal left the empty group when it was measured.
    """
    return controller_error(403)


async def client_authorization_handler(_request: Request, _exc: Exception) -> Response:
    return controller_error(400)


async def invalid_credentials_handler(_request: Request, _exc: Exception) -> Response:
    return controller_error(401)


async def account_unavailable_handler(_request: Request, _exc: Exception) -> Response:
    return controller_error(403)


def message_error(status_code: int, message: str) -> Response:
    r"""The fourth shape: the message as a JSON-encoded **bare string**.

    A quoted string is a complete JSON document, and that is exactly what the reference sends -
    `"#1 to Infinity does not have an image of type Box"`, 51 bytes including the quotes, under
    `application/json; charset=utf-8`. Going through `AtriumJSONResponse` rather than writing the
    bytes by hand is what makes the escaping and the negotiated profile the same here as
    everywhere else: an item called `DW Español` comes back as `DW Espa\u00F1ol`, uppercase hex,
    measured on the reference and produced here by the response class rather than by this
    function. `[probe: manual requests via tools/_probe.py, Jellyfin 10.11.11, 2026-08-28]`
    """
    return AtriumJSONResponse(message, status_code=status_code)


async def delivery_not_found_handler(_request: Request, _exc: Exception) -> Response:
    return controller_error(404)


async def delivery_source_handler(_request: Request, _exc: Exception) -> Response:
    return controller_error(400)


async def playlist_creation_handler(_request: Request, _exc: Exception) -> Response:
    return controller_error(400)


async def empty_identifier_handler(_request: Request, _exc: Exception) -> Response:
    return controller_error(400)


async def playlist_move_handler(_request: Request, _exc: Exception) -> Response:
    return controller_error(400)


async def empty_forbidden_handler(_request: Request, _exc: Exception) -> Response:
    """The `403` with nothing in it - beside `unauthenticated_handler`, whose group it shares.

    `ForbiddenError` left this group when it was measured (009 T2); this class is what the shape
    it left behind is now called, because two of the reference's refusals really do send it.
    """
    return empty_error(403)


async def delivery_production_handler(_request: Request, _exc: Exception) -> Response:
    """The `500` a production that could not start answers, with the header it already wrote.

    `Accept-Ranges: none` rides on the refusal because the reference sets it before the encoder
    is asked for anything and the failure happens after that - measured, and the reason this
    handler exists rather than the request reusing `controller_error(500)`.
    """
    return controller_error(500, headers={"Accept-Ranges": "none"})


async def subtitle_request_handler(_request: Request, _exc: Exception) -> Response:
    return controller_error(400)


async def negotiation_refused_handler(_request: Request, _exc: Exception) -> Response:
    """The `400` a negotiation answers when there is no audio stream to negotiate about.

    Plain `controller_error(400)`: the reference's exception middleware writes one body for every
    `ArgumentException` it maps, so this is the same twenty-five bytes as every other row above
    and the class - not the shape - is what says which refusal it is.
    """
    return controller_error(400)


async def subtitle_unavailable_handler(_request: Request, _exc: Exception) -> Response:
    """The `500` a subtitle fetch answers when there was nothing to convert.

    Plain `controller_error(500)` and not `delivery_production_handler`: the two say the same
    twenty-five bytes at the same status, and the delivery one carries `Accept-Ranges: none`
    which these routes never send (011 spec section 3.5).
    """
    return controller_error(500)


async def playlist_not_found_handler(_request: Request, _exc: Exception) -> Response:
    return message_error(404, PLAYLIST_ABSENT_MESSAGE)


async def user_not_found_handler(_request: Request, _exc: Exception) -> Response:
    return message_error(404, USER_ABSENT_MESSAGE)


async def deletion_not_permitted_handler(_request: Request, _exc: Exception) -> Response:
    """The `401` with a body - beside `playlist_not_found_handler`, whose shape it shares.

    Not beside `unauthenticated_handler`, which sends the *empty* `401` on the same route: the
    grouping in this module is by wire shape, and these two share only a status line.
    """
    return message_error(401, UNAUTHORIZED_ACCESS_MESSAGE)


async def media_deletion_refused_handler(_request: Request, _exc: Exception) -> Response:
    return controller_error(403)


async def item_update_handler(_request: Request, _exc: Exception) -> Response:
    return controller_error(400)


async def media_update_refused_handler(_request: Request, _exc: Exception) -> Response:
    """The invented `403` of the rename route, in the *empty* shape rather than the third.

    Beside `media_deletion_refused_handler`, which is the same refusal on the other method of the
    same path in a different shape - and the difference is the point rather than an inconsistency:
    the rename's other `403` is empty, so this one is too (`MediaUpdateRefusedError`).
    """
    return empty_error(403)


async def image_not_found_handler(_request: Request, exc: Exception) -> Response:
    message = str(exc) if isinstance(exc, ImageNotFoundError) else NOT_FOUND_TITLE
    return message_error(404, message)


async def routing_handler(request: Request, exc: Exception) -> Response:
    """Answer an unmatched path or an unavailable method as the reference does.

    `Allow` is rebuilt from the route table rather than taken from the exception, because
    Starlette fills it from the first route whose path matched and a path can be several routes -
    `/System/Ping` is two. See `atrium.compat.routing.RouteTable.methods_for`.
    """
    if not isinstance(exc, HTTPException) or exc.status_code not in ROUTING_REFUSALS:
        # Not a routing refusal: a handler raised this deliberately, and its shape is problem
        # details rather than emptiness. Nothing in feature 001 raises one, so this defers to the
        # framework instead of inventing a shape the feature that needs it will have to measure.
        return await http_exception_handler(request, exc)  # type: ignore[arg-type]

    headers = None
    if exc.status_code == 405:
        allowed = request.app.state.routes.methods_for(request.url.path)
        # Sorted, so two servers built from the same routes advertise the same string
        # (Principle VII) - and alphabetical is what the reference sends on the one measured
        # pair where alphabetical and registration order differ: PUT /UserFavoriteItems/{itemId}
        # answers "Allow: DELETE, POST" (behaviours section 1.11, probe_routing 2026-08-28).
        headers = {"Allow": ", ".join(sorted(allowed))} if allowed else None
    return empty_error(exc.status_code, headers)


#: Registered by the application factory. Kept here so the wire shape of an error lives beside the
#: wire shape of everything else.
EXCEPTION_HANDLERS: dict[int | type[Exception], ExceptionHandler] = {
    UnauthenticatedError: unauthenticated_handler,
    ForbiddenError: forbidden_handler,
    ClientAuthorizationError: client_authorization_handler,
    InvalidCredentialsError: invalid_credentials_handler,
    AccountUnavailableError: account_unavailable_handler,
    NotFoundError: not_found_handler,
    # `ItemNotFoundError` inherits `NotFoundError` and needs no row: Starlette resolves a
    # handler by walking the exception's MRO, so the subclass finds the base's handler and the
    # two shapes stay one shape. `ImageNotFoundError` does not inherit it - different shape.
    ImageNotFoundError: image_not_found_handler,
    # Not a `NotFoundError` subclass, and the row is what makes the difference real: the four
    # delivery routes answer the third shape where every other `404` in this project answers
    # problem details (behaviours section 1.11, measured 2026-08-29).
    DeliveryNotFoundError: delivery_not_found_handler,
    # 008 T7's two, and they are the same shape at two statuses: `mediaSourceId` naming no part
    # is the measured `400`, and a production that could not start is the measured `500`.
    DeliverySourceError: delivery_source_handler,
    DeliveryProductionError: delivery_production_handler,
    # 009 T8's, and it is the third shape at `400` for a third reason: the route walked the id
    # list it was given and refused it. A row of its own rather than a `DeliverySourceError`
    # because the class is read at the raise site, where "no such media source" would be false.
    PlaylistCreationError: playlist_creation_handler,
    # 009 T10's two. The first is the same bytes as the row above at the same status and is a
    # separate class because it belongs to the id list rather than to one route - the reference
    # refuses an all-zeros identifier in its item lookup, which both write routes and the
    # creation path go through. The second is the `403` shape `ForbiddenError` used to send: a
    # refusal the reference **returns** rather than throws carries no body and no content type,
    # and an editing route refused by the playlist's own owner-or-share test is one of the two
    # places that happens (009 spec section 3.7, AC-13, AC-14).
    EmptyIdentifierError: empty_identifier_handler,
    EmptyForbiddenError: empty_forbidden_handler,
    # 009 T11's, and it is the third shape at `400` for a third reason again: an index outside
    # the entries this caller can see. The bytes are the ones the reference's own `500` carries,
    # so the status is the whole divergence (behaviours section 3.15).
    PlaylistMoveError: playlist_move_handler,
    # 009 T9's, and it is the *fourth* shape at `404` - the one status this project had
    # thought settled. The playlist read route answers a JSON-encoded bare string where
    # every `NotFoundError` beside it answers problem details, so the row exists to keep
    # the class off `NotFoundError`'s MRO rather than merely to name a handler.
    PlaylistNotFoundError: playlist_not_found_handler,
    # 002's, arriving three features late: `GET /Users/{userId}` answers that same fourth shape
    # with `"User not found"` for an identifier no account has - to an administrator and to a
    # non-administrator alike, because the route refuses neither of them
    # (behaviours section 3.22). It is the `404` that replaced the `403` this route used to send.
    UserNotFoundError: user_not_found_handler,
    # 009 T12's two, and they are the two halves of one route. The first is the *fourth* shape at
    # `401` - a status this project had only ever sent empty - and it is the reference's own
    # refusal for a playlist this caller may not delete. The second is the invented `403` of
    # behaviours section 4.3, in the third shape, for everything on this route that is not a
    # playlist: two refusals, two statuses, and only one of them is a divergence.
    DeletionNotPermittedError: deletion_not_permitted_handler,
    MediaDeletionRefusedError: media_deletion_refused_handler,
    # 009 T13's two, and they are the other method of that same path. The first is the third shape
    # at `400` for a body this route will not apply - the reference's own refusal for a body
    # missing any of `Genres`, `Tags` and `ProviderIds`, and this server's for one missing the
    # `Name` the reference would erase (behaviours section 3.21). The second is the invented `403`
    # for an item that is not a playlist, in the **empty** shape and not the deletion's third one,
    # because the refusal beside it on this route is empty and telling them apart discloses
    # nothing worth disclosing (009 plan section 6.6).
    ItemUpdateError: item_update_handler,
    MediaUpdateRefusedError: media_update_refused_handler,
    # 011 T7's two, and they are the same shape at two statuses again - but split differently
    # from the pair above: on the subtitle fetch routes a `mediaSourceId` naming nothing is the
    # `500` and not the `400`, which is the whole reason they are their own classes.
    SubtitleRequestError: subtitle_request_handler,
    SubtitleUnavailableError: subtitle_unavailable_handler,
    # 012 T6's, and it is the third shape at `400` reached by a route that had never sent it: a
    # negotiation for an audio item with no audio stream. Its own class because the class is read
    # at the raise site and every neighbouring one would be false there - the request named a
    # source, that source exists, and nothing about a subtitle or a playlist is involved. The
    # shape is the platform's: an `ArgumentNullException` out of the audio builder, mapped like
    # every other `ArgumentException` (012 spec section 3.4).
    NegotiationRefusedError: negotiation_refused_handler,
    RequestValidationError: validation_handler,
    HTTPException: routing_handler,
}

__all__ = [
    "CONTROLLER_ERROR_BODY",
    "CONTROLLER_ERROR_TYPE",
    "EXCEPTION_HANDLERS",
    "IMAGE_ABSENT_TEMPLATE",
    "NOT_FOUND_TITLE",
    "PATTERN_MESSAGE",
    "PATTERN_MISMATCH",
    "PLAYLIST_ABSENT_MESSAGE",
    "PROBLEM_TYPE_BAD_REQUEST",
    "PROBLEM_TYPE_NOT_FOUND",
    "PROPERTY_REQUIRED_MESSAGE",
    "ROUTING_REFUSALS",
    "UNAUTHORIZED_ACCESS_MESSAGE",
    "USER_ABSENT_MESSAGE",
    "VALIDATION_TITLE",
    "AccountUnavailableError",
    "ClientAuthorizationError",
    "DeletionNotPermittedError",
    "DeliveryNotFoundError",
    "DeliveryProductionError",
    "DeliverySegmentRequestError",
    "DeliverySourceError",
    "EmptyForbiddenError",
    "EmptyIdentifierError",
    "ExceptionHandler",
    "ForbiddenError",
    "ImageNotFoundError",
    "InvalidCredentialsError",
    "ItemNotFoundError",
    "ItemUpdateError",
    "MediaDeletionRefusedError",
    "MediaUpdateRefusedError",
    "NegotiationRefusedError",
    "NotFoundError",
    "PlaylistCreationError",
    "PlaylistMoveError",
    "PlaylistNotFoundError",
    "SubtitleRequestError",
    "SubtitleUnavailableError",
    "UnauthenticatedError",
    "UserNotFoundError",
    "account_unavailable_handler",
    "client_authorization_handler",
    "controller_error",
    "deletion_not_permitted_handler",
    "empty_error",
    "empty_forbidden_handler",
    "empty_identifier_handler",
    "forbidden_handler",
    "image_absent_message",
    "image_not_found_handler",
    "invalid_credentials_handler",
    "item_update_handler",
    "media_deletion_refused_handler",
    "media_update_refused_handler",
    "message_error",
    "negotiation_refused_handler",
    "not_found_handler",
    "playlist_move_handler",
    "playlist_not_found_handler",
    "problem_details",
    "routing_handler",
    "trace_id",
    "unauthenticated_handler",
    "user_not_found_handler",
    "validation_errors",
    "validation_handler",
]
