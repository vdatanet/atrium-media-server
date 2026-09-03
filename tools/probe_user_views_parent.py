#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""What does a `/UserViews` row carry in `ParentId`, and on which rows?

Two readings in this repository disagreed, and neither was wrong about what it saw.

On **2026-08-27** `tools/probe_item_shapes.py` measured six view rows on an operator's server and
recorded *"`ParentId` arrived as an explicit `null` on 2 of the 6 `/UserViews` rows"*, beside
*"`UserViews` rows report Type: CollectionFolder, UserView"*
(specs/005-item-query-api/notes/item-shapes.md sections 5 and 6). On **2026-09-03** a conformance
sweep against a single-use instance of the pinned image measured an **identifier** on every row -
the only `TYPE` difference in the whole sweep, and a `TYPE` difference breaks a decoder.

**Both are the same behaviour seen on different rows**, and this probe is what establishes that.
`/UserViews` answers two kinds of row, and which kind a library produces is a property of the
*server's configuration*, never of the route:

* the library's own **`CollectionFolder`**, which is the default for every library and which
  carries the identifier of the **`UserRootFolder`** every library hangs off - one item, named
  `Media Folders`, fetchable through `/Items/{itemId}`; and
* a synthesised **`UserView`**, which carries an explicit `null` - grouped libraries collapsed
  into one view, the server-wide `Folders` view, the `Playlists` view, and any row a
  `presetViews` parameter turns into a shadow view.

Both kinds arrive **in the same response**, so this is a per-row property and not a per-server
one, and the 2026-08-27 server had two rows of the second kind.

**The mechanism is not an override of the null-omission setting**, which is what
[behaviours section 1.7](../docs/compatibility/behaviours.md) recorded as unestablished.
`BaseItemDto.ParentId` is a `Guid?` `[source: MediaBrowser.Model/Dto/BaseItemDto.cs:273 @
v10.11.11]` assigned from a **non-nullable** `Guid` - `dto.ParentId = item.DisplayParentId`
`[source: Emby.Server.Implementations/Dto/DtoService.cs:942-945 @ v10.11.11]` - so the property is
never CLR-null and `DefaultIgnoreCondition = WhenWritingNull` never has anything to omit. What
writes the JSON `null` is the registered converter, on `Guid.Empty` and only on it
`[source: src/Jellyfin.Extensions/Json/Converters/JsonNullableGuidConverter.cs:19-26,
src/Jellyfin.Extensions/Json/JsonDefaults.cs:38 @ v10.11.11]`. `ChannelId` is the same three
lines `[source: MediaBrowser.Model/Dto/BaseItemDto.cs:155,
Emby.Server.Implementations/Dto/DtoService.cs:1331 @ v10.11.11]`, which is why exactly two
properties survive a setting nothing overrides.

A `CollectionFolder`'s `DisplayParentId` is its real parent, the user root folder; a synthesised
view's is whatever `GetNamedView` was given, and the two overloads that build the grouped view and
the `Folders` view pass `Guid.Empty`
`[source: Emby.Server.Implementations/Library/UserViewManager.cs:110-113, 190-193,
Emby.Server.Implementations/Library/LibraryManager.cs:2409-2416 @ v10.11.11]`.

**The grouped view needs two libraries, not one.** A single grouped folder of an eligible type
collapses back to the folder itself and no `UserView` is made
`[source: Emby.Server.Implementations/Library/UserViewManager.cs:174-190 @ v10.11.11]`, which is
measured here as its own condition because it is the difference between a null appearing and not.

**It never touches a server somebody owns.** Answering the question means adding libraries,
grouping them, turning a server-wide view on and making a seat - writes, all of them - so it
refuses a server argument outright and measures only a single-use instance of the pinned version
that it creates and destroys, including on failure (010 spec section 3.1, ADR-0007).

