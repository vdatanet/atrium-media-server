# SPDX-License-Identifier: GPL-3.0-or-later
"""`/Library/VirtualFolders` and `/Library/Refresh` - listing, adding and scanning libraries.

Three of the reference's operations and nothing else of its two controllers (014 spec section 2).
**Two policies, and the difference is the point.** Listing and adding sit behind
`require_setup_or_administrator`, the setup window of spec section 3.1, because the reference's
library-structure controller carries the first-time-setup policy whole
`[source: Jellyfin.Api/Controllers/LibraryStructureController.cs:30 @ v10.11.11]`. `POST
/Library/Refresh` lives in another controller under an elevation policy alone
`[source: Jellyfin.Api/Controllers/LibraryController.cs:331-334 @ v10.11.11]`, so it requires an
administrator in both states: a library can be added during setup and not scanned on its own.

**Neither write waits for a scan.** Adding with `refreshLibrary=true` and refreshing both hand
libraries to `Scanner.request` and answer `204` at once, as the reference answers them
`[probe: tools/probe_first_time_setup.py, Jellyfin 10.11.11, 2026-09-13]`.

**What a listed library states is what this server honours, and nothing more.** `LibraryOptions`
carries `PathInfos` alone where the reference sends 37 properties (OQ-13, behaviours section 5),
`PrimaryImageItemId` is never sent because this server generates no library image (behaviours
section 5), and `ItemId` is each library's own view even beside a name differing only in case,
where the reference's listing gives both one (behaviours section 3.32).

See specs/014-first-time-setup/spec.md sections 3.5 to 3.7 and plan.md sections 5 and 6.6.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Annotated, Final

from fastapi import APIRouter, Depends, Request, Response
from fastapi.exceptions import RequestValidationError

from atrium.api.deps import (
    get_sessions,
    require_administrator,
    require_setup_or_administrator,
)
from atrium.compat.errors import PROPERTY_REQUIRED_MESSAGE, controller_error
from atrium.compat.model import AtriumModel
from atrium.db.engine import session_scope
from atrium.db.repositories import LibraryRepository
from atrium.domain.items import CollectionType
from atrium.domain.library import Library
from atrium.domain.user import User
from atrium.library import config
from atrium.library.identity import for_library
from atrium.library.scanner import Scanner, ScanTrigger

logger = logging.getLogger(__name__)

router = APIRouter(tags=["LibraryStructure"])

#: The eight declared types by their folded spelling. A value is matched ignoring case, as every
#: vocabulary token in a query is (behaviours section 1.12); anything else - `photos` included,
#: which the reference answers `204` and stores with no type - is no type (spec section 3.6.1).
_COLLECTION_TYPES: Final = {member.value.lower(): member for member in CollectionType}

#: What the window admits. `None` is a caller this machine sent during setup; nothing reads it.
SetupCaller = Annotated[User | None, Depends(require_setup_or_administrator)]


# --------------------------------------------------------------------------------------------
# The shapes
# --------------------------------------------------------------------------------------------


class MediaPathInfo(AtriumModel):
    """`[spec: MediaPathInfo]` - one property, `Path`. Optional here so that an entry without one
    binds, and is then refused as a path that does not exist, which is what the reference's
    directory test makes of it."""

    path: str | None = None


class LibraryOptionsIn(AtriumModel):
    """The body's `LibraryOptions`, as far as this server reads it: its `PathInfos`.

    Every other of the reference's properties is ignored - accepted, not bound, not applied - which
    is OQ-13 as amended on 2026-09-14.
    """

    path_infos: list[MediaPathInfo] | None = None


class AddVirtualFolderDto(AtriumModel):
    """`[spec: AddVirtualFolderDto]` - the optional body of `POST /Library/VirtualFolders`."""

    library_options: LibraryOptionsIn | None = None


class LibraryOptionsOut(AtriumModel):
    """A listed library's `LibraryOptions`: **`PathInfos` and no other property** (OQ-13).

    Each property of the reference's 37 enters with the behaviour it describes, so stating the
    other 36 at their defaults would describe features this server does not have (behaviours
    section 5).
    """

    path_infos: list[MediaPathInfo]


class VirtualFolderInfo(AtriumModel):
    """`[spec: VirtualFolderInfo]`, in the reference's declaration order.

    **`PrimaryImageItemId` is not declared at all**, so it cannot be sent by accident (behaviours
    section 5). `CollectionType` and `RefreshProgress` are `None` where the reference sends no key,
    and a null property is absent (behaviours section 1.7) - read on the reference's raw rows, 19
    of them, none carrying either as `null`
    `[probe: tools/probe_first_time_setup.py, Jellyfin 10.11.11, 2026-09-14]`.
    """

    name: str
    locations: list[str]
    collection_type: str | None = None
    library_options: LibraryOptionsOut
    item_id: str
    refresh_progress: float | None = None
    refresh_status: str


def _listed(library: Library, scanner: Scanner) -> VirtualFolderInfo:
    refresh = scanner.refresh_state(library.id)
    return VirtualFolderInfo(
        name=library.name,
        locations=list(library.roots),
        collection_type=(
            library.collection_type.value if library.collection_type is not None else None
        ),
        library_options=LibraryOptionsOut(
            path_infos=[MediaPathInfo(path=root) for root in library.roots]
        ),
        item_id=for_library(library.id),
        refresh_progress=refresh.progress,
        refresh_status=refresh.status,
    )


def _scanner(request: Request) -> Scanner:
    scanner: Scanner = request.app.state.scanner
    return scanner


# --------------------------------------------------------------------------------------------
# The routes
# --------------------------------------------------------------------------------------------


@router.get("/Library/VirtualFolders")
async def get_virtual_folders(request: Request, _caller: SetupCaller) -> list[VirtualFolderInfo]:
    """`GetVirtualFolders` - every library, one row each (spec section 3.5).

    `RefreshStatus` and `RefreshProgress` are the scanner's: `Active` with a percentage only while
    a scan the library was added with is running, and `Idle` with no progress otherwise - including
    during a scan `POST /Library/Refresh` started, which is the reference's own asymmetry.
    """
    scanner = _scanner(request)
    with session_scope(get_sessions(request)) as opened:
        libraries = LibraryRepository(opened).all()
    return [_listed(library, scanner) for library in libraries]


def _name_refused() -> RequestValidationError:
    """The validation `400` keyed `name`, for a name that is absent, empty or whitespace.

    **Raised here rather than declared as a required parameter, and the sentence is why.** The
    reference's binder turns an empty or whitespace value into no value and refuses that as a
    required one, so all three cases are one refusal - measured as one shape keyed `name`, its
    sentence elided in the reading `[probe: tools/probe_first_time_setup.py, Jellyfin 10.11.11,
    2026-09-13]`. Declared required, this framework reports an absent value with an input the
    handler quotes back as `The value 'None' is not valid.`, and an empty one as `The value '' is
    not valid.` - two sentences for what the reference answers as one. The sentence sent is the
    one that binder's required-value refusal carries where it was measured, on a body property
    (`PROPERTY_REQUIRED_MESSAGE`, behaviours section 1.11) - **read and not measured on this
    route**. The pinned document declares `name` without `required` `[spec: AddVirtualFolder]`,
    which is what an optional declaration here also publishes (014 T7, 2026-09-14).
    """
    return RequestValidationError(
        [
            {
                "type": "missing",
                "loc": ("query", "name"),
                "msg": PROPERTY_REQUIRED_MESSAGE.format(name="name"),
            }
        ]
    )


def _requested_paths(paths: str | None, body: AddVirtualFolderDto | None) -> list[str | None]:
    """The query's `paths`, or the body's `PathInfos` when the query names none (spec section 3.6).

    The reference splits one value on commas dropping empty entries, trims each, and uses the body's
    paths whenever that leaves nothing - so `paths=` is the body's paths too
    `[source: Jellyfin.Api/Controllers/LibraryStructureController.cs:84-91 @ v10.11.11]`.
    """
    from_query = [token.strip() for token in (paths or "").split(",") if token]
    if from_query:
        return list(from_query)
    options = body.library_options if body is not None else None
    if options is None or options.path_infos is None:
        return []
    return [info.path for info in options.path_infos]


def _admitted_roots(requested: list[str | None]) -> tuple[str, ...] | None:
    """The roots a library is added with, or `None` for the one refusal every path rule shares.

    In plan section 6.6's order: a path that is not absolute, then one that is not an existing
    directory, then two one inside the other. A path given twice is one root, which `create`
    already makes of it. The refusal is the same 25 bytes whichever rule refused, so the order is
    not observable; it is kept because it is the order the rules are argued in (behaviours section
    3.31).
    """
    try:
        cleaned = tuple(config.normalise_root(path or "") for path in requested)
    except ValueError:
        return None
    if not all(Path(root).is_dir() for root in cleaned):
        return None
    try:
        config.require_roots(cleaned)
    except ValueError:
        return None
    return cleaned


@router.post("/Library/VirtualFolders", status_code=204)
async def add_virtual_folder(
    request: Request,
    _caller: SetupCaller,
    name: str | None = None,
    collectionType: str | None = None,  # noqa: N803 - the reference's spellings, throughout
    paths: str | None = None,
    refreshLibrary: bool = False,  # noqa: N803
    libraryOptionsDto: AddVirtualFolderDto | None = None,  # noqa: N803
) -> Response:
    """`AddVirtualFolder` - plan section 6.6, step by step.

    1. `name` absent, empty or whitespace - the validation `400` keyed `name`;
    2. `collectionType` - one of the eight, ignoring case, or no type;
    3. the paths - refused `400` `Error processing request.` with nothing added when one is not
       absolute, is not an existing directory, or two are one inside the other; none is a library
       with no roots;
    4. the name settled against every library's, exactly;
    5. the library **and its view** in one transaction, then a scan requested if asked for;
    6. `204`, with nothing of the body applied but the paths step 3 read.
    """
    if config.is_blank(name):
        raise _name_refused()
    assert name is not None  # noqa: S101 - is_blank answered True for None
    kind = _COLLECTION_TYPES.get((collectionType or "").lower())
    roots = _admitted_roots(_requested_paths(paths, libraryOptionsDto))
    if roots is None:
        return controller_error(400)
    with session_scope(get_sessions(request)) as opened:
        settled = config.settle_name(name, LibraryRepository(opened).names())
        library = config.create_with_view(opened, settled, kind, roots)
    logger.info(
        "library %r added (%s) over %d path(s)",
        library.name,
        kind.value if kind is not None else "no type",
        len(library.roots),
    )
    if refreshLibrary:
        _scanner(request).request([library.id], ScanTrigger.ADDED)
    return Response(status_code=204)


@router.post("/Library/Refresh", status_code=204)
async def refresh_library(
    request: Request,
    _caller: Annotated[User, Depends(require_administrator)],
) -> Response:
    """`RefreshLibrary` - every library scanned, and the `204` sent as the scan starts (spec
    section 3.7). A refresh asked for during a pass is coalesced into one more pass, and nothing
    running is cancelled (plan section 6.5)."""
    _scanner(request).request(None, ScanTrigger.REFRESH)
    return Response(status_code=204)


__all__ = [
    "AddVirtualFolderDto",
    "LibraryOptionsIn",
    "LibraryOptionsOut",
    "MediaPathInfo",
    "VirtualFolderInfo",
    "router",
]