**The tree is four empty directories** rather than this repository's fixture. What a view row
carries is a property of the library root, and the files under it change nothing: the same six
readings were taken over the fixture tree on 2026-09-03 and answered identically. Four empty
directories keep the probe free of ffmpeg and of `tests/`, which a probe on the 3.9 floor should
be.

Writes: to its own instance only - four libraries, one throwaway seat, one playlist, the
administrator's grouping preference and the server's `EnableFolderView`, all of it destroyed with
the container.

Usage:
    python3 tools/probe_user_views_parent.py --allow-writes
"""

from __future__ import annotations

import argparse
import contextlib
import importlib.util
import json
import secrets
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, Iterator, List, Set, Tuple

HERE = Path(__file__).resolve().parent
REPOSITORY = HERE.parent

#: The mounted tree. Under `reference/` because that is the git-ignored place development-time
#: material lands and because a container runtime on macOS does not mount the directory `tempfile`
#: picks - `probe_reference_scan.py`'s finding, and the reason no probe here uses `tempfile`.
TREE = REPOSITORY / "reference" / "user-views-tree"

#: The libraries, and the shape is the measurement: **two** of one grouping-eligible type, because
#: one collapses back to the folder and produces no view to be null; one more eligible type and
#: one ineligible one, so a reading can tell "every row" from "the eligible rows".
LIBRARIES: Tuple[Tuple[str, str], ...] = (
    ("Films", "movies"),
    ("Movies", "movies"),
    ("Shows", "tvshows"),
    ("Music", "music"),
)

#: The throwaway seat. Fixed rather than random, for the reason the instance's label is fixed: a
#: run that was killed leaves a name the next run can recognise.
SEAT = "atrium-probe-user-views"
PLAYLIST = "atrium-probe-user-views"

#: The two row types `/UserViews` answers with, spelled as the reference spells them.
COLLECTION_FOLDER = "CollectionFolder"
USER_VIEW = "UserView"

#: What the identifier is expected to resolve to.
ROOT_TYPE = "UserRootFolder"

DOCUMENT = "docs/compatibility/behaviours.md"
SECTION = "section 1.7, as corrected on 2026-09-03"
EXPECTATION = (
    "behaviours section 1.7: ParentId is present on every /UserViews row and never omitted; a "
    "row that is the library's own CollectionFolder carries the identifier of the UserRootFolder "
    "it hangs off, and only a synthesised UserView row carries the explicit null - so the two "
    "kinds arrive in one response and the null is not a property of the route"
)


def load(name: str) -> Any:
    """A sibling of this script, loaded by path and on first use, never at import."""
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, HERE / (name + ".py"))
    if spec is None or spec.loader is None:  # pragma: no cover - the files are beside this one
        raise SystemExit(f"tools/{name}.py could not be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def build_tree(directory: Path) -> Path:
    """One empty directory per library. A library root is a row whether or not anything is in it."""
    shutil.rmtree(directory, ignore_errors=True)
    for name, _ in LIBRARIES:
        (directory / name).mkdir(parents=True, exist_ok=True)
    return directory


class Row:
    """One `/UserViews` row, reduced to the four things the question is about."""

    def __init__(self, body: Dict[str, Any]) -> None:
        self.name = str(body.get("Name", ""))
        self.identifier = str(body.get("Id", ""))
        self.type = str(body.get("Type", ""))
        self.collection_type = str(body.get("CollectionType") or "")
        self.present = "ParentId" in body
        self.parent = body.get("ParentId")

    @property
    def shape(self) -> str:
        """`omitted`, `null` or `identifier` - the three answers the question has."""
        if not self.present:
            return "omitted"
        return "null" if self.parent is None else "identifier"

    def __str__(self) -> str:
        return f"{self.name} ({self.type}) ParentId {self.shape}"


class Reading:
    """One condition, and the rows it answered."""

    def __init__(self, label: str, rows: List[Row]) -> None:
        self.label = label
        self.rows = rows

    def summary(self) -> str:
        if not self.rows:
            return "no rows"
        parts = [
            f"{row.name}={row.shape}" + (f" ({row.type})" if row.type == USER_VIEW else "")
            for row in self.rows
        ]
        return ", ".join(parts)


class Measurement:
    """The instance, the six readings, and what resolving the identifier answered."""

    def __init__(self) -> None:
        self.readings: List[Reading] = []
        self.identifiers: Set[str] = set()
        self.root: Dict[str, Any] = {}
        self.root_status = 0
        self.image = ""

    # -- the instance -------------------------------------------------------------------------

    @contextlib.contextmanager
    def connect(self, args: argparse.Namespace) -> Iterator[Any]:
        probe = load("_probe")
        reference = load("_reference")
        if getattr(args, "server", None):
            raise probe.ProbeError(
                "this probe refuses a server argument. Answering its question means adding "
                "libraries, grouping them and turning a server-wide view on, which is a write - "
                "so it measures only an instance it creates and destroys itself (010 spec "
                "section 3.1), never a server somebody owns"
            )
        build_tree(TREE)
        try:
            libraries = tuple(
                reference.Library(name=name, collection_type=collection_type, subpath=name)
                for name, collection_type in LIBRARIES
            )
            spec = reference.InstanceSpec(fixture_root=TREE, libraries=libraries)
            with reference.ReferenceInstance(spec) as instance:
                self.image = instance.image
                administrator = instance.administrator
                server = probe.Server(instance.url)
                server.connect(administrator.username, administrator.password, None)
                yield server
        except reference.InstanceError as failure:
            raise probe.ProbeError(str(failure)) from failure
        finally:
            shutil.rmtree(TREE, ignore_errors=True)

    # -- the readings -------------------------------------------------------------------------

    def read(self, server: Any, label: str, **params: Any) -> Reading:
        body = server.get("/UserViews", **params) if params else server.get("/UserViews")
        rows = [Row(row) for row in (body or {}).get("Items", [])]
        reading = Reading(label, rows)
        self.readings.append(reading)
        for row in rows:
            if row.shape == "identifier":
                self.identifiers.add(str(row.parent))
        return reading

    def group(self, server: Any, user_id: str, ids: List[str]) -> None:
        """Set the administrator's grouped-folder preference to exactly `ids`.

        The whole configuration object goes back, not three keys: a user configuration binds a
        complete document `[spec: UpdateUserConfiguration]`, and a partial body would reset every
        preference it did not mention while claiming to have changed the grouping.
        """
        probe = load("_probe")
        configuration = (server.get(f"/Users/{user_id}") or {}).get("Configuration")
        if not isinstance(configuration, dict):
            raise probe.ProbeError(f"GET /Users/{user_id} carried no Configuration object")
        configuration["GroupedFolders"] = ids
        status, _, answer = server.post_raw(f"/Users/{user_id}/Configuration", body=configuration)
        if status not in (200, 204):
            raise probe.ProbeError(f"could not set GroupedFolders: {status} {answer[:200]!r}")

    def folder_view(self, server: Any, enabled: bool) -> None:
        """Turn the server-wide `Folders` view on or off, whole document for the same reason."""
        probe = load("_probe")
        configuration = server.get("/System/Configuration")
        if not isinstance(configuration, dict):
            raise probe.ProbeError("GET /System/Configuration did not answer an object")
        configuration["EnableFolderView"] = enabled
        status, _, answer = server.post_raw("/System/Configuration", body=configuration)
        if status not in (200, 204):
            raise probe.ProbeError(f"could not set EnableFolderView: {status} {answer[:200]!r}")

    def resolve(self, server: Any) -> None:
        """Fetch the identifier every `CollectionFolder` row named, and say what it is.

        Through `/Items/{itemId}` rather than by inference: *"it must be the root"* is the kind of
        claim this repository asks a probe for, and a value that named nothing fetchable would be
        a different finding from one that names an item a client can open.
        """
        if len(self.identifiers) != 1:
            return
        identifier = next(iter(self.identifiers))
        status, _, raw = server.get_raw(f"/Items/{identifier}")
        self.root_status = status
        if status != 200:
            return
        try:
            body = json.loads(raw.decode() or "{}")
        except ValueError:  # pragma: no cover - a 200 that is not JSON is a version difference
            return
        if isinstance(body, dict):
            self.root = body

    # -- the run ------------------------------------------------------------------------------

    def run(self, server: Any, _args: argparse.Namespace) -> Any:
        module = load("_probe")
        user_id = str(server.user_id)

        default = self.read(server, "administrator, four libraries, nothing configured")
        ids = {row.name: row.identifier for row in default.rows}

        self.resolve(server)

        self.group(server, user_id, [ids["Films"], ids["Movies"]])
        self.read(server, "two 'movies' libraries grouped")
        self.group(server, user_id, [ids["Shows"]])
        self.read(server, "one 'tvshows' library grouped")
        self.group(server, user_id, [])

        self.folder_view(server, True)
        self.read(server, "the server-wide Folders view on")
        self.folder_view(server, False)

        password = secrets.token_hex(12)
        seat_id = str(server.post("/Users/New", body={"Name": SEAT, "Password": password})["Id"])
        policy = (server.get(f"/Users/{seat_id}") or {}).get("Policy") or {}
        policy.update({"IsAdministrator": False})
        server.post_raw(f"/Users/{seat_id}/Policy", body=policy)
        seat = module.Server(server.base, timeout=server.timeout)
        seat.connect(SEAT, password, None)
        self.read(seat, "a restricted seat, nothing configured")

        playlist = server.post("/Playlists", body={"Name": PLAYLIST, "UserId": user_id, "Ids": []})
        self.read(server, "after one playlist exists")

        self.read(server, "presetViews=movies", presetViews="movies")

        # Removed here rather than left to the shared register: the register is the net under a
        # run that died, not the teardown a probe is entitled to skip writing (010 spec 3.5).
        server.delete(f"/Items/{playlist['Id']}")
        server.delete(f"/Users/{seat_id}")

        return self.report(module)

    # -- the finding --------------------------------------------------------------------------

    def report(self, module: Any) -> Any:
        probe = module.Probe(
            script="probe_user_views_parent.py",
            question="what does a /UserViews row carry in ParentId, and on which rows?",
            document=DOCUMENT,
            section=SECTION,
            expectation=EXPECTATION,
        )
        probe.observe("image", self.image)
        probe.observe(
            "libraries", ", ".join(f"{name} ({kind})" for name, kind in LIBRARIES) + ", all empty"
        )
        for reading in self.readings:
            probe.observe(reading.label, reading.summary())
        probe.observe(
            "distinct identifiers", ", ".join(sorted(self.identifiers)) or "none - no row named one"
        )
        own = (
            "null"
            if "ParentId" in self.root and self.root["ParentId"] is None
            else repr(self.root.get("ParentId"))
        )
        probe.observe(
            "what the identifier is",
            f"GET /Items/<it> answered {self.root_status} {self.root.get('Name', '')!r} of type "
            f"{self.root.get('Type', '')}, whose own ParentId is {own}",
        )

        rows = [row for reading in self.readings for row in reading.rows]
        omitted = [row for row in rows if row.shape == "omitted"]
        nulls = [row for row in rows if row.shape == "null"]
        identifiers = [row for row in rows if row.shape == "identifier"]
        wrong_null = sorted({row.name + "/" + row.type for row in nulls if row.type != USER_VIEW})
        wrong_id = sorted(
            {row.name + "/" + row.type for row in identifiers if row.type != COLLECTION_FOLDER}
        )
        root_ok = (
            self.root_status == 200
            and str(self.root.get("Type")) == ROOT_TYPE
            and len(self.identifiers) == 1
        )
        holds = not omitted and not wrong_null and not wrong_id and root_ok and bool(nulls)

        if holds:
            probe.conclude(
                f"ParentId is present on all {len(rows)} rows of {len(self.readings)} readings and "
                f"omitted on none. The {len(identifiers)} CollectionFolder rows all name the one "
                f"UserRootFolder {self.root.get('Name')!r} they hang off - fetchable, and carrying "
                f"an explicit null ParentId of its own - and the {len(nulls)} explicit nulls are "
                f"every one of them a synthesised UserView. Both kinds arrive in one response, so "
                f"the null is a property of the row and never of the route",
                matches_documentation=True,
            )
        else:
            reasons = []
            if omitted:
                reasons.append(
                    "ParentId was omitted on " + ", ".join(sorted({r.name for r in omitted}))
                )
            if wrong_null:
                reasons.append(
                    "an explicit null on a row that is not a UserView: " + ", ".join(wrong_null)
                )
            if wrong_id:
                reasons.append(
                    "an identifier on a row that is not a CollectionFolder: " + ", ".join(wrong_id)
                )
            if not nulls:
                reasons.append(
                    "no reading produced an explicit null at all, so the null this repository "
                    "emits on every view row is now unmeasured"
                )
            if not root_ok:
                reasons.append(
                    f"the identifier did not resolve to one {ROOT_TYPE}: "
                    f"{len(self.identifiers)} distinct, GET answered {self.root_status}, "
                    f"type {self.root.get('Type')!r}"
                )
            probe.conclude("; ".join(reasons), matches_documentation=False)

        probe.note(
            "The two readings this probe reconciles: 2026-08-27 measured 2 explicit nulls on 6 "
            "rows of an operator's server, whose own record notes the rows reported two types, "
            "CollectionFolder and UserView; 2026-09-03's sweep measured an identifier on every "
            "row of a fresh instance, which has no synthesised view until something makes one. "
            "Neither saw the other's rows. specs/005-item-query-api/notes/item-shapes.md "
            "section 6 carries both."
        )
        probe.note(
            "Nothing overrides the null-omission setting, which behaviours section 1.7 recorded "
            "as unestablished. ParentId and ChannelId are `Guid?` assigned from a non-nullable "
            "`Guid`, so they are never CLR-null and WhenWritingNull has nothing to omit; the "
            "registered converter writes the JSON null on `Guid.Empty` and only on it "
            "`[source: src/Jellyfin.Extensions/Json/Converters/JsonNullableGuidConverter.cs:19-26 "
            "@ v10.11.11]`. That is why exactly two properties survive it."
        )
        probe.note(
            "A single grouped library of an eligible type produces no UserView and therefore no "
            "null: it collapses back to its own CollectionFolder "
            "`[source: Emby.Server.Implementations/Library/UserViewManager.cs:174-190 @ "
            "v10.11.11]`. The 'one tvshows library grouped' reading above is that condition, and "
            "it is why the grouping story needs two libraries to be told at all."
        )
        probe.note(
            "What Atrium emits is not this probe's question. Atrium sends an explicit null on "
            "every /UserViews row because it has no user root folder item; whether that stays, "
            "and what it would cost a decoder either way, is an owner's decision recorded in "
            "src/atrium/api/item_models.py."
        )
        return probe


def main() -> int:
    measurement = Measurement()
    return int(
        load("_probe").main(
            measurement.run,
            description=(
                "Measure what a /UserViews row carries in ParentId and on which rows. Stands up a "
                "single-use instance of the pinned version over four empty libraries, takes six "
                "readings across the conditions that change the answer, and destroys everything - "
                "including on failure. Never touches a server somebody owns."
            ),
            needs_writes=True,
            with_args=True,
            connect_with=measurement.connect,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
